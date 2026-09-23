# 서버 작업 지시서 (코딩 에이전트용)

> 이 문서를 코딩 에이전트에 그대로 붙여넣어라.
>
> **포팅 코드는 이미 작성되어 있다.** 남은 일은 이 서버에 맞게 설정을 채우고,
> 실제로 동작하는지 확인하는 것이다. 코드를 새로 짜는 작업이 아니다.

---

## 배경

SWE-bench 문제를 푸는 실험 코드다. **외부 메모리를 주입하면 해결률이 오르는가**를 측정한다.

```
컨트롤러(Python) ──launch──▶ 워커(에이전트 CLI, 새 세션)
                                  │
                                  │ MCP 툴 "benchmark.action" (유일한 능력)
                                  ▼
                            브로커(Python) ──▶ 저장소 체크아웃 / 테스트 실행
                                  │
                                  ├─ arm=BASELINE  → 메모리 주입 없음
                                  └─ arm=PDF_MEMORY → 동결 메모리 검색·주입
```

모델은 셸도, 파일 접근도, 웹 검색도 없다. **오직 MCP 툴 하나**로만 움직인다.
이건 버그가 아니라 실험 설계다. 두 arm의 유일한 차이를 메모리로 고정하기 위한 것이다.

원래 환경은 Windows + WSL + Codex CLI + ChatGPT 로그인 + `gpt-6-astra`였다.
목표 환경은 Linux 서버 + vLLM + GLM이다.

---

## 이미 되어 있는 것

`scripts/trimem_skhynix_host_profile.py` 가 호스트 토폴로지와 solver 신원을 한 곳에서 선언한다.
이 모듈이 다음을 처리하도록 코드가 이미 배선되어 있다.

| 문제 | 해결 방식 | 적용된 곳 |
| --- | --- | --- |
| 기록된 절대경로가 이 호스트에 없음 | 읽는 시점에 접두사 리매핑 (`remap`) | `pipeline.absolute()`, `memory._path()` |
| 새로 쓰는 증거가 다른 네임스페이스에 기록됨 | 기록 시 캡처 공간으로 역변환 (`unmap`) | `pipeline.ref()` |
| WSL 경유 호출 | 토폴로지가 `NATIVE_POSIX`면 직접 호출 | `native.controller_python()` |
| `/mnt/c` ↔ `C:` 변환 | `NATIVE_POSIX`면 항등 | `pipeline.windows_path()/linux_path()` |
| 모델·인증 하드코딩 | 선언값 참조 (리터럴 33곳 제거) | 런타임 13개 모듈 |
| ChatGPT 강제 로그인 | provider 설정으로 분기 | `native.authentication_arguments()` |
| API 키를 환경에서 제거 | 선언된 provider 키만 주입, 나머지는 계속 제거 | `native.worker_environment()` |

**중요**: 해시 검증은 그대로 살아 있다. 경로만 바뀌고 sha256은 내용 기준이라 여전히 일치해야 한다.
프로파일을 설정하지 않으면 원래 Windows/WSL 동작을 그대로 재현한다.

검증 상태: skhynix 단위 테스트가 포팅 전과 동일하게 통과하고,
프로파일 전용 테스트 19개가 추가되어 통과한다.

---

## 할 일

### STEP A. 호스트 프로파일 작성

예시가 있다: `configs/skhynix_v1/host/glm_server_example.json`
이걸 복사해서 이 서버의 실제 경로로 고쳐라.

```json
{
  "schema": "skhynix/host-profile/1.0",
  "topology": "NATIVE_POSIX",
  "path_remap": [
    {"from": "/home/trimem-runner/skhynix-architecture-scale-001", "to": "<실제 실행 루트>"},
    {"from": "/mnt/c/Users/jewon/esm-r23-d115-writer",             "to": "<이 저장소 경로>"},
    {"from": "/mnt/c/Users/jewon/AppData/Local/Temp",              "to": "<스테이징 경로>"}
  ],
  "run_root": "<실제 실행 루트>",
  "staging_root": "<스테이징 경로>",
  "controller_python": "<python3.11 절대경로>",
  "controller_environment": {"PYTHONDONTWRITEBYTECODE": "1"},
  "solver": {
    "model": "<vLLM의 --served-model-name>",
    "reasoning_effort": "high",
    "authentication": "API_KEY",
    "provider": {
      "name": "glm",
      "base_url": "http://localhost:8000/v1",
      "env_key": "GLM_API_KEY",
      "wire_api": "chat"
    }
  }
}
```

