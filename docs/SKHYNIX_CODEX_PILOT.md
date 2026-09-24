# Codex 에이전트로 실행하는 메모리 비교 파일럿

별도 모델 API 클라이언트 대신 새 문맥의 Codex 에이전트가 공개 저장소를 수정하고,
제출 패치를 기존 공식 grader가 채점한다. Codex 자체 사용량은 발생하며 이 실행기에서
정확한 Codex 토큰·비용을 관측하지 못하므로 그 값은 `null`로 기록한다.

첫 파일럿은 SymPy `sympy__sympy-23262` 하나를 메모리 없음, 기존 M2,
SK hynix 조회 세 조건에서 각각 한 번 실행한다. 에이전트 모델 요청은
`gpt-6-astra`, 대화 상속은 `fork_turns="none"`으로 고정했다. 내부 모델의
날짜별 snapshot을 별도로 증명한 실험은 아니다.

[실행 결과](../reports/SKHYNIX_CODEX_PILOT_EVALUATION.md): 세 조건 모두 공식
채점에서 해결했다. 기본 조건·기존 M2·PDF 조회의 요청 수는 각각 15·14·16회다.
M2의 실제 주입은 1개, PDF 조회의 실제 주입은 0개였으므로 메모리의 추가 이득은
확인하지 못했다.

## 사용자가 해야 할 일

새 창이나 세션을 수동으로 만들 필요는 없다. 이 대화를 실험 관리자로 사용하고,
비교할 대상과 조건, 허용할 실행 규모를 전달하면 된다. 문제풀이 에이전트는
관리자가 새로 만들며 사용자가 중간에 풀이 힌트를 주지 않는 편이 비교에 유리하다.

현재 CLI는 `--target-id`와 고정한 추가 문제 목록을 지원한다. 학습 기록을 고정해
여러 문제를 비교하는 방법은 [학습·평가 실행법](SKHYNIX_CODEX_LEARNING_EVALUATION.md)을
따른다. 실행 디렉터리 하나는 문제 하나와 세 조건을 담으며, 전체 비교 계획은
별도 batch CLI가 고정하고 집계한다. 같은 실행 디렉터리를 초기화해 재사용하지 않는다.

PDF의 학습 효과까지 확인하려면 다음 순서가 필요하다.

1. 메모리를 만들 학습 문제와 최종 평가 문제를 분리한다.
2. 학습 문제에서 실제 수정·공개 검증 증거를 모아 경험과 검증 스킬을 저장한다.
3. 메모리 bank를 동결하고, 동일 모델·도구·예산의 새 에이전트들로 평가한다.
4. 해결률과 함께 조회된 메모리, 도구 요청 수, 검증 결과를 비교한다.

이 파일럿의 bank는 기존 과거 PR 지식이다. L1 개인 경험과 L3 검증 스킬은 없고,
Gate A/B 누적 학습도 실행하지 않는다. 따라서 이 파일럿으로 대규모 스킬 학습의
효과를 주장하지 않는다.

## 구현과 실행 경계

- [관리자·공개 도구 중계기](../scripts/trimem_skhynix_codex.py): 새 작업공간 준비,
  요청 기록, 도구 실행, 1회 제출, 공식 채점 및 세 조건 집계.
- [메모리 연결](../scripts/trimem_skhynix_codex_memory.py): 실제 기존 M2와
  `SkillFirstMemoryController` 호출, 메모리 내용·개수·바이트 기록과 복구.
- [Windows 클라이언트](../scripts/trimem_skhynix_codex_client.py): JSON을 UTF-8
  base64로 전달해 PowerShell 문자열 손실을 피한다. WSL의 공개 도구 중계기만 호출한다.

