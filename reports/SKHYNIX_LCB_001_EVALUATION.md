# LiveCodeBench Astra 실험

**2026-09-24 pilot 완료: 메모리 OFF 24/24(100%), ON 24/24(100%), 해결률 차이 0%p.**
이번에는 baseline이 이미 모두 풀어 해결률 상승을 관측하지 못했다. 이는 valid 106개 중 사전에
고정한 24개의 결과이며, 최종 test 182개는 아직 실행하지 않았다.

| VALID 지표 | OFF | ON |
| --- | ---: | ---: |
| 공식 채점 통과 | 24/24 (100%) | 24/24 (100%) |
| 평균 풀이 시간 | 39.12초 | 36.90초 |
| 중앙값 풀이 시간 | 36.75초 | 30.51초 |
| 공개 테스트 호출 합계 | 25 | 25 |
| L1 경험이 실제 주입된 문제 | 0/24 | 5/24 |
| 미채점·보류·인프라 오류 | 0 | 0 |

실패→성공과 성공→실패는 모두 0개다. ON의 평균 시간이 2.22초 짧았지만 단일 실행이고
19개 문제에는 경험 주입도 없었으므로 이 차이를 메모리의 인과 효과로 해석하지 않는다.
짝지은 부트스트랩 구간 [0, 0]도 관측된 차이가 전부 0이라 생긴 값이며 모집단 효과가
정확히 0임을 보증하지 않는다. 해결률 차이에 대한 exact McNemar p는 1.0이다.

TRAIN 24/24도 공식 테스트를 통과했다. train 24개와 valid 24개 × 두 조건, 총 72개 풀이·채점을
**00:03:24–00:33:47 KST, 약 30분 23초**에 완료했다. 준비 시간은 제외한 실행기 경과 시간이다.
생성·경험 캡처·공개 테스트 인프라 오류는 모두 0건이다.
[최종 성적 JSON](../artifacts/skhynix_v1/lcb_001/pilot-results-001.json),
[동일 문제별 OFF/ON 결과 CSV](../artifacts/skhynix_v1/lcb_001/pilot-paired-results-001.csv),
[72개 실행 메타데이터](../artifacts/skhynix_v1/lcb_001/pilot-progress-001.json).

2026-09-23 준비, 2026-09-24 실행 완료. 기존 작업 저장소 `esm-r23-d115-writer`, 브랜치 `codex/trimem-coder-v1`에서 진행했다.
첫 준비 코드 커밋 `02768d8b8262de0737f8f6165b46d4285343d7a9`는 현재 추적 중인 비공개
GitHub 저장소 `Scuttie/skhynix-memory-experiment`에 push했다. 기존 SWE-bench v20 실행과는 별도다.

추가 실행 코드·문제 분할 커밋 **`3c6c0f4f808e3c7b086d20bd454b7ea6cd6c5555`**도 push했다.
**2026-09-24 00:03:24 KST**에 Astra pilot을 시작했다. 실행에 사용한 구현 47개 파일은 이 커밋과
바이트 단위로 일치한다. [실행 시작 영수증](../artifacts/skhynix_v1/lcb_001/execution-start-001.json).
관련 회귀 검사 156개 통과, POSIX 전용 1개는 Windows에서 건너뛰었다.

고정한 실행 순서는 train 수집 → 은행 동결 → valid OFF/ON 풀이 → 숨은 테스트 일괄 채점이었다.
모든 풀이와 경험 수집을 마친 뒤 비공개 채점을 시작했다. 후속 문제 선택이나 회고에 중간
숨은 테스트 성적을 사용하지 않았다.

## 고정한 문제와 실험 조건

데이터는 LiveCodeBench `code_generation_lite`, `release_v6`의 1,055개 문제다.
데이터 revision은 `0fe84c3912ea0c4d4a78037083943e8f0c4dd505`, 공식 채점 코드 commit은
`28fef95ea8c9f7a547c8329f2cd3d32b92c1fa24`다.

