# LiveCodeBench: 사내 Linux 컨테이너 전달 안내

2026-09-23. 이 경로는 이미 제공된 Linux 컨테이너와 사내 GLM/vLLM 서비스를
대상으로 한다. 추가 Docker 설치·데몬·소켓·GPU·모델 서버 설치를 요구하지 않는다.
기존 SWE-bench용 `AGENT_BRIEF.md`의 Docker/GPU 설치 절차를 적용하지 않는다.

## 같은 저장소에서 관리한다

개발 저장소는 기존 `enterprise-shared-memory-poc`의 작업 사본이며, 브랜치는 `codex/trimem-coder-v1`이다.
현재 push 대상은 추적 remote `private`의 비공개 `Scuttie/skhynix-memory-experiment`다.
개발 PC의 경로는 `C:\Users\jewon\esm-r23-d115-writer`이지만 아래 프로그램의 실행
입력에는 그 경로를 고정하지 않는다. 서버에서는 원하는 디렉터리에 checkout한다.

GitHub에는 **커밋된 파일만** 전달된다. 작업 디렉터리의 새 파일·가상환경·캐시가
자동으로 따라가지 않는다. 릴리스 시 코드·설정·문제 분할·의존성 잠금·실행 안내의
commit SHA를 기록하고, 두 실행 장소에서 같은 버전을 사용한다.

| 구성 | 전달 방식 | 현재 상태 |
| --- | --- | --- |
| `scripts/trimem_lcb_grade.py` | Git 저장소 | 공식 로컬 추출기·채점기 연결 구현 및 합성 검증 완료 |
| `scripts/trimem_lcb_smoke.py` | Git 저장소 | 호스트 경로를 받는 합성 정답/오답 검사 |
| `tests/unit/test_trimem_lcb_*.py` | Git 저장소 | 제출 누락·채점 오류·검증 실패 처리 회귀 검사 |
| `configs/skhynix_v1/lcb_eval_py310.lock` | Git 저장소 | 검증 환경의 패키지 버전·배포 파일 해시 고정 |
| `scripts/trimem_lcb_dataset.py` | Git 저장소 | 고정 원본의 공개 입력·비공개 채점 분리와 가족 단위 시간 분할 |
| `scripts/trimem_lcb_memory.py` | Git 저장소 | 기존 메모리 저장·검색·승격 조건 재사용, train만 쓰기 |
| `scripts/trimem_lcb_native.py` | Git 저장소 | 제한된 도구를 사용하는 Astra native 세션 |
| `configs/skhynix_v1/lcb_001_pilot.json` | Git 저장소 | train 24개·valid 24쌍 pilot 설정 |
| `configs/skhynix_v1/lcb_001_public_split.json` | Git 저장소 | 전체 train 767·valid 106·test 182의 고정 ID·해시 |
| `configs/skhynix_v1/lcb_runtime_py310.lock` | Git 저장소 | 메모리용 SQLAlchemy 포함 43개 패키지 버전·배포 해시 |
| 공식 LiveCodeBench 코드 | 고정 commit의 별도 Git bundle 또는 checkout | `28fef95ea8c9f7a547c8329f2cd3d32b92c1fa24` |
| 벤치마크 데이터·채점용 배치 | 별도 승인된 반입 저장소/파일 | 원본 6개 해시 검증, 공개 입력과 분할 동결 완료; 비공개 추출 상태는 실행 보고서 참고 |
| Python 패키지 wheel 묶음 | 대상 환경에 맞춰 별도 반입 | wheelhouse 조립 및 오프라인 재설치 검증 미완료 |
| API 주소·인증 | 서버의 로컬 설정·환경변수 | Git에 실제 키·사내 주소를 넣지 않음 |

**Astra native 실행, 경험 저장·동결·검색과 공식 채점 경로를 구현했다.**
실제 GLM 모델 호출에는 사내 vLLM HTTP 어댑터와 서버별 연결 검증이 추가로 필요하다.
같은 ID로 GLM 자체 train 경험을 모으고 같은 valid/test를 평가한다. Astra의 경험을
GLM에 주는 전이 실험과 구분한다. 현재 진행 상태와 프로토콜은
[실험 보고서](../../reports/SKHYNIX_LCB_001_EVALUATION.md)를 기준으로 한다.

## 1. 외부 네트워크가 있는 준비 환경

검증한 환경은 Linux x86_64 / CPython 3.10.21이다. 대상의 CPU 아키텍처,
Python 버전, glibc와 wheel 호환성을 확인하고 같은 플랫폼에서 묶음을 준비한다.
다른 Python 버전을 사용할 때에는 해당 버전으로 새 설치 검증과 잠금을 남긴다.
기존 가상환경은 절대경로가 포함되므로 그대로 복사하지 않는다.

아래 명령의 상대경로 기준은 이 프로젝트 저장소다. `lcb-handoff-assets`는
Git에 넣지 않는 별도 반입 디렉터리의 예시다.

```sh
export LCB_ASSETS=/path/to/lcb-handoff-assets
mkdir -p "$LCB_ASSETS/wheelhouse"

python3.10 -m pip download --require-hashes --only-binary=:all: \
  -r configs/skhynix_v1/lcb_runtime_py310.lock \
  --dest "$LCB_ASSETS/wheelhouse"

git clone https://github.com/LiveCodeBench/LiveCodeBench.git "$LCB_ASSETS/LiveCodeBench"
git -C "$LCB_ASSETS/LiveCodeBench" checkout --detach \
  28fef95ea8c9f7a547c8329f2cd3d32b92c1fa24
git -C "$LCB_ASSETS/LiveCodeBench" bundle create "$LCB_ASSETS/LiveCodeBench.bundle" HEAD
```

