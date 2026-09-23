# 공개 벤치마크 선정: 로컬 Astra / 사내 GLM

2026-09-23 조사. 대상 환경은 이미 제공된 Linux 컨테이너, Python,
사내 vLLM의 GLM 서비스이며 추가 Docker 데몬·소켓·중첩 컨테이너를 요구하지 않는다.

**권고: LiveCodeBench로 공통 실행·채점을 먼저 연결하고, ClassEval-Pro를
구조적 코드 생성의 보완 평가로 검증한다.** 같은 공개 문제에서 각 모델의
메모리 OFF/ON 차이를 측정한다. 저장소 수준 L2의 효과까지 주장하려면 별도의
저장소 벤치마크가 필요하다. 아래 우선순위는 실행 가능성·재사용·과제 적합성에
근거하며, 메모리 상승이 나오는 벤치마크를 골랐다는 뜻이 아니다.

이번에는 공식 문서·실행 코드·기존 저장소 기록과 공개 데이터 메타데이터를
확인했다. 새 모델 호출, 채점 실행, 패키지 설치는 하지 않았다. 사내에서의
실행 가능성은 아직 실측 전이다. 기존 v20 평가 설정과 프로세스도 변경하지 않았다.

## 후보 비교

| 후보 | 추가 Docker 없이 실행 | 규모·측정 대상 | 판단 |
| --- | --- | --- | --- |
| **LiveCodeBench** | 공식 로컬 Python 채점기. 이 저장소에 실행 기록과 어댑터 존재 | 고정 후보 `release_v6`: 1,055문제. 알고리즘·프로그램 정확성 | **첫 연결·본평가 후보**. 다른 문제의 풀이 교훈 전이에 적합. 실제 저장소 L2를 검증하는 과제는 아님 |
| **ClassEval-Pro** | 공개 `common/evaluate.py`가 importlib·unittest로 채점 | 실제 배포 JSON 300문제, 소개상 11개 영역. 메서드·상태가 얽힌 클래스 생성 | **보완 평가 우선 후보**. L0 작업 분해·L1/L3 교훈·클래스 내부 관계를 살펴볼 수 있음. 전체 저장소 수준 효과로 확대 해석하지 않음 |
| **BigCodeBench-Instruct** | 공식 `--execution local` 지원 | Full 1,140 / Hard 148. 라이브러리 활용 코드 생성 | **의존성 준비 후 후보**. 현재 검증된 환경은 공식 Python 3.10 이미지; 이미지 없이 동일 환경을 새로 재현해야 함 |
| **DS-1000** | 공식 로컬 Conda/Python 평가. 이 저장소에 독립 grader 존재 | 1,000문제, NumPy/Pandas 등 데이터 과학 라이브러리 | 활용 가능하지만 과학계산 의존성이 무겁고 난도 적합성 확인 필요 |
| **HumanEval+/MBPP+** | EvalPlus 로컬 평가 가능, MBPP+ 어댑터 존재 | 비교적 짧은 함수 생성·강화 테스트 | 연결 확인·보조 점수용. 메모리 구조 전체의 대표 평가로 삼지 않음 |
| **BugsInPy** | 원본 checkout/compile/test 스크립트에 native 실행 경로 | 원 발표 493개 실제 버그 / 17개 저장소 | **후속 저장소 평가 후보**. L2·L3에 더 직접적이나 여러 Python·패키지·시스템 라이브러리의 재현과 자료 이용 조건 확인 필요 |