| 구분 | 전체 분할 | 이번 pilot에서 실행 | 용도 |
| --- | ---: | ---: | --- |
| train | 767 | 24 | 공개 예제 실행과 모델의 회고에서 경험 수집 |
| valid | 106 | 24 × OFF/ON | 같은 문제를 메모리 유무로 비교 |
| test | 182 | 0 | 최종 프로토콜을 정한 후 사용할 보류 집합 |

train은 2024-11-01 이전, valid는 2024년 11–12월, test는 2025년 1월 이후다.
동일 대회와 정규화된 문제·starter 중복을 가족으로 묶고 가족 전체를 같은 분할에 배정한다.
267개 가족, 분할 경계를 넘는 가족 없음. 두 pilot은 각각 easy/medium/hard 8개씩이며,
고정 seed와 문제 ID의 SHA256 순서로 선택했다. 정답률이나 ON 상승폭을 보고 문제를 고르지 않았다.
이 분할은 실험의 경험 수집과 평가를 분리한다. 기반 모델의 사전학습에 문제들이 노출됐는지를
검증했다는 뜻은 아니다.

[고정 분할](../configs/skhynix_v1/lcb_001_public_split.json)의 SHA256은
`a960fee4bd549dcec2bda5828b657b4b2cd6af76198485030c33a4a55e5a75c9`다.
각 ID, 가족, 분할, 공개 입력 해시와 원본 파일 해시를 저장했다. 숨은 테스트는 모델 입력과
분리된 파일에 있으며, 별도 채점 프로세스만 읽는다. 최종 비공개 채점 manifest는 전체 추출이
끝난 뒤 연결하고 동일한 ID·공개 입력·원본 해시인지 확인한다. 전체 추출과 모든 비공개 파일의
불투명 해시 검증도 완료했다. [최종 분할](../configs/skhynix_v1/lcb_001_split.json)과
[동일성 검증 영수증](../artifacts/skhynix_v1/lcb_001/dataset-final-validation-001.json)을 보존한다.
공개 입력은 변하지 않았으며 최종 채점 manifest SHA256은
`baaee09dc3f8bb92e6712b70a5fca75828d3e9968fdab2fd8550f1148cf4daae`다.

공식 채점 연결 검증에 사용한 두 train 문제와 같은 가족 9개는 경험 수집에서 제외한다.
이 9개는 이번 train pilot 24개와 겹치지 않는다. 전체 train으로 확장할 때도 같은 제외 목록을
적용하므로 수집 가능한 나머지 train은 758개다.

| 항목 | 고정값 |
| --- | --- |
| 모델 요청 | `gpt-6-astra`, reasoning `low` |
| 모델 연결 | ChatGPT 로그인 기반 Codex native; 별도 OpenAI API 키 없음 |
| 병렬 실행 | 문제 풀이 최대 2개 |
| 문제당 한도 | 600초, 도구 호출 24회, 공개 테스트 실행 4회 |
| 세션 | 문제당 최대 4개; 명시적 하위 작업 전환 때 새 세션 |
| 입력 제한 | prompt 196,608 bytes, L0 투영 문맥 48,000 bytes, 메모리 12,000 bytes |
| 답안 제한 | Python 코드 65,536 bytes |
| 공식 채점 | 문제별 한 후보, 테스트당 6초, 채점 worker 1개 |

위 bytes는 토큰 수와 다르다. native 경로에 별도 강제 출력 토큰 한도를 지정하지 않는다.
실제 노출되는 토큰 사용량은 실행 영수증에 보관한다. CLI에 요청한 모델/추론 설정과 서버가
독립적으로 확인해 준 모델 식별값은 구분하며, 후자가 없으면 확인됐다고 쓰지 않는다.

## 메모리 비교의 의미

두 조건은 같은 작업 그래프와 L0 문맥 투영을 쓴다. OFF에는 영속 메모리 은행이 없고,
ON에는 train 경험을 동결한 은행을 연결한다. 기존 controller의 **L3 → L2 → L1** 순서,
범위·관련성·승격 조건을 그대로 사용한다. 관련성이 부족하면 주입하지 않는다.

