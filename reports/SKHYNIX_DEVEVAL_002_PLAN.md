# DevEval 저장소 메모리 소규모 실험 계획

모델 결과를 보기 전에 **30개 작업과 78개 세션**을 고정했다. 아직 모델은 호출하지 않았다. 목표는 동일한 저장소 문맥에서 L2 관계 정보와 개인 L3 작업 절차가 실제로 사용되는지, 그리고 OFF 대비 제출·정확도에 차이가 있는지 점검하는 것이다. 3개 저장소의 작은 pilot이며, 새 저장소에 대한 일반화나 전체 DevEval 성능을 주장하지 않는다.

## 고정 표본

[계획 JSON](../configs/skhynix_v1/deveval_002_plan.json)의 최종 SHA-256은 `909aa8369fbec37a217bbbff2f7c29dafd4a627dd6be34596b25266e2794ed26`이다. 원본은 사전검증과 동일한 공식 DevEval GitHub/Hugging Face commit에 고정했다. 사전검증 001의 IMAPClient/Jinja2/Faker/mistune/PyJWT는 저장소 전체를 제외했다.

| 저장소 | DISCOVERY | VERIFICATION | VALID | TEST | 제거할 모든 benchmark 본문 |
|---|---:|---:|---:|---:|---:|
| Internet/pyramid | 4 | 2 | 2 | 2 | 100 |
| Multimedia/mingus | 4 | 2 | 2 | 2 | 52 |
| System/mrjob | 4 | 2 | 2 | 2 | 105 |
| 합계 | 12 | 6 | 6 | 6 | 257 |

선정 기준은 공식 메타데이터의 cross-file dependency 선언과 테스트 존재 여부다. 고정 seed로 파일 그룹과 작업 ID를 정렬하고, 저장소별 정확한 수를 채우는 첫 가능한 분할을 선택했다. 같은 source 파일 및 정확히 같은 공개 requirement는 phase를 넘지 않는다. 다른 저장소의 동일 requirement가 연결한 파일 그룹은 후보에서 제외한다. 실제 데이터에서는 이 중복 제외가 0개였다. 준비 환경이 실패해도 작업이나 저장소를 다른 것으로 바꾸지 않는다.

학습은 DISCOVERY와 VERIFICATION에 한정한다. VALID와 TEST는 각각 6개이며 두 집계는 분리한다. VALID 결과로 bank, 정책, 예산, TEST 구성을 바꾸지 않는다. 저장소 정체성은 L2 평가를 위해 phase 사이에서 의도적으로 공유하지만 target 파일은 분리한다.

## 비교 조건과 실행량

| arm | 활성 메모리 |
|---|---|
| OFF | 없음 |
| L1_ONLY | L1 |
| NO_L2 | L1 + L3 |
| NO_L3 | L1 + L2 |
| FULL | L1 + L2 + L3 |

18개 source 세션과 동일한 12개 VALID/TEST 작업 × 5개 arm = **78개 세션**, 반복은 1회로 사전 고정한다. 모델은 Luna/low, 작업당 600초·24개 도구 동작·생성 테스트 실행 4회·native 세션 4회다. worker는 최대 2개이며 같은 작업이나 같은 쓰기용 저장소 복사본의 동시 실행을 금지한다. arm 순서는 작업별 순환 배치로 고정하고 각 target은 모든 arm에서 정확히 한 번 실행한다. 실제 성능이나 승패를 보고 반복 수를 늘리지 않는다. GLM은 현재 호출하지 않고 추후 회사 서버 패키징 대상으로 남긴다.

L0는 기존 `ShortTermWorkingGraph`, 최대 3개 subtask를 사용한다. 조회 우선순위는 **L3 → L2 → L1**, active node당 최대 1개 메모리 단위, 누적 12KB다. 비활성 layer는 건너뛴다. arm 이름만으로 해당 메모리가 제공됐다고 간주하지 않고 실제 종류·출처·해시·시점·바이트를 집계한다.

## 정답과 테스트가 모델에게 넘어가지 않는 경계

