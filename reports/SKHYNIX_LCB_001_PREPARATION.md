# LiveCodeBench 실험 준비와 모델 선택

2026-09-23. 새 실험은 **gpt-6-astra / low**로 시작한다. 기존 SWE-bench
v20의 Astra/high 설정과 프로세스는 변경하지 않는다.

## 모델 선택

현재 Codex 모델 목록과 공식 문서를 확인했다. Astra의 최소 추론 설정은 `low`다.
이는 Astra 자체의 추론 노력을 낮추는 설정이며, 작은 별도 모델로 바꾸는 것은 아니다.
`gpt-5-luna`라는 정확한 ID는 현재 목록에서 확인되지 않는다. 확인한 Luna ID는
**`gpt-5.6-luna`**이며, 선택 가능한 추론 설정은 low/medium/high/xhigh/max다.
공식 API 문서와 Codex 클라이언트에 노출되는 설정은 다를 수 있으므로 실제 실행은
현재 클라이언트 목록과 실행 영수증으로 검증한다.

- [Astra 공식 모델 문서](https://developers.openai.com/api/docs/models/gpt-6-astra)
- [GPT-5.6 Luna 공식 모델 문서](https://developers.openai.com/api/docs/models/gpt-5.6-luna)
- [Codex 추론 설정](https://learn.chatgpt.com/docs/config-file/config-reference)

우선 Astra/low의 OFF 기준 성능·완주율·시간을 본다. 필요하면 같은 개발 문제에
Luna/medium을 추가한다. Luna가 약하므로 반드시 메모리가 더 잘 작동한다거나,
사내 GLM과 비슷한 능력을 갖는다고 가정하지 않는다. 작은 모델은 경험을 읽고
적용하는 능력도 낮을 수 있다. 메모리 ON 상승폭을 본 뒤 모델을 고르지 않는다.

기존 사용자 선호대로 여기서는 ChatGPT 로그인 기반 Codex native 세션을 사용한다.
별도 OpenAI API 키를 추가하지 않는다. 공개 API의 토큰 가격을 이 클라이언트의
실제 크레딧 사용량으로 환산하지 않는다. 사내에서는 이미 제공되는 GLM/vLLM
서비스에 연결하며 정확한 GLM ID·서빙 설정은 아직 확인 전이다.

## 준비 순서와 상태

실험 계획은 [lcb_001_plan.json](../configs/skhynix_v1/lcb_001_plan.json)에 기록했다.
이 파일은 **준비 명세**이며 아직 실행기를 제어하는 동결된 본평가 설정은 아니다.
GitHub 전달 구성과 사내 컨테이너 설치·검사 명령은
[LCB 컨테이너 전달 안내](../docs/port/LCB_CONTAINER_HANDOFF.md)에 정리한다.

1. 별도 Linux 가상환경에서 고정된 공식 채점기를 불러온다. Docker·GPU·모델 호출은 필요 없다.
2. 합성 문제의 정답/오답 구별, 이후 공식 문제의 참조 답안/오답 재현으로 채점 경로를 확인한다.
3. 데이터·문제 가족 중복을 확인하고 source/dev/main 분할을 모델 호출 전에 동결한다.
4. 별도 dev **24문제(easy/medium/hard 각 8개)**에서 Astra/low OFF 예비평가를 한다.
5. 실행 신뢰성·해결률의 상한/하한 문제·시간을 확인한 뒤 경험 수집 및 OFF/ON 실험의
   도구·시간·출력·컨텍스트 예산을 확정한다. dev 결과는 본평가 점수에서 제외한다.

모델을 너무 약하게 설정하거나 시간을 과도하게 줄이면 메모리보다 기본 문제 해결 능력이
실패 원인이 될 수 있다. 반대로 거의 전부 해결하면 개선 여지가 작다. 이 판단은 개발
문제의 OFF 결과로 하고, 결과를 본 뒤 본평가 문제를 유리하게 골라 바꾸지 않는다.

## 공통 비교 조건

데이터는 `livecodebench/code_generation_lite`, `release_v6`, revision
`0fe84c3912ea0c4d4a78037083943e8f0c4dd505`의 1,055문제를 준비 대상으로 삼는다.
공식 코드 commit은 `28fef95ea8c9f7a547c8329f2cd3d32b92c1fa24`다.
기존 R11의 “lite는 smoke만”이라는 주석은 새 실험으로 복사하지 않는다.

OFF/ON은 동일 모델·문제·공통 L0·도구·예산·채점 조건을 사용한다. ON만 다른 source
문제에서 수집한 동결 메모리를 읽는다. 각 모델의 자체 경험을 쓰는 비교가 기본이며,
Astra 경험을 GLM에 주는 실험은 별도의 전이 조건이다. 비공개 테스트·참조 답안은
모델 입력이나 메모리에 넣지 않는다. 평가 중 경험 은행을 갱신하지 않는다.

LiveCodeBench는 알고리즘 문제 사이의 교훈 전이에 적합하다. 실제 여러 파일로 구성된
저장소 관계를 활용하는 L2의 효과까지 검증하는 벤치마크로 간주하지 않는다.
공식 문제와 테스트를 사용하더라도 도구·수정 기회를 부여한 우리 실행 규칙의 점수는
기존 단발 생성 리더보드와 구분해서 보고한다.

## 실행 기록

아래에는 구현과 검증이 실제로 완료된 범위만 추가한다. 모델 목록 확인은 모델 실행
성공이나 해결률 평가 완료를 뜻하지 않는다.

### 2026-09-23 준비 실행

- 모델 카탈로그에서 Astra와 Luna의 정확한 ID·추론 설정을 기록했다.
  [카탈로그 확인](../artifacts/skhynix_v1/lcb_001/model-catalog-observation.json).
- Astra/low를 지정한 native 세션 1개에서 합성 연결 확인 응답을 받았다.
  ChatGPT 로그인 사용, 별도 API 키 없음, 도구 실행 없음, 10.409초.
  CLI가 `skip_host_skill_discovery` 기능 경고를 `error` 항목으로 내보내 처음 검사기는
  이를 실패로 분류했다. 실제 응답·turn 완료와 경고 내용을 확인해 별도 검토 기록을
  남겼고, 원본 기록은 그대로 보존했다. 서버가 반환한 모델 ID와 실제 추론 예산은
  이 JSONL에 노출되지 않아 요청 설정과 구분한다.
  [실행 검토](../artifacts/skhynix_v1/lcb_001/native-availability/review.json).
- 별도 Linux runtime `/home/trimem-runner/skhynix-lcb-001/venv`에 Python 3.10.21과
  채점용 패키지를 설치하고 공식 코드를 import했다. 기존 SWE-bench venv는 변경하지 않았다.
  [설치 영수증](../artifacts/skhynix_v1/lcb_001/runtime-install-receipt-001.json)과
  [패키지 해시 잠금](../artifacts/skhynix_v1/lcb_001/requirements.lock)을 보관했다.
- [독립 채점기](../scripts/trimem_lcb_grade.py)를 추가했다. 로컬 데이터 SHA256과
  공식 checkout commit을 검사하고 공식 추출기·채점기를 사용한다. 모델·Docker·데이터
  다운로드를 호출하지 않는다. 예정 문제 ID를 주면 누락 제출·인프라 오류를 보존하고
  완전한 결과가 없을 때 전체 해결률을 확정하지 않는다.
- **합성 문제 2개**(표준입출력 1개, 함수 호출 1개)로 실제 공식 채점기를 실행했다.
  정답 **2/2 통과**, 의도한 오답 **0/2 통과**, 인프라 오류 0건이다.
  [정답 검사](../artifacts/skhynix_v1/lcb_001/synthetic-smoke/correct-report.json),
  [오답 검사](../artifacts/skhynix_v1/lcb_001/synthetic-smoke/wrong-report.json).
  이 수치는 채점 연결 검증이며 **LiveCodeBench 해결률이 아니다**.
- 채점 어댑터의 합성 단위 테스트 **27개 통과**. 제출 누락·인프라 오류·잘못된
  공식 결과·빈 테스트 집합·데이터/코드 출처·숨은 내용 출력 억제를 확인했다.
  최종 어댑터는 전체 채점 시간과 공식 grader 호출 시간을 별도로 기록한다.
  앞선 합성 채점 영수증은 시간 필드 추가 전에 실행한 원본으로 그대로 유지했다.
- 서버 전달용 [이식 가능한 설치 검사](../scripts/trimem_lcb_smoke.py)와
  [개인 경로 없는 패키지 잠금](../configs/skhynix_v1/lcb_eval_py310.lock)을 추가했다.
  grader와 wrapper 단위 테스트 합계 **41개 통과**, 실제 Linux wrapper 실행에서도
  정답 2/2·오답 0/2를 확인했다.
  [최종 설치 검사](../artifacts/skhynix_v1/lcb_001/portable-smoke-002/smoke-report.json).
  첫 wrapper 검사는 합성 함수 입력의 마지막 빈 줄 때문에 정답 1개가 실패했다.
  입력 직렬화를 공식 call-based 규칙에 맞게 고치고 새 출력 경로에서 재검증했다.
  `portable-smoke-001`의 실패 원본은 보존했다. 공식 데이터나 채점 규칙은 변경하지 않았다.

공식 release_v6 원본은 고정 revision에서 JSONL 6개, 합계 약 **4.18 GiB**가 필요하다.
아직 실제 문제 데이터를 다운로드·분할하지 않았고, 공식 문제의 참조 답안 재현도
실행 전이다. 모델이 푼 LiveCodeBench 문제는 **0개**, 새 메모리 OFF/ON 결과도 없다.
다음 작업은 원본 반입·해시 검증·분할 및 24문제 개발 평가다. 사내 반입용 wheel 묶음과
공식 데이터의 오프라인 재현, GLM 연결 검증은 별도로 남아 있다.

### 로컬 채점 명령

Linux 환경에서 다음 형식으로 사용한다. `predictions.json`은
`{"schema":"trimem/lcb-predictions/1.0","expected_question_ids":["id"],"predictions":[{"question_id":"id","output":"원본 모델 출력"}]}`
형식이다. `expected_question_ids`를 빼면 제출되지 않은 문제는 탐지할 수 없다.
출력 파일은 기존 파일을 덮어쓰지 않는다.

```sh
python scripts/trimem_lcb_grade.py \
  --predictions predictions.json \
  --dataset-json local-official-rows.json \
  --dataset-sha256 DATASET_SHA256 \
  --official-repo /path/to/pinned/LiveCodeBench \
  --workers 1 --timeout 6 \
  --output new-grade-report.json
```

채점 보고서에는 코드·비공개 테스트·원시 grader 오류 문자열을 넣지 않는다.
공식 checkout은 commit과 작업 트리를 확인할 수 있는 Git 메타데이터를 함께 반입해야 한다.
가상환경은 코드 실행의 보안 경계를 대신하지 않으며, 모델이 제출할 코드의 작업 공간과
실행 권한 분리는 실제 풀이 실행기를 연결할 때 추가 검증한다.
