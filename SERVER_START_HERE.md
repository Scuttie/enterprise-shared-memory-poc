# 서버에서 시작하기

이 저장소를 GPU 서버로 옮겨서 **GLM으로 메모리 ON/OFF 실험**을 돌리기 위한 문서다.
순서대로 따라가면 되고, 각 단계에 "성공 판정"이 붙어 있다.

---

## 0. 이 실험이 뭔지 (30초)

문제를 풀면서 얻은 경험을 외부 메모리(L1 경험 / L2 그래프 / L3 절차)에 쌓아두고,
**새 문제를 풀 때 그 메모리를 주입하면 해결률이 오르는가**를 측정한다.
모델 파인튜닝이 아니다. 가중치는 안 건드린다.

- **OFF (BASELINE)**: 장기 메모리 검색·주입 없음
- **ON (PDF_MEMORY)**: 동결된 L1·L2·L3를 현재 하위 작업에 맞게 검색·주입
- 두 조건은 현재 작업 문맥(L0)·실행 환경·예산을 **공유**한다. 차이는 장기 메모리뿐이다.

채점은 공식 SWE-bench 하네스다. `resolved`는 FAIL_TO_PASS와 PASS_TO_PASS를 **둘 다** 만족한 경우만 뜻한다.

---

## 1. 여기서 하려는 것 (3개 arm)

메모리는 이미 만들어져 있다. `gpt-6-astra`가 240문제를 풀면서 수집했고, 저장소 안에 동결되어 있다.

| arm | 메모리 | 추가 수집 | 실행량 |
| --- | --- | --- | --- |
| **A. GLM-OFF** | 없음 | 없음 | 60문제 |
| **B. GLM-ON (Astra 메모리)** | 저장소에 포함됨 ✅ | **없음** | 60문제 |
| C. GLM-ON (GLM 자체 메모리) | 새로 만들어야 함 | 240문제 수집 | 60문제 |

**A와 B만으로 실험 하나가 완결된다** — "다른 모델이 만든 경험이 이 모델에 전이되는가".
C는 거기에 "자기가 만든 경험이면 더 나은가"를 붙이는 것이고, **전체 비용의 대부분이 C에 있다.**
A+B 먼저 끝내고 결과를 보고 C를 할지 정하는 걸 권한다.

문제 집합은 이미 고정되어 있다. 수집 240 / 개발 60 / 최종 500이고 **서로 교집합 0개**다.
(`configs/skhynix_v1/architecture_scale_001/protocol.json`)

---

## 2. 서버에서 할 일 — 순서대로

### STEP 1. 압축 풀고 메모리 무결성 확인

```bash
unzip skhynix-memory-experiment-main.zip
cd skhynix-memory-experiment-main
python3.11 scripts/trimem_skhynix_verify_portable_bank.py
```

**성공 판정**: `"status": "PASS"`, `"references_checked": 924`, `"failure_count": 0`

이게 PASS면 Astra 메모리 919개 경험 / 4,653노드 / 4,193엣지 / L3 절차 1개가 온전히 넘어온 것이다.
FAIL이면 ZIP이 잘렸거나 파일이 빠진 것이니 다시 받아라. **여기서부터 막히면 그 다음은 의미 없다.**

> 메모리는 절대경로 + sha256으로 고정되어 있다. 검증기가 원래 캡처 호스트의 경로를
> 저장소 안 사본으로 바꿔서 확인한다. 해시는 내용 기준이라 호스트가 바뀌어도 그대로 유효하다.

### STEP 2. 환경 점검

```bash
python3.11 scripts/server_preflight.py
```

Python 3.11 / Docker / GPU / 메모리 뱅크 / 필수 파일을 한 번에 확인하고 `PASS`·`FAIL`을 항목별로 찍는다.

필요한 것:
- **Python 3.11**
- **Docker** — 공식 SWE-bench 채점에 per-instance 이미지가 필요하다
- **GPU** — 아래 3번 참고
- **vLLM** — GLM 서빙용

### STEP 3. 설정 (포팅 코드는 이미 들어 있다)

이 코드는 원래 **Windows + WSL + Codex CLI + ChatGPT 로그인**에서 돌던 것이다.
Linux + vLLM + GLM에서 돌리기 위한 **포팅은 이미 되어 있다.** 남은 건 설정이다.

`scripts/trimem_skhynix_host_profile.py` 가 호스트 토폴로지와 solver 신원을 한 곳에서 선언하고,
런타임 코드가 전부 그 선언을 참조하도록 배선되어 있다. 프로파일 JSON 하나로:

- WSL 경유 호출이 직접 호출로 바뀐다
- 기록된 경로가 이 서버 위치로 매핑된다 (파일은 다시 쓰지 않는다, 해시는 그대로 유효)
- 모델이 `gpt-6-astra`/ChatGPT 로그인에서 GLM/API 키로 바뀐다

예시: `configs/skhynix_v1/host/glm_server_example.json`

**→ [`docs/port/AGENT_BRIEF.md`](docs/port/AGENT_BRIEF.md) 를 사내 코딩 에이전트에 통째로 붙여넣어라.**
프로파일 작성부터 스모크까지 STEP A~E로 적혀 있다.

### STEP 4. 스모크 테스트 (1문제) — **여기가 최대 관문**

포팅이 끝나면 **반드시 1문제만** 먼저 돌려라.

확인할 것: GLM이 MCP 툴 `benchmark.action`을 제대로 호출하는가.
이 실험에서 모델의 유일한 능력은 그 툴 하나다. 셸도 없고 파일 접근도 없다.
툴콜이 안 되면 모델이 아무것도 못 하고, 그건 메모리 실험 이전의 문제다.

**성공 판정**: 해당 문제 디렉터리에 `execution-audit.json`이 생기고 `passed: true`, `errors: []`

**실패하면 여기서 멈춰라.** 60문제를 돌려놓고 전부 실패인 걸 나중에 발견하는 게 최악이다.

### STEP 5. 본실행

A(OFF) → B(ON) 순서. 같은 문제·같은 예산·같은 채점 기준이다.
비교는 **양쪽 다 공식 판정이 나온 동일 문제끼리만** 한다.

---

## 3. GPU / 모델 선택

| | GLM-5.3-Flash | GLM-5.3 |
| --- | --- | --- |
| 파라미터 | 321B total / 18B active (MoE) | ~744B급 / 40B active |
| 기본 체크포인트 | 네이티브 FP8 | FP8 |
| 가중치만 | **~306 GiB** | **~860 GiB+** |
| 최소 구성 | 4×H200 / 8×H100 / 2×B200 | 8×H200 |

`scripts/server_preflight.py` 가 이 호스트의 총 VRAM을 위 수치와 비교해 알려준다.

```bash
vllm serve zai-org/GLM-5.3-Flash \
  --tensor-parallel-size 4 \
  --kv-cache-dtype fp8 \
  --tool-call-parser glm47 \
  --reasoning-parser glm47 \
  --enable-auto-tool-choice \
  --served-model-name glm
```

`--tool-call-parser glm47 --enable-auto-tool-choice`가 **필수**다. 이게 STEP 4의 툴콜을 가능하게 한다.

INT4 양자화로 VRAM을 줄일 수는 있지만, 그러면 **평가 대상 모델 자체가 바뀐다.**
양자화 손실이 해결률에 섞이므로 결과를 보고할 때 반드시 명시해야 한다.

---

## 4. 알아둘 것

**지금 저장소에 있는 것**
- 실행 코드 전체 (`scripts/`)
- **Astra 동결 메모리 전체** (`artifacts/skhynix_v1/architecture_scale_001/frozen-bank-240/`, 186MB, 924개 참조)
- 문제 분할·프로토콜·설정 (`configs/skhynix_v1/`)
- 이전 Astra 실행 결과와 보고서 (`reports/`)

**저장소에 없는 것 (서버에서 따로 준비)**
- SWE-bench per-instance Docker 이미지
- GLM 가중치
- vLLM

**이전 Astra 실험 상태 (동결됨, 참고용)**
- 경험 수집 240문제 완료 → 메모리 동결
- 개발 OFF 13/15 해결(86.7%), 채점 보류 1건, 사용량 한도로 중단 1건
- **개발 ON은 시작 전** → OFF/ON 비교쌍이 0개라 **메모리 효과는 아직 측정된 적 없다**
- 86.7%는 고정 순서의 앞 15문제이고 무작위 표본이 아니다. 벤치마크 점수로 인용하면 안 된다.

**결과 해석 주의**
- 60문제 중 15문제만 Astra 공식 판정이 있다. GLM 결과를 Astra와 비교하려면 같은 문제끼리만 비교해야 한다.
- 채점 보류(`no_tests_collected` 등)는 해결·미해결 어느 쪽도 아니다. 별도로 집계한다.
- 미판정이 남아 있으면 전체 해결률 차이를 확정값으로 제시하지 않는다.