각 에이전트는 별도 초기 Git checkout을 사용한다. 명령은 고정 이미지에서
비관리자·네트워크 차단 상태로 실행되며, checkout 외의 호스트 자료를 마운트하지
않는다. Git 이력도 문제의 기준 시점만 남긴다. 실제 에이전트는 호스트 도구를
상속하므로 **중계기 외 접근 금지는 실험 절차상의 제한**이다. 새 문맥이나 별도
worktree만으로 호스트 전체에 대한 강제 접근 차단을 보장하지 않는다.

현재 허용량은 조건마다 도구 요청 120회, 첫 요청부터 1,200초다. 검색·읽기·수정·
명령·메모리 조회·제출·오류가 각각 요청 수에 포함된다. 하위 작업별 제한은 없다.
명령 timeout은 남은 시간 이내로 줄이며, 컨테이너 준비 시간은 추가될 수 있다.
이는 모델 내부 추론 호출 수를 세는 예산이 아니다.

메모리 내용은 작업당 최대 3개·12,000 UTF-8 bytes다. 같은 하위 작업의 조회를
반복하면 기존 결과를 돌려주고 새로 주입한 것으로 세지 않는다. 같은 하위 작업
ID에 다른 검색 의미를 덮어쓰면 거부한다. 실제 Codex 대화 문맥을 기존
`SkhynixAgentRuntime` 방식으로 잘라내지는 않으므로 L0 문맥 압축 효과는 평가하지 않는다.

모델이 문제풀이 도중 실행하는 공개 테스트와 제출 후의 공식 채점은 분리한다.
이번 SymPy 환경의 공개 Python은 `/opt/miniconda3/envs/testbed/bin/python`이며,
다음 명령이 새 초기 코드에서 22개 테스트를 통과하는 것을 먼저 확인했다.

```text
/opt/miniconda3/envs/testbed/bin/python bin/test sympy/core/tests/test_basic.py --no-colors --no-subprocess
```

이 기본 검사는 환경 확인용이다. 각 에이전트는 문제와 관련된 공개 테스트를
직접 찾아 실행해야 한다. 공식 정답 패치와 grader 전용 테스트는 전달하지 않는다.

## 관리자용 실행 예시

기존 WSL 캐시가 준비된 Linux 실행 소스 디렉터리에서 실행한다. 모델 API 키는
사용하지 않는다. `prepare`는 새 출력·작업 디렉터리만 허용하며 실제 모델을 호출하지 않는다.

```bash
python scripts/trimem_skhynix_codex.py prepare \
  --run-root /home/trimem-runner/NEW_PILOT/execution \
  --workspace-root /home/trimem-runner/NEW_PILOT/workspaces \
  --dataset-cache-root /opt/trimem-rehearsals/e932-preflight/datasets \
  --harness-root /opt/trimem-rehearsals/e932-preflight/harnesses \
  --public-python /opt/miniconda3/envs/testbed/bin/python
```

관리자는 각 에이전트에 해당 cell의 클라이언트 호출법과 같은 공통 지침을 전달한다.
에이전트가 `submit`을 마친 뒤 관리자만 다음 명령을 실행한다.

```bash
python scripts/trimem_skhynix_codex.py grade --run-root /home/trimem-runner/NEW_PILOT/execution --cell A
python scripts/trimem_skhynix_codex.py grade --run-root /home/trimem-runner/NEW_PILOT/execution --cell B
python scripts/trimem_skhynix_codex.py grade --run-root /home/trimem-runner/NEW_PILOT/execution --cell C
python scripts/trimem_skhynix_codex.py report --run-root /home/trimem-runner/NEW_PILOT/execution
```

공식 채점 중 장애가 나면 자동으로 중복 채점하지 않는다. 실패 원인과 남은 증거를
관리자가 확인한다. 도구 한도에 도달한 미제출 실행은 `seal`로 당시 부분 패치를
고정할 수 있으며, 결과에 `agent_completed=false`를 남긴다. 미채점 조건이 하나라도
있으면 세 조건 해결률 비교는 생성하지 않는다.

구조 테스트 기록: [codex_validation.xml](../artifacts/skhynix_v1/codex_validation.xml).