공식 코드의 `pip install -e .`는 실행하지 않는다. upstream의 전체 모델 추론
의존성 대신 위 채점용 잠금을 쓴다. GitHub 접근이 안 되는 서버에는 프로젝트의
확정된 릴리스 소스와 공식 코드 bundle을 승인된 경로로 함께 반입한다.

데이터는 `livecodebench/code_generation_lite`, `release_v6`, revision
`0fe84c3912ea0c4d4a78037083943e8f0c4dd505`를 사용한다. 원본 6개 JSONL 합계는
약 4.18 GiB이며, 캐시·추출본·결과 저장 공간은 별도다. 이 데이터와 비공개 테스트·
참조 답안은 프로젝트 Git에 추가하지 않는다. 데이터 출처·원본 해시·선별 ID·변환
코드 해시·배치 해시를 반입 manifest에 기록하는 exporter는 후속 구현 대상이다.

현재 채점기는 입력 파일 전체를 메모리에 읽으므로 **예정 ID만 담은 작은 로컬
채점 배치**를 사용한다. 전체 4.18 GiB를 하나의 채점 입력으로 합치지 않는다.
비공개 채점 자료와 모델에 제공하는 문제·공개 예제는 별도 경로로 관리한다.

## 2. 사내 컨테이너에서 오프라인 설치

프로젝트 릴리스 소스로 이동한 후, 반입 경로와 작업 경로를 지정한다.
아래 `python3.10`은 해당 버전이 준비되어 있다는 전제다. 시스템 Python을 교체하지 않는다.

```sh
export LCB_ASSETS=/path/to/imported/lcb-handoff-assets
export LCB_RUN=/path/to/writable/lcb-run
mkdir -p "$LCB_RUN"

python3.10 -m venv "$LCB_RUN/venv"
"$LCB_RUN/venv/bin/python" -m pip install --no-index --require-hashes \
  --only-binary=:all: --find-links "$LCB_ASSETS/wheelhouse" \
  -r configs/skhynix_v1/lcb_runtime_py310.lock
"$LCB_RUN/venv/bin/python" -m pip check

git clone "$LCB_ASSETS/LiveCodeBench.bundle" "$LCB_RUN/LiveCodeBench"
git -C "$LCB_RUN/LiveCodeBench" checkout --detach \
  28fef95ea8c9f7a547c8329f2cd3d32b92c1fa24

export PYTHONDONTWRITEBYTECODE=1
export HF_HUB_OFFLINE=1
export HF_DATASETS_OFFLINE=1
```

Git은 공식 평가 코드의 commit·수정 여부 검사에 필요하다. `.git`이 빠진 단순
소스 ZIP은 현재 `--official-repo` 검사를 통과하지 않는다. `PYTHONDONTWRITEBYTECODE`
설정은 공식 checkout 안에 생성된 캐시가 미추적 변경으로 잡히는 일을 방지한다.

## 3. 모델 호출 없는 설치 검사

```sh
"$LCB_RUN/venv/bin/python" scripts/trimem_lcb_smoke.py \
  --official-repo "$LCB_RUN/LiveCodeBench" \
  --output-dir "$LCB_RUN/smoke-001"
```

`smoke-001`은 새 디렉터리여야 한다. 표준입출력·함수 호출 합성 문제에서
정답 **2/2**, 의도한 오답 **0/2**, 채점 보류 **0건**이어야 통과한다.
결과는 `smoke-report.json`에 기록된다. 이는 모델 해결률이 아니다.
이 검사는 모델 서버·API 키·외부 네트워크·Docker가 없어도 실행된다.

개발 호스트의 별도 Linux 환경에서 위 wrapper의 실제 실행을 확인했다.
정답 2/2·오답 0/2이며, grader와 wrapper 단위 테스트 총 **41개**가 통과했다.
[검증 영수증](../../artifacts/skhynix_v1/lcb_001/portable-smoke-002/smoke-report.json).
이는 기존에 설치한 개발용 venv에서의 검증이다. 별도 wheelhouse만 사용한 새 설치와
실제 사내 컨테이너 검증은 아직 남아 있다.

미리 생성한 실제 문제 답안의 채점은 다음 형식이다. 데이터는 숨은 테스트를 포함하는
평가자 전용 배치이므로 문제풀이 모델의 작업 폴더에 넣지 않는다.

```sh
"$LCB_RUN/venv/bin/python" scripts/trimem_lcb_grade.py \
  --official-repo "$LCB_RUN/LiveCodeBench" \
  --dataset-json /path/to/evaluator-only/batch.json \
  --dataset-sha256 BATCH_SHA256 \
  --predictions /path/to/predictions.json \
  --output "$LCB_RUN/grade-001.json"
```

## 실제 메모리 실험을 넘기기 전 남은 작업

1. 원본 데이터 검증, 작은 채점 배치·모델용 문제 export, source/dev/main 분할 동결.
2. Astra native 실행기와 GLM/vLLM 실행기를 공통 문제·도구·기록 규칙에 연결.
3. 동일 모델의 OFF/ON 예산을 고정하고 L0~L3 수집·검색·은행 동결 흐름 연결.
4. 실제 GLM ID, API 주소/인증, 컨텍스트·출력·병렬 제한, timeout·재개 동작 확인.
5. 새 환경에 반입한 파일만으로 합성 검사와 실제 문제 1개를 완주한 뒤 개발 평가.

모델 대기·생성·도구 실행·채점·총 시간, 호출·토큰·메모리 노출과 누락/오류를
기록한다. 사내 endpoint 및 인증 정보는 로컬 설정으로 넣고 결과 보고서는
그 값을 포함하지 않는다. Astra와 GLM의 주 비교는 각 모델 안에서의 ON−OFF다.