`from` 값들은 **바꾸지 마라.** 원래 캡처 호스트의 경로이고, 기록된 증거가 그 이름을 쓴다.
`to` 값만 이 서버의 실제 위치다.

적용:
```bash
export SKHYNIX_HOST_PROFILE=/path/to/your_profile.json
export GLM_API_KEY=<vLLM이 요구하는 값, 로컬 서빙이면 아무 값이나>
```

### STEP B. 메모리 뱅크를 실행 루트에 배치

동결 메모리는 저장소 안에 있고, 원래 트리 구조 그대로 미러링되어 있다:

```
artifacts/skhynix_v1/architecture_scale_001/frozen-bank-240/
  pipeline-v13/learning-240/captures/      (916개, L1 경험 원본)
  pipeline-v15/bank-240/                   (bank.json + authority sqlite)
  pipeline-v15/learning-240/               (authority sqlite, observations, proposals)
```

이 트리가 `path_remap`의 첫 번째 `to` 경로(실행 루트)에서 보여야 한다.
복사하든 bind mount를 쓰든 상관없지만, **심볼릭 링크는 안 된다** —
`memory._path()`가 링크를 거부한다. 증거 무결성을 위한 의도된 제약이다.

확인:
```bash
python3.11 scripts/trimem_skhynix_verify_portable_bank.py --bank-root <실행 루트>
```
`"status": "PASS"`, `"references_checked": 924`, `"failure_count": 0` 이어야 한다.

### STEP C. vLLM 기동

```bash
vllm serve <GLM 모델> \
  --tensor-parallel-size <GPU 수> \
  --kv-cache-dtype fp8 \
  --tool-call-parser glm47 \
  --reasoning-parser glm47 \
  --enable-auto-tool-choice \
  --served-model-name <프로파일의 solver.model과 동일하게>
```

`--tool-call-parser glm47 --enable-auto-tool-choice` 가 **필수**다.
이게 없으면 모델이 MCP 툴을 호출하지 못하고, 그러면 아무것도 못 한다.

확인:
```bash
python3.11 scripts/server_preflight.py --vllm-url http://localhost:8000/v1
```

### STEP D. 1문제 스모크 — **여기가 최대 관문**

**반드시 1문제만 먼저 돌려라.**

확인할 것: GLM이 MCP 툴 `benchmark.action`을 실제로 호출하는가.

**성공 판정**: 해당 문제 디렉터리에 `execution-audit.json`이 생기고 `passed: true`, `errors: []`

**실패하면 여기서 멈춰라.** 60문제를 돌려놓고 전부 실패인 걸 나중에 발견하는 게 최악이다.

#### 스모크가 실패하면

미확인 리스크가 하나 있다. **에이전트 CLI가 OpenAI 호환 엔드포인트 + GLM 조합에서
MCP 툴콜을 제대로 도는지는 실측 전에 알 수 없다.** vLLM 쪽은 `glm47` 파서로 지원되지만,
CLI가 기대하는 포맷과 맞는지는 별개 문제다.

진단 순서:
1. 워커 출력의 `events.jsonl`에 `mcp_tool_call` 항목이 있는가? 없으면 툴콜 자체가 안 된 것이다.
2. `completion.json`의 `transport_errors`, `outside_broker_tool_events`를 봐라.
3. vLLM 로그에서 tool call 파싱 오류를 확인하라.
4. `wire_api`를 `"responses"`로 바꿔서 재시도해볼 수 있다.

그래도 안 되면 CLI를 쓰지 않고 API를 직접 호출하는 워커를 새로 만드는 경로가 남는다.
다만 **그 경우 하네스가 달라져서 기존 Astra 결과와의 비교 가능성이 깨진다.**
이건 설계 변경이므로 임의로 진행하지 말고 보고하라.

### STEP E. 본실행