- L1: 실제 공개 도구 실행 기록을 인용한 회고. 공개 예제 통과를 숨은 테스트 통과로 표현하지 않는다.
- L2: 제출 코드의 실제 AST에서 파일·함수·클래스·import와 관계를 수집한다. 출처 revision을
  다른 문제의 revision으로 바꾸지 않으므로 독립 알고리즘 문제 사이의 L2 적용 범위는 좁다.
- L3: 실제 WRONG_ANSWER → 코드 변경 → 같은 공개 테스트 PASS의 절차 관측은 별도로 보존한다.
  이것만으로 L3 승격이 되지는 않는다. 기존 복수 사용자 검증 조건을 유지하므로 이번 단일
  실제 소유자 실행의 승격된 L3는 0개일 수 있다. 세션을 새 사용자로 꾸미지 않는다.

실제 동결 은행은 **L1 경험 24개, L2 노드 85개·관계 84개, L3 절차 0개**다.
검증 가능한 공개 실패→수정→통과 절차 관측도 0개였다. 은행 SHA256은
`dc4c843b17aa026762105bfa9ddbe61a5047d2dc9eac6805b1ea41cc43c3c257`다.
ON 24개 중 5개에 L1 경험이 한 건씩 주입됐고, 19개(79.2%)는 관련성 조건 때문에 주입을
보류했다. L2/L3 주입은 0건이며 72개 풀이 모두 한 세션에서 끝나 세션 전환은 없었다.

[최종 노출 감사](../artifacts/skhynix_v1/lcb_001/pilot-exposure-audit-001.json)에서 5건 모두
train 출처, 다른 문제·가족, 실제 저장된 경험과 주입 내용의 해시 일치, 동결 은행 불변을
확인했다. 이는 주입 경로의 검증이며 모델이 그 경험을 활용해 개선됐다는 증거는 아니다.
따라서 이 실험을 “네 계층이 모두 충분히 채워진 구조의 성능”으로 해석할 수 없다.
여기서 train은 모델 가중치 학습이 아니라 경험 수집이다. valid/test의 결과를 은행에 쓰지 않는다.

## 채점 및 보고

공식 문제와 공식 테스트를 사용하되 공개 테스트로 수정할 수 있는 자체 실행 프로토콜이다.
공개 리더보드의 단일 생성 점수와 동일하다고 간주하지 않는다. OFF/ON은 같은 ID로 짝지어
해결률, 실패→성공, 성공→실패, 시간, 토큰, 도구 사용량과 메모리 노출량을 비교한다.
인프라 오류·미제출·미채점은 별도로 남기고 원래 예정 분모에서 숨기지 않는다.
완료된 문제만의 중간 성적과 전체 집합의 최종 성적을 구분한다.

실행 전 확인한 사항:

- 모델 없는 합성 정답/오답 구분과 Astra 실제 합성 문제 제출·공개 채점 연결을 확인했다.
- 실제 공개 기록에서 L1/L2 저장, 은행 동결, ON 조회 경로를 연결했다. 합성 한 문제의 경험은
  실제 실험 은행에 넣지 않는다. 이 합성 조회는 관련성 필터가 주입을 보류했다.
- 별도 train 문제 두 개에서 보관 후보 2/2 통과, 문법 오류 후보 0/2 통과, 인프라 오류 0건을
  확인했다. 이것은 이번 Astra 성적에 합산하지 않는다.
  [공식 채점 검증 영수증](../artifacts/skhynix_v1/lcb_001/official-controls-001/control-receipt.json).

완료 후 추가 검증에서 VALID 24개는 공개 66개 + 비공개 933개 = 총 999개 테스트,
TRAIN 24개는 공개 63개 + 비공개 419개 = 총 482개 테스트임을 확인했다.
각 VALID 문제에 최소 31개, TRAIN 문제에 최소 11개의 비공개 테스트가 있다.
실제 채점 보고서 72개 모두 공개·비공개를 합한 전체 샘플 입력 해시와 공식 commit이 일치한다.
[테스트 수·채점 입력 감사](../artifacts/skhynix_v1/lcb_001/official-controls-002/pilot-test-count-audit-002.json).

