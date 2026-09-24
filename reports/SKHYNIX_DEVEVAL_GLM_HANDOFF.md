# DevEval 사내 GLM 실행 인계

사내 GLM은 이 PC에서 호출하지 않았다. 사내의 기존 Linux 컨테이너에서 같은 문제 ID·분할·비교 조건으로 실행할 오프라인 패키지를 준비했다. GLM은 TRAIN 경험을 직접 새로 수집하며 Luna의 답안·경험 저장소를 가져가지 않는다.

## 전달할 자료

- 코드 원격: `https://github.com/Scuttie/skhynix-memory-experiment.git`, 브랜치 `codex/trimem-coder-v1`.
- 패키지 기준 커밋: `9d4cbf3daaf9a0dd1f9a0be9b0144d83d3bdab82`.
- 패키지 폴더: `data/deveval_002/handoff/final-9d4cbf3-001/` 전체.
- 크기: 1,248,933,433 bytes, 221 files. 큰 런타임·데이터 자산은 Git에 넣지 않았으므로 Git clone만으로 오프라인 실행 자료가 모두 옮겨지는 것은 아니다.
- `manifest.json` SHA-256: `87182fe38f66ff4e1ba36c73de4cdb5910beea01b298f93b649d9087e9dff311`.
- [실행 안내와 명령](../docs/SKHYNIX_DEVEVAL_GLM_REPRODUCTION.md), [vLLM 설정 예시](../configs/skhynix_v1/deveval_002_glm_runtime.example.json), [최종 검증 영수증](../artifacts/skhynix_v1/deveval_002/offline-final-handoff-001.json).

## 사내에서 할 일

1. 폴더 전체를 옮긴 뒤 위 manifest 해시와 패키지 내부 파일 해시를 확인한다.
2. 안내 문서의 `install-offline` 명령으로 새 경로에 Python과 의존성을 설치한다. Linux x86_64, glibc 2.28 이상, 쓰기 가능한 Linux 파일시스템이 필요하다. 설치 후에도 여유 공간 10GiB를 유지하도록 검사한다.
3. vLLM의 `/v1` 주소와 실제 served model ID를 별도 JSON에 입력한다. 인증이 있으면 지정한 환경 변수로 키를 제공하며, 없으면 `api_key_env`를 `null`로 설정한다.
4. `prepare-company`를 실행한다. 같은 30문제의 원래 구현 통과와 의도적 오답 실패를 검사하고 가려진 저장소 문맥을 만든다. 이 단계에서는 모델을 호출하지 않는다.
5. 준비 결과에 기록된 `run_command`를 실행한다. TRAIN 18회 경험 수집 후 VALID/TEST 12문제 × 5조건으로 총 78회 풀이를 진행한다. 마지막에 공식 채점 및 `deveval_repository_results.py publish`로 결과를 산출한다.

OFF는 L1~L3를 끈 조건이고 L0 작업 문맥과 도구는 모든 조건에 공통이다. 비교 조건은 OFF, L1_ONLY, NO_L2, NO_L3, FULL이다. 각 풀이의 한도는 600초·24동작·4세션·생성 테스트 4회이며 최대 2개 병렬이다. GLM의 모델 ID·출력 토큰 설정은 별도로 동결하므로 Luna의 `low`와 같은 수치적 추론 설정이라고 주장하지 않는다.

## 이 PC에서 확인한 범위

최초 이전 검증에서 오프라인 설치한 평가용 Python 3.9.18/79개 패키지와 관리자용 Python 3.10.21/43개 패키지의 import 및 `pip check`가 통과했다. 새 Linux 경로에서 고정 30문제의 원래 구현 30/30 통과와 의도적 오답 30/30 실패, 원본 복원, 78회 실행 준비까지 확인했고 모델 호출은 없었다.

최종 패키지는 그때 검증한 122개 wheel과 두 standalone Python의 내용이 동일하다. 최종 패키지의 관리자·결과 집계기 import와 수정된 생성 테스트 실행기의 합성 검사 3개도 통과했다. 이전 draft 환경 검증을 최종 패키지에서 다시 수행한 것처럼 표기하지 않는다. 실제 사내 서버 환경 검사와 GLM 성적은 아직 수행하지 않았다.

LCB004의 `NOT_READY`와 중단된 DevEval002 `run-001`은 기록으로 남겼다. 이 패키지는 import 경로를 수정한 `run-002`와 같은 실행 코드를 사용한다. 3개 저장소의 작은 실험이며 전체 DevEval 또는 처음 보는 저장소의 성능을 대표하지 않는다.