공식 근거: [LiveCodeBench](https://github.com/LiveCodeBench/LiveCodeBench),
[ClassEval-Pro](https://github.com/ian-Kappa/ClassEval-Pro),
[BigCodeBench 로컬 실행](https://github.com/bigcode-project/bigcodebench/blob/main/ADVANCED_USAGE.md),
[DS-1000](https://github.com/xlang-ai/DS-1000),
[EvalPlus](https://github.com/evalplus/evalplus),
[BugsInPy compile](https://github.com/soarsmu/BugsInPy/blob/master/framework/bin/bugsinpy-compile).

## 1. LiveCodeBench를 먼저 연결하는 이유

공식 `custom_evaluator`는 모델이 따로 생성한 결과를 받아 채점한다. 따라서
Astra와 GLM이 같은 형식의 최종 코드를 제출하고 동일한 테스트를 실행하도록
연결할 수 있다. 모델 서버를 평가 컨테이너에 새로 띄울 필요가 없다.
[공식 custom evaluation](https://github.com/LiveCodeBench/LiveCodeBench#custom-evaluation).

재사용할 로컬 경로는 `scripts/r11_lcb_run.py`의 공식 `extract_code`와
`codegen_metrics` 연결, `.github/workflows/ci-r11-lcb.yml`의 평가용 설치 구성이다.
기존 기록에는 Linux/Python 3.10에서 `datasets==2.21.0`, `pebble`, `numpy`,
`tqdm`, `pyext`를 사용해 정답 20/20 통과·의도적 오답 0/20의 점검이 남아 있다.
이것은 과거 환경의 검증이며 현재 사내 환경 검증으로 대체하지 않는다.
[기존 실행 보고](R11_MAIN_COMPLETE.md).

그 실행기는 Solar 인증을 가정하므로 그대로 재사용하지 않는다. 채점·문제 읽기
부분을 분리하고 Astra native 세션/CLI와 사내 GLM HTTP 연결을 새로 연결한다.
전체 upstream 의존성에는 로컬 추론용 `torch`, `vllm`도 있으므로 **평가용 의존성만
분리**해야 기존 모델 서비스를 쓰는 클라이언트가 불필요한 GPU 설치를 요구하지 않는다.

데이터 선택에는 다음 기록상의 주의점이 있다.

- 기존 실제 R11 본실행은 `code_generation_lite / release_v6`다. 오래된 lock와 CI 주석의
  “lite는 smoke만, main은 full” 문구를 새 실험 명세로 복사하지 않는다.
- 코드 commit `28fef95ea8c9f7a547c8329f2cd3d32b92c1fa24`를 이번에도 확인했다.
  기존 데이터 revision은 `0fe84c3912ea0c4d4a78037083943e8f0c4dd505`다.
  새 실행은 데이터·테스트 변형·분할·실행기를 별도 manifest로 고정해야 한다.
- 기존에는 source pool 873문제와 2025년 1~4월 target 182문제로 나눴다.
  이 분할은 재사용 후보이며 새 실험에 아직 채택·동결하지 않았다.
- `release_latest`를 두 환경에서 각각 내려받으면 같은 평가가 아닐 수 있다.
  공개 시점만으로 현재 Astra·GLM의 사전학습 노출이 없다고 단정하지 않는다.
- 도구를 쓰며 수정하는 agent 실험이면 공개 문제와 공식 채점기를 활용한
  **우리 agent 프로토콜의 해결률**로 보고한다. 기존 단발 생성 리더보드와
  예산·수정 횟수가 같다고 주장하지 않는다.

## 2. ClassEval-Pro 확인 범위

공식 commit `6ec785c7068e0e7d36374e2890ebf473f88dd306`의 `data.json`을
내용 출력·실행 없이 구조적으로 검사했다. 300개 고유 task ID와 빈 목록이 아닌
`test_classes`를 확인했다. 원본 데이터 SHA256은
`f6bcb748819f6f2e39f3d6635c76a8310f5cbee55f08154f9dd726522decb2e3`다.
저장소는 MIT를 명시한다. 모델 생성 부분은 Azure 연동 예시이므로 우리 모델
연결부를 사용하고, 공식 테스트·채점 의미를 보존해야 한다.
[공식 실행·평가 설명](https://github.com/ian-Kappa/ClassEval-Pro#evaluation).

정적 import 조사에는 NumPy와 task 내부 모듈 이름이 나타났다. 따라서
“표준 라이브러리만 있으면 300문제 전부 준비 완료”라고 하지 않는다.
`skeleton`은 실행 모듈이 아닌 프롬프트 문자열이므로 그 필드의 AST 파싱 실패를
문제 오류로 세지 않았다. 실제 정답 실행·오답 거부·독립 프로세스 정리·파일 경계와
의존성 검증이 다음 단계다. 원본 데이터의 `solution_code`와 `test`는 모델 입력에
노출하지 않는다. 구성에 재사용된 원천 클래스·유사 문제는 같은 분할에 묶어
source→target 유출을 점검한다.

[메타데이터 검사 원본](../artifacts/skhynix_v1/container_native_benchmark_selection_20260923/metadata-audit.json).
이 기록은 채점 통과나 사내 오프라인 실행을 인증하는 기록이 아니다.

## 우선순위를 낮춘 후보의 이유

BigCodeBench는 로컬 실행이 가능하지만, 현재 upstream 평가 requirements에는
구형 NumPy/SciPy/TensorFlow 등 많은 핀이 있다. 저장소 최종 lock은 **0.2.4 /
Python 3.10.16**이며 초기 보고서의 0.2.5가 아니다. 기존 재현은 Docker 이미지
안에서 수행했다. 로컬 방식이라고 해서 사내 Python에 곧바로 설치 가능한 것은 아니다.
[최종 lock](../configs/bigcode_r2/bigcodebench_lock.json),
[공식 requirements](https://github.com/bigcode-project/bigcodebench/blob/main/Requirements/requirements-eval.txt).

DS-1000은 기존 정답 1,000/1,000 재현과 독립 채점 subprocess를 재사용할 여지가 있다.
다만 과학계산 패키지·부가 데이터 준비가 필요하고, 과거 Solar 실험에는 높은 기본
해결률로 개선 폭을 측정하기 어려웠던 기록이 있다. 이를 Astra·GLM의 점수로
간주하지 않는다. [기존 환경 감사](R3_DS1000_DEPENDENCY_AUDIT.md),
[기존 calibration 판단](R3_CALIBRATION_DECISION.md).

ClassEval 원본은 100개 클래스이며 코드 MIT와 별도로 **데이터 CC BY-NC 4.0**를
명시한다. ClassEval-Pro와 같은 이용 조건이라고 취급하지 않는다.
[원본 라이선스 설명](https://github.com/FudanSELab/ClassEval#license).

RepoExec은 기본 실행기가 Docker를 직접 호출해 별도 이식이 필요하다.
DevEval은 현재 공식 배포·예전 조사에서 남은 자료 이용 조건과 환경 재현 사항을
다시 확인해야 하므로 첫 실행 후보에서 제외했다. 이들은 별도 후보이며 이름이
비슷한 ExecRepoBench와 혼동하지 않는다.
[RepoExec](https://github.com/FSoft-AI4Code/RepoExec),
[DevEval](https://github.com/seketeam/DevEval), [기존 조사](R9_DEVEVAL_DEPENDENCY_AUDIT.md).

## 두 환경의 공통 실험

| 실행 장소·모델 | OFF | ON | 우선 비교 |
| --- | --- | --- | --- |
| 여기: Astra, 현재처럼 native 세션/CLI | 공통 L0, 장기 메모리 미주입 | 같은 L0 + 동결 L1/L2/L3 사용 | Astra 안에서 ON−OFF |
| 사내: GLM, 기존 vLLM HTTP | 공통 L0, 장기 메모리 미주입 | 같은 L0 + 동결 L1/L2/L3 사용 | GLM 안에서 ON−OFF |

문제 ID·데이터 버전·채점 테스트·코드 수정 규칙을 공통으로 정한다. 모델별로
OFF/ON의 예산과 실행 조건은 동일하게 고정한다. 출력·도구·컨텍스트 상한은
두 모델에서 실제 지원되는 값을 확인한 뒤 사전 선언하고, `high` 같은 모델별
설정을 같은 추론량으로 간주하지 않는다. 공유 GLM 서버 대기시간과 장치 차이도
기록하여 두 장소의 총 시간을 그대로 모델 속도 순위로 해석하지 않는다.

모델 연결부 외의 도구·기록·메모리·채점은 공통으로 만든다. native CLI와 HTTP
worker의 감싸는 실행 방식이 완전히 같지 않으면 그 차이도 명시하고, Astra와
GLM의 원시 점수를 빼서 메모리 효과라고 부르지 않는다.

source/dev/test는 문제 가족·중복·시간 정보를 고려해 모델 실행 전에 분리한다.
기본 설계는 같은 source 문제 집합에서 각 모델이 수집한 경험으로 별도 은행을
만들고 모델 내부 OFF/ON 효과를 측정하는 것이다. 같은 은행으로 reader 차이만
보려면 은행 내용을 고정한 별도 실험으로 둔다. Astra 은행을 GLM에 전달하는 경우
**Astra 경험→GLM 전이**로 표시하며 GLM 자체 경험 효과와 섞지 않는다.

평가 중 은행 갱신과 테스트 정답의 메모리 유입을 막는다. L3는 실제 승격 조건을
충족한 검증 절차만 포함한다. 알고리즘 문제에서 저장소 관계를 거의 조회하지
않았다면 L2 사용·효과가 검증됐다고 하지 않는다.

주지표는 같은 문제의 ON/OFF 해결 전환, 해결률 차이와 신뢰구간이다.
해결→실패도 함께 집계하고, 모델·인프라·채점 오류는 별도 수와 전체 분모를 보존한다.
시간·모델 요청·토큰·도구 사용·메모리 노출도 함께 기록한다.
같은 문제 재풀이 이득과 다른 문제 경험의 전이 이득은 구분한다.

다음 실행 단계는 LiveCodeBench의 **모델 없는 정답/오답 채점 점검 → 별도 dev의
20~30문제 작은 비교 → 동결된 본평가 확대**다. ClassEval-Pro도 같은 환경 재현
절차를 통과한 뒤 보완 평가로 확정한다. 작은 비교의 상승 여부만으로 본평가
문제나 벤치마크를 골라 바꾸지 않는다.