병렬 실행을 쓸 경우 `evaluation_max_workers`(1~4, 기본 1)를 설정한다.
**2로 시작해서 시간 초과율을 먼저 측정하라.** vLLM 한 대에 여러 solve가 동시에 붙으면
요청 지연이 늘고, 벽시계 예산을 쓰는 만큼 해결률이 내려갈 수 있다.
설계와 해석 주의사항은 `docs/SKHYNIX_PARALLEL_EVALUATION.md`에 있다.

A(GLM-OFF) → B(GLM-ON, Astra 메모리) 순서.
같은 문제·같은 예산·같은 채점 기준이다.
비교는 **양쪽 다 공식 판정이 나온 동일 문제끼리만** 한다.

---

## 절대 바꾸지 말 것

실험의 타당성이 여기 달려 있다. **"동작하게 만들려고" 아래를 건드리면 실험이 무효가 된다.**

| 항목 | 이유 |
| --- | --- |
| **OFF/ON 비대칭 금지** | 두 arm은 문제·모델·예산·채점이 **완전히 동일**해야 한다. 차이는 메모리뿐이다 |
| **OFF에 메모리 주입 금지** | `arm == "BASELINE"`이면 주입 0. 이 분기를 흐리지 마라 |
| **예산** | 도구 요청 120회 / 1,200초. 한쪽만 늘리면 비교가 무너진다 |
| **풀이·채점 재시도 금지** | 실패하면 실패로 기록한다. 재시도는 결과를 낙관 편향시킨다 |
| **메모리 뱅크 내용** | 동결되어 있다. 평가 중 갱신 금지 |
| **평가 경험 격리** | 평가에서 얻은 경험이 뱅크로 흘러들면 안 된다 |
| **채점 기준** | 공식 SWE-bench 하네스. FAIL_TO_PASS + PASS_TO_PASS 둘 다 만족만 `resolved` |
| **sha256 검증** | 통과시키려고 끄지 마라. 안 맞으면 원인을 찾아라 |
| **심볼릭 링크 거부** | `memory._path()`의 링크 거부를 풀지 마라 |
| **문제 집합·순서** | 고정되어 있다. 결과를 본 뒤 바꾸면 안 된다 |
| **프로파일의 `from` 경로** | 캡처 호스트의 이름이다. 기록된 증거가 이걸 참조한다 |
| **`evaluation_max_workers`는 OFF/ON 동일** | 풀이 예산 1,200초는 벽시계다. 한쪽만 병렬도를 올리면 그 arm이 경합으로 더 많은 시간을 쓰고 시간 초과가 늘어, 메모리 효과와 구분할 수 없게 된다 |

**실행이 불확실하게 중단되면 자동으로 새로 시작하지 말고 증거를 보존한 채 멈춰라.**
판정 불가는 "실패"가 아니라 **별도의 미판정**으로 기록한다.

경로나 모델 관련 오류가 나면, 코드에 값을 하드코딩하지 말고 **프로파일을 고쳐라.**
포팅의 요점이 그 값들을 한 곳에 모은 것이다.

---

## 검증

```bash
python3.11 scripts/trimem_skhynix_verify_portable_bank.py   # 메모리 무결성 (924개 참조)
python3.11 scripts/server_preflight.py                      # 환경
python3.11 -m pytest tests/unit -q -k skhynix               # 단위 테스트
```

단위 테스트는 원래 환경 기준으로 작성된 것이 있어서 일부는 이 서버에서 의미가 없을 수 있다.
**어떤 테스트가 왜 실패하는지 먼저 확인하고**, 환경 차이 때문인지 설정 실수 때문인지 구분하라.
통과시키려고 단정문(assert)을 지우지 마라.

참고 — 포팅 시점의 기준선에서 `test_trimem_skhynix_evaluate.py::test_equal_reader_mechanisms_traverse_the_existing_runtime`
하나가 실패했다. `git rev-parse HEAD`가 되지 않는 환경 문제이고, 포팅 전후 동일하다.

---

## 완료 판정

1. 메모리 검증 PASS (924개 참조)
2. 환경 점검 PASS (vLLM 포함)
3. **1문제 스모크에서 `execution-audit.json`의 `passed: true`, `errors: []`**
4. 위 "절대 바꾸지 말 것" 항목이 전부 그대로임

3번이 안 되면 1·2가 통과해도 본실행을 시작하지 마라.
