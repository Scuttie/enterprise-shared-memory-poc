# Astra 실행 증거 (동결, 참고용)

`gpt-6-astra`로 돌린 개발 OFF 평가와 240문제 경험 수집의 **원본 증거**다.
GLM 실험에 필요하지는 않지만, 저장소의 `interim-results-*.json`이 이 파일들을
sha256으로 참조하므로 여기 보존한다.

원래 위치는 WSL 배포판 `TriMemRunner2404` 안의
`/home/trimem-runner/skhynix-architecture-scale-001/` 였다. 그 배포판을 지우면
원본이 사라지기 때문에 옮겨 왔다.

## 들어 있는 것

`pipeline-v15/development/baseline/run/cells/EVALUATION/<문제>/BASELINE/`

| 파일 | 내용 |
| --- | --- |
| `broker/submission.diff` | 모델이 작성한 패치. **같은 문제에서 GLM과 비교하려면 이것뿐이다** |
| `broker/events.jsonl` | 모든 툴 호출 기록. 어떻게 풀었는지의 전체 궤적 |
| `broker/packets/*.json` | 세션 간 인계 패킷 |
| `execution-audit.json` | 정상 실행 감사 |
| `public-result.json`, `grader-private.json` | 공식 채점 결과 원본 |
| `cell.json`, `cell.sha256` | 봉인된 문제 정의 |

문제 17개분이다. 공식 채점 15건 + 채점 보류 1건 + 사용량 한도로 중단된 1건.
13/15 해결(86.7%)의 근거가 여기 있다. 그 15건은 고정 순서의 앞부분이고
무작위 표본이 아니므로 벤치마크 점수로 인용할 수 없다.

## 빠진 것

- `workspaces/` (218MB) — 저장소 체크아웃일 뿐이라 제외했다. 다시 받으면 된다.
- `learning-240/authority.sqlite3` — `../frozen-bank-240/pipeline-v15/learning-240/`
  에 있는 것과 바이트 동일해서 중복을 제거했다. 그쪽이 뱅크 검증기가 확인하는 정본이다.

## 이건 실행하지 않는다

읽기 전용 보존물이다. 여기서 무언가를 이어서 돌리지 마라.
Astra 평가는 개발 ON을 시작하기 전에 동결됐고, OFF/ON 비교쌍은 0개다.
즉 **메모리 효과는 이 데이터로 측정된 적이 없다.**