선택한 30개만 가리지 않고, 세 저장소에 속한 **257개 benchmark target 본문 모두**를 제거한 뒤 AST/L2를 만든다. 공식 위치 정보가 본문 앞 docstring을 제외하는 경우도 있으므로 signature 이후 전체 suite를 가린다. 실제 test/fixture/공식 test-selector 파일, VCS/cache와 비 Python 자료는 solver snapshot에서 제외한다. examples/docs/setup은 기본적으로 제외하되 **공식 메타데이터가 benchmark target source module로 지정한 파일**만 본문과 docstring을 모두 가린 후 유지한다. 이 예외는 실제 private test/fixture/selector 파일에는 적용하지 않는다. 모델에게 주는 과제는 공식 `Functionality`/`Arguments`, 가려진 파일의 signature, snapshot ID뿐이다.

이 문맥 정책은 모델 호출 전에 명확히 했다. 초기 계획은 example source도 일괄 제외한다고 적었으나, 실제 DevEval에 `mrjob/examples/mr_text_classifier.py`와 `mrjob/setup.py`의 benchmark target이 있음을 확인했다. [변경 증거](../artifacts/skhynix_v1/deveval_002/eligibility-plan-amendment-001.json)는 이전 plan/planner 바이트를 보관하고 **visibility와 planner reference 외 모든 필드가 동일**함을 확인한다. 작업 ID, phase, 실행 순서, 예산, 모델, 메모리 gate는 바꾸지 않았다.

모든 arm은 같은 가려진 저장소와 같은 읽기 API를 받는다. L2는 이 바이트들에서 추출한 import/call/ownership 관계만 사용한다. 공식 dependency 주석은 gold body에서 유도된 선정 메타데이터이므로 모델에게 제공하거나 L2 edge로 복사하지 않는다. snapshot/file/evidence 해시가 조회와 일치해야 하며, 다른 revision을 현재 저장소로 다시 표기하지 않는다.

선택한 작업들의 cross-file 선언 중 다른 benchmark target을 가리키는 항목은 pyramid 4개, mingus 5개, mrjob 4개다. 따라서 모든 본문을 가린 뒤 공개 실행 가능성과 관계 coverage가 줄어들 수 있다. 이는 실제 sanitized AST audit으로 따로 측정하며, 선언 개수를 실사용 가능한 L2 관계 개수로 보고하지 않는다. 가린 helper 때문에 생성 테스트가 실행되지 않더라도 gold body를 복원해 공개 실행을 통과시키지 않는다.

[최종 masking/L2 감사](../artifacts/skhynix_v1/deveval_002/context-audit-002.json)는 수정된 계획에 고정된 snapshot에서 다음 수치를 확인했다. 257개 target 본문을 가린 뒤에도 선택한 **30개 모두** callable node와 11KB 미만의 L2 조회 packet을 가진다. 이는 조회 가능성 증거이며 모델에게 실제 제공됐거나 도움이 됐다는 결과는 아니다.

| 저장소 | 공개 Python 파일 | L2 nodes | L2 edges | 해석된 cross-file CALLS | IMPORTS |
|---|---:|---:|---:|---:|---:|
| pyramid | 61 | 1,393 | 4,832 | 293 | 408 |
| mingus | 42 | 721 | 3,086 | 302 | 104 |
| mrjob | 62 | 1,275 | 6,928 | 411 | 367 |
| 합계 | 165 | 3,389 | 14,846 | 1,006 | 879 |

이 관계는 공개 구문의 정적 분석이며 동적 호출 정확성을 인증하는 runtime callgraph가 아니다.

생성 테스트는 sanitized repository에서만 실행한다. 공식 정답이 보관된 원본과 private tests는 별도 evaluator에만 있다. 공식 private 채점은 모든 target solve가 봉인된 다음 수행하고, 그 결과를 bank나 모델 문맥으로 돌려보내지 않는다. native 실행만으로 보안 sandbox가 완성되는 것은 아니므로 실제 실행기의 파일/도구 격리 검증도 모델 호출 전 필요하다.

## 개인 L3의 검증 범위

DevEval에는 LCB와 같은 별도 공개 예제 oracle이 없다. 이를 만들거나 private tests를 공개하지 않는다.

