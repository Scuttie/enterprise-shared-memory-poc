# L0–L3 구현과 실제 사용 근거 점검

2026-09-15 점검. PDF 원문 32·42–46쪽, 현재 실행의 동결 소스, 실제 공개 실행 기록, SQLite 저장소와 테스트 결과를 대조했다. PDF SHA-256은 `48cf59041ca5cedce430cc3237c418e03c2955948f1af0ed26002d8ab48f941d`다. 이 점검에서는 실행 중인 실험을 변경하거나 모델·공식 채점기를 추가 실행하지 않았다.

**L0–L3 핵심 경로의 로컬 실험용 구현은 있다. L0의 실제 문맥 전달과 L1·L2의 실제 저장도 확인했다. 그러나 PDF 전체 기능의 완성이나, 학습된 네 계층을 이용한 평가의 정상 작동·해결률 개선까지 확인한 상태는 아니다.** “구현 코드”, “사용할 데이터 준비”, “실제 평가에서 사용”, “성능 효과”를 구분해야 한다.

| 계층 | 코드에서 확인한 기능 | 현재 실험에서 확인한 근거 | 아직 주장할 수 없는 것 |
| --- | --- | --- | --- |
| L0 작업 문맥 | 현재 하위 목표의 상세 이력, 완료 목표의 근거 요약, 완료 원문 숨김과 명시적 복구, 새 세션으로 packet 전달 | 10:27 전후 점검에서 해시가 일치하는 packet 67개와 새 native 세션 입장 기록 67개, 완료 목표 요약이 들어간 packet 22개를 확인 | 모든 L0 기능의 실제 사용. 명시적 원문 복구 호출은 이 표본에서 0회이며, 토큰 절감 효과도 미측정 |
| L1 개인 경험 | 공개 실패·수정·검증 이력을 소유자별 episode로 저장하고 해당 소유자 범위에서 조회 | 10:27:39 KST 읽기 전용 SQLite 점검에서 **episode 107개**, 수집 완료 출처 **22문제** | 이 개인 기억을 실제 평가 문제에서 검색·주입하여 얻은 효과 |
| L2 저장소 지식 | 관측한 코드 조각 저장, 명시적 관계 생성·중복 방지, 범위·출처 검사, lexical seed와 PPR 검색 | 같은 시점에 **지식 기록 676개, 관계 625개**가 실제 DB에 존재 | 완성된 의미 관계 그래프, 자동 지식 통합·저장소 변경 추적, 실제 평가에서 유효한 조회·주입 |
| L3 검증 절차 | parameterised 절차 제안 검증, 서로 다른 출처·소유자 근거 검사, 승격·저장·동결·조회 | 구현과 구성요소 테스트는 확인. 현재 실험은 **reflection 0·승격 관측 0·스킬 0·준비된 bank 0** | 현재 실험에서 실제 스킬을 만들고 동결하여 평가에 사용했다는 주장 |

이 수치는 점검 시점의 관측이며 실행이 진행되면 바뀐다. [계층별 저장소·소스 점검 기록](../artifacts/skhynix_v1/architecture_scale_001/layer-implementation-audit-001.json)에는 별도 관측 시각과 재확인한 수치를 남긴다. 출처 문제 수, capture 수, episode 수와 skill 수는 서로 다른 집계다.

## 코드 근거와 구현의 범위

**L0는 단순히 세션을 바꾼 것보다 더 많은 기능이 연결되어 있다.** [문맥 조립](../src/enterprise_memory/trimem/native_architecture_context.py:268)에서 기준선의 일반 이력과 PDF 조건의 하위 목표별 이력을 분리하고, [문맥 투영](../src/enterprise_memory/trimem/subgoal_context.py:209)에서 활성 목표의 상세 이력과 완료 목표의 요약을 구성한다. [broker](../scripts/trimem_skhynix_architecture_broker.py:305)가 packet을 만들고, [실행기](../scripts/trimem_skhynix_architecture_run.py:430)가 이를 실제 native prompt와 새 세션에 전달한다. 원문 복구 코드가 있다는 사실과 현재 실험에서 복구 도구를 실제로 호출했다는 사실은 구분했다.

문맥 조립 모듈에는 `PACKET_ASSEMBLY_FOUNDATION_ONLY`, `runtime_wired:false`라는 고정 메타데이터가 남아 있다. 이는 해당 모듈 자체의 보증 범위를 나타내는 값이며 현재 실행 전체의 연결 상태를 조회한 결과가 아니다. 실제 연결 여부는 호출 경로와 별도 native 실행 영수증으로 확인했다. 이 상수만으로 실제 연결이 없다고 판단해서도 안 된다.

**L1과 L2는 reflection 전에 쓰인다.** [capture_training_trace](../scripts/trimem_skhynix_architecture_memory.py:259)는 실제 공개 실행의 검증 구간을 episode로 저장한다. 이어 [L2 생성 경로](../scripts/trimem_skhynix_architecture_memory.py:290)가 원래 코드에서 읽은 조각을 `put_repository_knowledge`로 저장하고 `link_repository_knowledge`로 관계를 연결한다. 따라서 L2 쓰기가 PDF 설명에만 존재한다고 말하는 것은 현재 코드와 실제 DB에 맞지 않는다. 저장된 공개 테스트 성공 라벨은 공식 SWE-bench 문제 해결 판정과 별개다.

