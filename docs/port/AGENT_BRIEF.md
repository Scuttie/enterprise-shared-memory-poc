# 포팅 작업 지시서 (코딩 에이전트용)

> 이 문서를 코딩 에이전트에 그대로 붙여넣어라. 작업 2개(T1, T2)와 금지사항이 적혀 있다.

---

## 배경

SWE-bench 문제를 푸는 실험 코드다. **외부 메모리를 주입하면 해결률이 오르는가**를 측정한다.

현재 구조:

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

원래 환경: Windows + WSL(`TriMemRunner2404`) + Codex CLI + ChatGPT 로그인 + `gpt-6-astra`
목표 환경: Linux 서버 + vLLM + GLM (OpenAI 호환 API)

---

## T1. 경로 이식 — WSL 제거 + 루트 리매핑

### 배경

이 코드는 모든 증거 파일을 **절대경로 + sha256** 쌍으로 고정한다. 데이터 파일(JSON) 안에
원래 호스트의 절대경로가 기록되어 있다. 호스트가 바뀌면 경로가 안 맞는다.

**해시는 파일 내용 기준이므로 호스트가 바뀌어도 그대로 유효하다.**
따라서 **데이터 파일을 다시 쓰지 말고, 읽는 시점에 경로 접두사만 바꿔라.**
데이터를 다시 쓰면 모든 해시가 깨지고 증거 사슬이 무너진다.

이미 검증된 선례가 있다: `scripts/trimem_skhynix_verify_portable_bank.py`가
메모리 뱅크 924개 참조에 대해 정확히 이 방식(접두사 치환 + 해시 검증)으로 PASS한다.
같은 패턴을 코드 전체에 적용하는 것이 T1이다.

### 고칠 곳

| # | 파일 | 위치 | 현재 | 목표 |
| --- | --- | --- | --- | --- |
| 1 | `scripts/trimem_skhynix_architecture_native.py` | `wsl_python()` (59행 부근) | `["wsl.exe", "-d", "TriMemRunner2404", "--user", ..., "--exec", "env", ...]` | WSL 경유 제거. 서버 Python을 직접 호출 |
| 2 | `scripts/trimem_skhynix_architecture_pipeline.py` | `windows_path()` / `linux_path()` (79~93행) | `/mnt/c` ↔ `C:` 변환 강제 | 네이티브 Linux에선 항등 변환. `/mnt/c` 강제를 풀어라 |
| 3 | `scripts/trimem_skhynix_architecture_pipeline.py` | `absolute()` / `ref()` / `check()` (44~62행) | 기록된 절대경로 그대로 사용 | 여기에 접두사 리매핑 훅을 넣어라 |
| 4 | `scripts/trimem_skhynix_architecture_memory.py` | `_path()` (51행) | 동일 | 동일. 심볼릭 링크 거부는 **유지**하라 |
| 5 | `scripts/trimem_skhynix_architecture_scale_setup.py` | 51행, 78행 | `/mnt/c/Users/jewon/AppData/Local/Temp`, `/home/trimem-runner/...` 하드코딩 | 설정값으로 |

### 설계 지침

- 리매핑 규칙은 **설정 파일 한 곳**에 두고 `{원래 루트: 새 루트}` 형태로 선언하라.
  코드 곳곳에 경로 문자열을 흩뿌리지 마라.
- `_path()`의 심볼릭 링크 거부는 유지하라. 링크로 우회하면 증거 무결성이 깨진다.
- 리매핑 후에도 **sha256 검증은 그대로 수행**되어야 한다. 검증을 끄거나 완화하지 마라.

### 수용 기준

- `python3.11 scripts/trimem_skhynix_verify_portable_bank.py` → `"status": "PASS"`, 924개 참조
- `python3.11 scripts/server_preflight.py` → 경로 항목 PASS
- 기존 단위 테스트가 깨지지 않을 것 (아래 "검증" 참고)

---

## T2. provider 교체 — 고정된 모델/인증을 설정값으로

### 배경

