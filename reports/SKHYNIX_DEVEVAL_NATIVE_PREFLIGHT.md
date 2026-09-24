# DevEval native 채점 사전검증

2026-09-24. **Docker 없이 참조 코드 10/10 통과, 의도적 실패 대조군 10/10 검출**을 확인했다. 모델 호출은 0회이며, 이는 환경 검증 결과이지 모델 정확도가 아니다.

## 고정한 공식 자료

- 대상은 [seketeam/DevEval](https://github.com/seketeam/DevEval/tree/c1653455e0a18480a29aa07ba51636070f113316)이다. OpenCompass의 동명 벤치마크가 아니다.
- GitHub commit: `c1653455e0a18480a29aa07ba51636070f113316`.
- [Hugging Face 데이터](https://huggingface.co/datasets/LJ0815/DevEval/tree/16ff740d87f5fa97567d6dffd4bcbf299231211c) commit: `16ff740d87f5fa97567d6dffd4bcbf299231211c`.
- 메타데이터: 1,825개 작업, 115개 저장소. `Source_Code.tar.gz`: 916,746,365 bytes, SHA-256 `c7e501a0a812197d227fee189740bc22a323011d2251e46d53e4bb854af4555f`.
- 708MB `Dependency_Data.tar.gz`는 이번 실행에 필요하지 않아 내려받지 않았다. 공식 dependency recall@k 분석은 아직 준비하지 않았다.
- 데이터 카드 라이선스는 CC-BY-4.0이다. GitHub 저장소의 license API 값은 `null`이며, 개별 원본 저장소의 라이선스는 별도 보존해야 한다. 선택한 5개 저장소의 라이선스 파일 해시를 증거에 기록했다.

## 선택과 결과

테스트 결과를 보기 전에 IMAPClient, Jinja2, Faker, mistune, PyJWT에서 각각 2개를 고정했다. 각 저장소는 외부 서비스 없이 설치 가능한 후보로 선정했고, 작업은 공식 메타데이터에 cross-file dependency와 테스트가 있는 항목을 seed/namespace SHA-256 순서로 골랐다. 이는 편의 환경 점검 표본이며 전체 DevEval의 대표 표본이 아니다. **향후 target 평가는 이 10개 작업과 5개 저장소 전체를 제외하는 정책**을 사용한다.

| 검증 | 결과 |
|---|---:|
| 원본 참조 코드 | 10/10 PASS |
| 본문을 고정 AssertionError로 교체한 대조군 | 10/10 검출 |
| JUnit 분류 | test failure 9, fixture assertion error 1 |
| 모델 / Docker / 권한상승 호출 | 0 / 0 / 0 |
| 20개 control 실행 합계 | 33.80초 |
| 보관 원본 및 작업용 소스·테스트 해시 | 변경 없음 |

공식 `pass_k.py`의 evaluator와 test selector를 그대로 사용했다. `PYTEST_ADDOPTS`로 JUnit 기록만 추가했다. 공식 `Error`만으로 실패 대조군을 인정하지 않고, 정확한 의도적 `AssertionError` 표식을 확인했다. 테스트 fixture에서 발생한 하나는 pytest가 `error`로 분류했지만 같은 의도적 예외이며, 무관한 수집·설치 오류와 구분했다.

첫 `controls-001`의 보수적인 진단은 이 fixture 분류와 생성 파일 변경 때문에 미완료로 남겨 두었다. 분류를 명확히 한 뒤 **동일한 10개 작업**을 새 `controls-002`에서 다시 실행했다. 이전 기록은 덮어쓰지 않았다. `.pytest_cache` 및 `*.egg-info` 파일 9개의 변경은 생성 메타데이터로 따로 기록했다. 원본 1,975개 파일은 모두 유지했고, 작업용 일반 소스·테스트 변경은 0개였다.

## 재사용 환경과 명령

새 WSL `TriMemRunner2404` 일반 사용자 환경에 CPython **3.9.18**, 공식 `requirement.txt`, pytest 7.4.0 / pytest-runner 6.0.0 / setuptools 68.0.0 등을 설치했다. 73개 설치 배포판의 버전을 저장했고 `pip check`가 통과했다. Python은 uv의 독립 배포본으로 설치했으므로 공식 Conda lock의 네이티브 라이브러리 빌드까지 동일하다고 주장하지 않는다.

- runtime: `/home/trimem-runner/skhynix-deveval-001/venv/bin/python`
- immutable source: `/home/trimem-runner/skhynix-deveval-001/pristine`
- opaque controls: `/home/trimem-runner/skhynix-deveval-001/controls-002`
- 원본 압축파일·작업 메타데이터: ignored `data/deveval_001/`
- 선택 저장소만 추출: 1,975 files, 17,504,591 bytes. 기존 LCB 환경·소스는 변경하지 않았다.

재현 시 새로운 `--preflight-run` 경로를 사용한다. 출력 경로 재사용이나 기존 영수증 덮어쓰기는 거부한다.

```bash
python3 scripts/deveval_prepare.py --root data/deveval_001 \
  --fetch-source --extract-to /path/to/fresh/pristine

/path/to/python3.9.18 scripts/deveval_prepare.py --root data/deveval_001 \
  --preflight-pristine /path/to/fresh/pristine \
  --preflight-run /path/to/fresh/controls
```

위 준비 명령은 네트워크 다운로드를 포함한다. 회사 서버 반입 시에는 고정 원본·라이선스·실행환경을 별도로 패키징해야 한다. [버전 목록](../artifacts/skhynix_v1/deveval_001/runtime-pip-freeze.txt)은 설치 버전 기록이며, wheel hash까지 잠근 offline bundle은 아직 아니다.

## 증거와 다음 단계 경계

- [사전검증 JSON](../artifacts/skhynix_v1/deveval_001/native-preflight-001.json): source/selection/runtime/cell 영수증 해시, 결과·시간·라이선스 참조.
- [고정 대조군 선택](../artifacts/skhynix_v1/deveval_001/control-selection-001.json): 메타데이터 ID와 dependency 개수만 포함.
- [준비 도구](../scripts/deveval_prepare.py), [안전성 테스트](../tests/unit/test_deveval_prepare.py): **13 PASS**. 경로 탈출, 원본 해시 불일치, 기존 영수증 덮어쓰기, 결과와 무관한 고정 선택, fixture 오류 구분을 검증했다.

모델에 제공할 repository context와 target body/test 차단, L2/L3 bank, train/verification/held-out 분리, GLM 연결은 이 사전검증에서 구현하거나 실행하지 않았다. cross-file 의존관계는 공식 정적 메타데이터의 선언이며 모델의 의존관계 활용을 입증한 것이 아니다. 공식 harness는 파일을 잠시 교체하므로 같은 저장소에서 동시 실행하지 않아야 한다. 일반 사용자 native 실행은 비신뢰 코드를 격리하는 보안 sandbox와 같지 않다.