또한 별도 통제 문제에 정상 실행되는 오답을 넣어 0/2 통과, 모두 공식 WRONG_ANSWER(-2),
인프라 오류 0건을 확인했다. 문법 오류만 판정하거나 공개 예제만 채점한 결과가 아니다.
[오답 통제 검증](../artifacts/skhynix_v1/lcb_001/official-controls-002/wrong-answer-control-002.json).
이 통제 실행들은 Astra pilot 성적에 합산하지 않는다.

최종 성적은 실행기 `summary.json` SHA256
`3c7818393b9fab33cb12f5ef07b1e718d69609ff349eaa5f822db7ce41b688a0`에서 산출했다.
문제·답안·비공개 테스트 원문은 로컬 실행 디렉터리에 보존하고 Git에는 성적과 검증 메타데이터를
올린다. 준비·합성 검증을 실제 LiveCodeBench 문제 해결률로 보고하지 않는다.

로컬 실행·재개 명령은 아래와 같다. 새 출력 디렉터리는 새 실험이고, 기존 출력 디렉터리는
입력·코드·증거 해시가 같을 때만 재개한다. 완료한 답안을 다시 생성하지 않으며, 중단된 모델
호출은 자동으로 재시도하지 않는다. 두 관리자가 같은 출력에 접근하면 잠금으로 거절한다.

```sh
python scripts/trimem_lcb_experiment.py run \
  --config configs/skhynix_v1/lcb_001_pilot.json \
  --runtime /path/to/runtime.local.json \
  --dataset-root /path/to/lcb-data \
  --output /path/to/pilot-output
python scripts/trimem_lcb_status.py --output /path/to/pilot-output
```

## GLM에서 재현

같은 Git commit, [pilot 설정](../configs/skhynix_v1/lcb_001_pilot.json), 분할 파일, 원본 revision과
공식 채점 버전을 가져간다. GLM도 **같은 train ID로 자기 경험을 수집**하고 같은 valid/test
ID에서 OFF/ON을 비교한다. Astra 은행을 GLM에 주는 것은 별도의 전이 실험이다.
같은 문제·도구·예산을 사용해도 Codex native와 GLM HTTP의 내부 시스템 문맥이나 토큰 계산이
동일하다는 뜻은 아니다. 우선 각 모델 안에서의 OFF/ON 차이를 비교하고, 모델 간 절대 점수는
전송 경로와 관측 가능한 사용량 차이도 함께 제시한다.

기존 Linux 컨테이너 안에서 Python과 SQLite를 사용한다. 추가 Docker·데몬·GPU·모델 서버 설치는
필요 없다. 코드·설정·분할·해시만 Git에 올리고 추출한 공개·채점 자료, wheelhouse, 공식 Git
bundle은 별도 반입 자료다. 검증한 반입 합계는 약 3.47 GB(3.24 GiB)이며 저장소와 Python은
별도다. 실행 시 약 4.18 GiB의 원본 JSONL은 필요 없다. 공개 입력은 모델에 제공하므로 내부
GLM에는 사내 vLLM endpoint를 연결해야 한다.
현재 native Astra 실행기와 공식 채점기는 연결했지만 **GLM HTTP 전송 어댑터와 사내 연결 검증은
별도 작업으로 남아 있다**. 정확한 모델 ID와 서버의 도구 호출·문맥 제한을 확인한 뒤 맞춘다.

[Linux 전달 안내](../docs/port/LCB_CONTAINER_HANDOFF.md),
[모델·채점 경로 설정 예시](../configs/skhynix_v1/lcb_runtime.example.json),
[메모리 포함 Python 3.10 의존성](../configs/skhynix_v1/lcb_runtime_py310.lock).

Linux x86_64 / Python 3.10용 wheel 43개(96,226,986 bytes)를 준비해 새 환경에
`--no-index --require-hashes`로 설치하고 의존성 검사·메모리/실행기 import·공식 합성 채점을
통과했다. 실행 중인 환경과 소스는 바꾸지 않았다.
[오프라인 설치 검증](../artifacts/skhynix_v1/lcb_001/offline-handoff-validation-001.json).