현재 코드는 `gpt-6-astra` + ChatGPT 로그인을 **하드코딩으로 강제**한다.
GLM으로 바꾸려면 이 고정을 설정값으로 바꿔야 한다.

가장 중요한 지점 — `scripts/trimem_skhynix_architecture_native.py`:

- **164행**: `if config.get("model") != "gpt-6-astra" or config.get("authentication") != "CHATGPT": raise`
- **168행**: `-c 'forced_login_method="chatgpt"'`
- **194~196행**: 환경변수에서 `OPENAI_API_KEY`·`CODEX_API_KEY`를 **의도적으로 제거**

즉 API 키가 "필요 없는" 게 아니라 **코드가 키 사용을 능동적으로 막고 있다.**

### 고칠 곳

같은 패턴(`"gpt-6-astra"` / `"CHATGPT"` / `"CHATGPT_FORCED"` 리터럴 비교)이
**13개 모듈에 26곳** 있다. 전부 찾으려면:

```bash
grep -rn 'gpt-6-astra\|CHATGPT\|forced_login_method' scripts/trimem_skhynix_architecture_*.py
```

해당 모듈: `broker` `learning` `native` `pipeline` `plan` `quarantine`
`reflection_recovery` `run` `scale_pipeline` `semantic_publish` `semantic_reflection`

### 설계 지침

- 26곳을 개별 수정하지 마라. **선언된 solver 신원(모델명·인증방식·추론강도)을
  한 모듈에 정의하고**, 각 지점이 그 값을 참조하게 바꿔라.
- 검증 자체는 **유지**하라. "선언된 값과 실제 실행값이 일치하는지" 확인하는 로직이다.
  고정 대상만 설정값으로 바뀌는 것이지, 검증을 없애는 게 아니다.
- 워커 실행 커맨드에 OpenAI 호환 provider 설정을 추가하라
  (`base_url`, `wire_api="chat"`, API 키 환경변수).
- 키 제거 로직(194~196행)은 **삭제가 아니라 반전**이다.
  선언된 provider의 키만 주입하고 나머지는 계속 제거하라.

### 미확인 리스크 (반드시 먼저 검증할 것)

에이전트 CLI가 OpenAI 호환 엔드포인트 + GLM 조합에서 **MCP 툴콜을 제대로 도는지는
실측 전에 알 수 없다.** vLLM 쪽은 `--tool-call-parser glm47 --enable-auto-tool-choice`로
지원되지만, CLI가 기대하는 포맷과 맞는지는 별개다.

**T2를 끝내면 60문제를 돌리기 전에 반드시 1문제 스모크를 통과시켜라.**
안 되면 CLI를 쓰지 않고 직접 API를 호출하는 워커를 새로 만드는 경로를 검토해야 한다.
(단 그 경우 하네스가 달라져서 기존 Astra 결과와의 비교 가능성이 깨진다.)

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
| **문제 집합·순서** | 고정되어 있다. 결과를 본 뒤 바꾸면 안 된다 |

**실행이 불확실하게 중단되면 자동으로 새로 시작하지 말고 증거를 보존한 채 멈춰라.**
판정 불가는 "실패"가 아니라 **별도의 미판정**으로 기록한다.

---

## 검증

```bash
# 메모리 무결성
python3.11 scripts/trimem_skhynix_verify_portable_bank.py

# 환경
python3.11 scripts/server_preflight.py

# 단위 테스트
python3.11 -m pytest tests/unit -q
```

단위 테스트는 원래 환경 기준으로 작성된 것이 있어서 일부는 서버에서 의미가 없을 수 있다.
**어떤 테스트가 왜 실패하는지 먼저 확인하고**, 환경 차이 때문인지 포팅 실수 때문인지 구분하라.
통과시키려고 단정문(assert)을 지우지 마라.

---

## 완료 판정

1. 메모리 검증 PASS (924개 참조)
2. 환경 점검 PASS
3. **1문제 스모크에서 `execution-audit.json`의 `passed: true`, `errors: []`**
4. 위 "절대 바꾸지 말 것" 항목이 전부 그대로임

3번이 안 되면 1·2가 통과해도 본실행을 시작하지 마라.