- DISCOVERY: 모델이 실제 작성한 generated test에서 AssertionError RED → 다른 candidate로 **동일 test script** GREEN, 최종 candidate 해시가 GREEN과 같고 lesson이 두 실제 단계에 연결돼야 한다. 승격을 만들기 위한 고의적 실패 stub은 금지한다.
- VERIFICATION: 파일이 겹치지 않는 별도 TRAIN 작업에 procedure ID를 미리 배정하고, 동일한 선언 method/ID를 실제 호출해 그 작업의 최종 candidate에서 generated test GREEN을 확인한다.
- oracle은 `MODEL_GENERATED_EXPECTATIONS`다. 관측한 테스트 절차의 재사용을 확인하며, 모델이 쓴 설명·기대 정답·알고리즘의 의미적 정당성이나 공식 public PASS를 인증하지 않는다. 같은 개인 소유이며 조직 Gate B는 변경하지 않는다.

L3가 0개여도 L2 평가를 중단하지 않는다. 이 경우 개인 L3는 NOT_READY로 표시하고 FULL과 NO_L3의 사용 가능한 메모리 계층이 같다는 점을 공개한다. 실제 L3 노출이 없으면 L3 효과 비교를 주장하지 않는다. 기존 LCB bank나 target 이력을 DevEval 저장소 revision으로 바꾸어 가져오지 않는다.

## 분석과 사전 입장 조건

주 지표는 **정상 제출 AND 공식 private PASS**다. 제출률, 실제 layer 노출, 모든 시도의 시간·token·도구 사용을 보조 지표로 보고한다. 모델/형식/예산 실패는 false, 판정 불가능한 인프라 실패는 null로 구분하고 전체 시도 수와 누락 수를 유지한다. 동일 target의 paired 비교와 저장소별 수치를 함께 제시하되 표본이 매우 작다는 한계를 유지한다.

모델 호출 전에는 고정 30개 작업의 native reference/negative controls, 257개 target masking, 잔존 L2 관계 coverage, 동일 공개 문맥과 실행 격리 검증이 모두 필요하다. 계획의 상태 이름은 `TASKS_FROZEN_RUNTIME_AND_CONTEXT_AUDIT_PENDING`이며 자체로 실행 승인 영수증이 아니다. 결과를 보고 ID를 교체하는 fallback은 없다.

native eligibility는 **참조 30/30 PASS, 의도적 실패 30/30 검출**을 완료했다. 60개 control의 시간 합계는 95.37초이며 원본 보관본 및 일반 작업 소스·테스트의 해시는 유지됐다. [최종 native 영수증](../artifacts/skhynix_v1/deveval_002/native-eligibility-002.json)에 개별 task/arm과 근거 해시가 있다. 최초 실행은 pyramid의 기존 setuptools와 최신 zope 배포판 이름 정규화 충돌로 20/30만 통과했고, [해당 실패 기록](../artifacts/skhynix_v1/deveval_002/native-eligibility-001.json)을 보존했다. 전용 002 환경의 zope 호환 버전만 고정한 후 **같은 30개 전체**를 새 디렉터리에서 재검증했다. 기존 001 환경이나 모델 코드는 바꾸지 않았다.

공식 archive에 있던 `mrjob/file:/tmp/...`의 오래된 파일시스템 테스트 잔재는 별도 기록하고 추출하지 않았다. 외부 절대 경로를 가리키는 symlink는 따라가거나 재생성하지 않았다. 나머지 2,129개 파일(18,163,594 bytes)의 원본 해시를 보관한다. 모든 원본 archive bytes는 그대로 유지한다.

재현 가능한 계획 생성:

```bash
python scripts/deveval_repository_plan.py
```

[planner](../scripts/deveval_repository_plan.py)의 합성 테스트 **11개 PASS**는 순서/결과와 무관한 선정, 파일·requirement 분리, 5-arm 분모, private 내용 미출력, control repo 제외, L3=0 정책을 확인한다. [native eligibility helper](../artifacts/skhynix_v1/deveval_002/prepare-native-eligibility-source.py)는 별도 Python 3.9.18 환경과 매번 새로운 private root를 사용하며 모델을 호출하지 않는다. [79개 패키지 버전 기록](../artifacts/skhynix_v1/deveval_002/runtime-pip-freeze-002.txt)과 `data/deveval_002/native-runtime-manifest.local.json`에 실제 환경을 기록했고 `pip check`가 통과했다. 실행용 config를 발행하기 전 해당 영수증들과 최종 snapshot 참조를 추가로 고정해야 한다.