다만 **현재 L2는 의미 지식 그래프의 제한적인 초기 구현**이다. 노드는 출처가 묶인 `read_file` 관측 조각이고, 간선은 주로 `CO_OBSERVED_IN_PUBLIC_SUBGOAL`이다. 이는 같은 하위 목표에서 함께 관측했다는 관계이지, 함수 호출·의존성·소유권을 분석했다는 뜻이 아니다. 반복 관측의 출처가 다르면 별도 기록이 생길 수 있으므로 676개를 676개의 독립적인 의미 지식으로 해석하지 않는다.

[저장소](../src/enterprise_memory/trimem/skill_memory.py:297)는 기존 식별자의 내용 덮어쓰기를 거부하며 동일 관계는 중복 삽입하지 않는다. 명시적 무효화 API와 [revision·원본 파일 해시의 적용성 검사](../scripts/trimem_skhynix_architecture_memory.py:619)는 있지만, Git/CI 변경 감지에 따른 자동 의미 병합·그래프 갱신 서비스가 연결된 상태는 아니다. [현재 검색](../src/enterprise_memory/trimem/skill_runtime.py:246)은 lexical seed와 PPR을 사용하며 embedding 가중치는 0이다.

**L3는 생성 조건이 코드로 집행된다.** [검증 경로](../scripts/trimem_skhynix_architecture_memory.py:371)는 보존된 공개 이력의 assertion RED → 구현 수정 → 동일 명령 GREEN을 검사하고, 테스트 수정·무효 수정·검증 후 변경 등을 거부한다. [승격·저장](../src/enterprise_memory/trimem/skill_memory.py:397)은 같은 절차를 뒷받침하는 서로 다른 문제·소유자 ID·검증 증거를 요구한다. 여기의 소유자는 합성 contributor ID이며 실제 여러 사람의 독립 실험이라는 뜻은 아니다. 이 검증은 공개 재현 절차의 근거이지 공식 정답 패치나 문제 해결을 보증하는 검증은 아니다.

[bank 동결](../scripts/trimem_skhynix_architecture_learning.py:695)은 등록된 실제 출처, reflection ingestion 및 유효한 L3를 요구하고, 확대 bank에서는 L1·L2 노드·간선도 요구한다. 현재 스킬 0개는 reflection 이전의 상태다. 아직 Gate B가 모든 후보를 거부했다거나 bank가 `NOT_READY`로 최종 판정됐다는 뜻은 아니다.

## 실제 사용과 테스트의 구분

[온라인 callback](../scripts/trimem_skhynix_architecture_memory.py:677)과 [조회 controller](../src/enterprise_memory/trimem/skill_runtime.py:170)는 **L3 Skill → L2 repository graph → L1 personal episode** 순으로 적격 결과를 찾아 문맥에 넣는다. 한 번의 조회에서 모든 계층을 무조건 주입하는 방식은 아니다. 조회기는 절차를 직접 실행하지 않고 모델에 검증된 절차 정보를 제공한다.

현재 단계는 빈 메모리에서 출처 경험을 모으는 단계다. [실행기](../scripts/trimem_skhynix_architecture_run.py:289)가 학습 풀이에는 `TRAINING_COLD_START`를 반환하고, 학습 bank를 이용한 callback은 평가의 `PDF_MEMORY` 조건에 연결한다. 점검한 실제 출처 실행에서 외부 메모리 주입은 0건이며, 현재 확대 실험의 평가 셀도 0개다. 따라서 `PDF_MEMORY`라는 학습 실행 라벨만으로 네 계층의 저장된 기억이 모두 사용됐다고 판단할 수 없다.

[implementation-validation-v2.json](../artifacts/skhynix_v1/architecture_scale_001/implementation-validation-v2.json)과 연결된 JUnit 원본을 확인했다. **622개는 19개 `tests.unit` 모듈의 검사**이며 실패·오류·skip은 0이다. 실제 저장·조회·승격 구현을 호출하는 구성요소 검사와 거부 경로 검사도 포함하지만, 모델 응답이나 RED/GREEN 출력은 fixture·mock인 경우가 있다. 검증 중 모델 호출과 공식 채점 호출은 모두 0이다. 따라서 622개 통과는 벤치마크 622문제 해결, 전체 코드 커버리지, 실제 end-to-end 평가 완료 중 어느 것도 뜻하지 않는다. 추가 controller 검사 16개는 이 수치와 겹친다.

예를 들어 [메모리 구성요소 검사](../tests/unit/test_trimem_skhynix_architecture_memory.py:104)는 실제 store·Gate B·동결·조회 경로를 검사하고, [L2 전달 검사](../tests/unit/test_trimem_skhynix_architecture_memory.py:128)는 검색 결과 전달을 확인한다. 이는 의미 있는 구현 근거이지만 실제 모델의 해결률 효과를 대신하지 않는다. 이번 점검에서는 테스트를 다시 실행하지 않았다.

PDF 전체와 동일한 배포 시스템이라고도 표현하지 않는다. 현재 범위는 로컬 SQLite, 고정 조회·승격 정책, 합성 소유자와 제한적인 저장소 관측 그래프를 사용하는 실험 구현이다. 학습된 메모리 정책, 실제 조직 인증·서비스 운영, 자동 CI 연동 갱신, 개인 shortcut·팀 playbook까지 포함한 PDF의 모든 범위가 완성됐다는 근거는 없다.

따라서 보고할 수 있는 표현은 **“L0–L3의 핵심 경로를 로컬 실험용으로 구현·테스트했고, 실제 L0 전달과 L1·L2 저장을 확인했다. L3 bank 준비, 평가 중 검색·주입, 해결률 효과 검증은 남아 있다.”**이다.