```bash
/home/trimem-runner/skhynix-deveval-002/venv/bin/python \
  artifacts/skhynix_v1/deveval_002/prepare-native-eligibility-source.py \
  --plan configs/skhynix_v1/deveval_002_plan.json \
  --private-root /path/to/new/private-eligibility-root \
  --report /path/to/new/metadata-only-receipt.json
```

## 모델 실행 직전 검증

실행기·모델 게이트웨이·문맥·메모리·승격·채점·관리자의 합성 통합 테스트 **140개가 통과**했다. 실제 002 Linux 환경의 합성 문제에서도 대상 함수 실행을 확인한 assertion RED → 코드 수정 → 같은 생성 테스트 GREEN → 최종 제출을 확인했다. 이 검증에는 모델 호출이나 공식 문제 채점이 없다. [합성 실행 영수증](../artifacts/skhynix_v1/deveval_002/synthetic-broker-runtime-001.json).

생성 테스트 PASS는 서로 다른 assertion 줄 2개 이상과 실제 대상 함수 본문의 실행, 실행 전후 대상 파일 해시 유지를 요구한다. L3의 RED도 대상 함수 실행 후 나온 실제 AssertionError여야 한다. 임의의 `assert True`만 통과시킨 기록은 승격 근거가 되지 않는다.

실행 설정은 `data/deveval_002/runtime.local.json`, 정답을 가린 문맥은 `data/deveval_002/snapshots-002.local.json`, 원본 실행 기록은 `data/deveval_002/run-001/`이다. 각 비교 조건의 도구·제한·제출 안내는 동일하다. 경험과 절차는 TRAIN 18문제에서만 수집하고, VALID 6문제 및 TEST 6문제 각각에 OFF / L1_ONLY / NO_L2 / NO_L3 / FULL을 적용한다. 최대 78회 대화이며 같은 문제의 비교 조건은 동시에 실행하지 않는다.

모든 78개 풀이가 봉인된 뒤 공식 채점을 시작한다. 최종 성적과 실제 L1/L2/L3 노출은 별도 실행 결과로 기록하며, 이 계획 문서의 구현·환경 검증 수치를 모델 해결률로 해석하지 않는다. 한 풀이는 최대 4개의 새 세션을 사용할 수 있으므로 풀이 수와 실제 세션 수는 다르다.

## 생성 테스트 import 수정 및 새 실행

첫 실행 `run-001`은 30개 풀이 완료 후 명시적으로 중단했다. 생성 테스트 실행기가 저장소 루트만 Python 경로에 추가해 `src/` 배치에서는 설치된 패키지가 선택될 수 있었다. 실제 후보 실행 검사는 대상이 실행되지 않은 테스트를 PASS로 인정하지 않았지만, 수정 코드에 대한 테스트를 방해하는 환경 결함이었다. 모델이 작성한 테스트의 누락 import 등과는 구분한다. [진단 및 합성 재현 근거](../artifacts/skhynix_v1/deveval_002/generated-import-diagnostic-001.json).

수정본은 저장소의 `src/`와 루트를 우선하며, 해당 저장소의 모듈이 외부에서 로드되면 실패 처리한다. 기존 후보 실행·파일 해시 검사를 유지한다. 합성 실행기·브로커 테스트 21개와 실제 Python 3.9.18에서 세 저장소의 가려진 패키지 import 3/3이 통과했다. 이는 모델 정답률이나 L3 준비도 검증은 아니다.

첫 실행의 공식 채점은 0회다. 기존 30개 풀이·TRAIN 은행을 새 성적에 섞거나 재사용하지 않는다. 문제 ID, 분할, 5개 비교 조건, 모델·예산·기억 승격 규칙은 그대로 유지하고 `data/deveval_002/run-002/`에서 모든 78개 풀이를 새로 수집한다. 설정은 `data/deveval_002/runtime-run-002.local.json`이다. [중단 기록](../artifacts/skhynix_v1/deveval_002/interruption-001.json), [새 모델 호출 전 수정 등록](../artifacts/skhynix_v1/deveval_002/import-protocol-amendment-001.json).
