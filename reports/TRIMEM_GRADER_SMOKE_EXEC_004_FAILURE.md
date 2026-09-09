# TriMem-Coder V1 `_004` grader-smoke 실패 폐쇄 보고

이 문서는 P0.1.4의 한 번뿐인 승인 실행을 비공개 payload 없이 폐쇄한다. 이 실행은 실제 official grader를 일부 실행했지만, 12개 전체 campaign을 완성하지 못했고 aggregate/public result/attestation에도 도달하지 못했다. 따라서 benchmark 성능이나 official-grader viability의 PASS 근거가 아니다.

현재 판정은 다음과 같다.

```text
TRIMEM_SYSTEM_IMPLEMENTATION = CREDENTIAL_FREE_GREEN
OFFICIAL_GRADER_VIABILITY = NOT_YET_ESTABLISHED
PERFORMANCE = NOT_MEASURED
PAID_MODEL_CALLS = 0
DEV_APPROVAL_ALLOWED = NO
ENDPOINT = TRIMEM_GRADER_SMOKE_ADAPTER_CONTRACT_NOT_READY
```

## 실행·정규화·요구량의 구분

| 조건 | official execution 완료 | adapter-normalized result | campaign 요구량 |
|---|---:|---:|---:|
| GOLD | 3 | 3 | 6 |
| NOOP_BASELINE | 3 | 2 | 6 |
| 합계 | 6 | 5 | 12 |

여섯 번째 셀인 Vue NOOP_BASELINE은 container, patch stage, tests, per-instance report, final report까지 실행되었고 official final report에서 정확히 unresolved로 분류되었다. 그러나 local adapter가 그 결과를 잘못 거부하여 최종 normalized result 파일을 만들지 못했다. 따라서 아래의 `6 executed`, `5 normalized`, `12 required`는 서로 바꾸어 쓸 수 없다. 특히 실행된 6개 셀의 부분 결과를 12-cell smoke PASS로 승격하거나, 다섯 normalized row만으로 viability를 주장해서는 안 된다.

## 1. correction commits

P0.1.4 시작점은 `a0f8cf2bbc3e13690c583b86054aaae562dfe3fd`이다. 그 이후 correction, probe-evidence, reseal 및 sentinel chain은 다음 16개 commit 순서로 고정되었다.

- `955e1d46e5ea0f16cadee745e9a72f0d2c14189b` — Multi-SWE prebuilt entrypoint 고정
- `b870ea8660078b8b6c25d02fbcf40157734e5413` — grader execution evidence fail-closed 결속
- `fd7bb6fa912e7a896211194d6075155b98882ab8` — Multi-SWE contract 및 probe gate 동결
- `bb3ab5ed4c88d7b5098cb3a7ff8df36fcd84907b` — credential-free correction reseal
- `25a9a5875a4c196b6bb579799b20311c4698dc79` — pinned Multi-SWE parser argv 결속
- `ca1f7983b3d936a389a4ab349e010fa54c681c52` — 제품 workflow inventory 정합화; 연구 seal과 분리
- `b19d7c8bff240ea96b48537b951a956fe98dd333` — 일회성 image-probe gate/evidence 결속
- `c4608fcf485433b250210b9def267977a0d4ee35` — complete Multi-SWE test evidence 요구
- `faee0f5d8c0a10199503e1526abfcc5dc95eb26d` — prebuilt grader runtime evidence 강화
- `9966918a621a7a29a78ef1e5d2703556d44c148a` — pinned Multi-SWE contract lock 확장
- `fd06c5f9d6d4e19af428a658b099fb48614b8284` — corrected prebuilt contract reseal
- `2add387b7abb82508659758913ff6408f22658b8` — 일회성 Vue image-probe request
- `d42dd13bf1a0ff1587dce3dbc2bf4c414c5105b4` — probe evidence 보존
- `650d4da86d7b052425765776b0bbd66f87d829c7` — post-probe CI history 완결
- `b34ca1c712057edc85dd292c39216634c1b884a2` — post-probe correction reseal
- `0e9ed55196da922dcebf1fb33b73940873007180` — 일회성 authoritative grader-smoke trigger (`_004` sentinel-only)

마지막 commit은 앞선 15개 correction/probe/reseal commit과 역할이 분리된 실행 sentinel이며, `_004` 한 파일만 추가했다. 보고서와 실패 evidence를 폐쇄하는 후속 commit은 실행 당시 contract나 이 16개 commit의 순서를 소급 변경하지 않는다.

## 2. correction HEAD

`_004`가 source/correction HEAD로 결속한 값은 `b34ca1c712057edc85dd292c39216634c1b884a2`이다. 실제 grader execution HEAD는 sentinel-only child인 `0e9ed55196da922dcebf1fb33b73940873007180`이다. Probe 전 contract correction HEAD는 `fd06c5f9d6d4e19af428a658b099fb48614b8284`로 별도 기록되어 있다.

## 3. PR #18 state

폐쇄 시점의 PR #18은 `OPEN / DRAFT`, branch `codex/trimem-coder-v1`, head `0e9ed55196da922dcebf1fb33b73940873007180`이었다. Head check rollup은 success 25, failure 1, skipped 1, pending 0이다. Failure 하나는 이 보고서가 다루는 `frozen-gold-noop-smoke`이며, skipped 하나는 sentinel push가 새 probe marker-only push가 아니어서 probe job이 실행되지 않은 정상 gate 결과다.

## 4. historical failed run preservation

다음 실행과 sentinel은 현재 결과와 합치지 않고 immutable history로 보존한다.

- Original trigger run `33470431940`, original sentinel raw SHA-256 `03207843e241bef409d64d0181596f4cec4c83fe157dfc22670d429bc14f91f0`
- Run `33480195643` attempts 1/2, `_002` raw SHA-256 `258900694f1584fcb0f04cde485c33ad4f4d4691154f5dfe598883ecdb03f48c`
- P0.1.3 run `33594270929` attempt 1, `_003` raw SHA-256 `90bae24a2fba5e9ed88882fb06a47c8bb0113e1ffe6c2c121db990934bad0603`
- P0.1.3 inventory artifact `9833160240` 및 encrypted artifact `9833161906`

`main` `ce10ab49586db7a859fbe5cca93051b93f9f5b55`, tag `v0.3.0-rc1`, PR #17, R1–R23 연구 artifact도 변경하지 않았다. 과거 네 SWE-bench valid cell은 과거 diagnostic evidence이며 이번 12-cell 결과에 재사용하지 않는다.

## 5. exact adapter root cause

P0.1.3의 원인은 `force_build=false` 상태에서 이미 존재하는 image tag 때문에 pinned harness의 build path가 조기 반환한 뒤, `human_mode=false` evaluator가 host `prepare.sh`를 요구한 계약 불일치였다. P0.1.4는 이를 `MULTI_SWE_PREBUILT_EVALUATION` (`human_mode=true`, `force_build=false`, `need_clone=false`)로 교정했고, 이번 Vue 실행은 host prepare나 source build 없이 실제로 그 경로를 통과했다.

이번 `_004` 실패의 primary error는 그보다 뒤의 official-test evidence validator에 있다. `scripts/trimem_official_grader.py`와 aggregate 측 `scripts/trimem_benchmark_matrix.py`가 Multi-SWE per-instance `Report.valid`를 final `resolved`와 동일한 값으로 요구한다. 그러나 pinned upstream에서 `Report.valid`는 per-instance report 자체와 관측된 test transition의 유효성이다. `gen_report`가 frozen expected-test domain을 추가 대조해 report/invalid-report를 나눈 뒤 `FinalReport`가 최종 resolved/unresolved list를 만든다. 실제 Vue NOOP는 per-instance `valid=true`였지만 final report는 정확히 unresolved였다. Adapter가 이 합법적인 조합을 `Multi-SWE official per-instance status identity/result mismatch`로 거부했다.

그 다음 masking error도 별개로 존재한다. 실패 report는 `materialized_private_inputs`를 top level에 보존했으나 caller는 `_trimem.materialized_private_inputs`만 읽었다. 그 결과 workflow 표면에는 primary error 대신 `official grader private-input identity set differs`가 마지막 오류로 나타났다. Primary semantics bug와 secondary evidence-shape masking을 함께 수정하기 전에는 adapter contract가 ready가 아니다.

## 6. pinned upstream contract evidence

- Upstream: `https://github.com/multi-swe-bench/multi-swe-bench`
- Revision: `24f493f8a103e72312ded4f6b9c89f081d69cb09`
- Git tree: `741ce10a4ec220fec713112502850b381a6226b9`
- Locked regular Git blobs: 11
- Contract projection SHA-256: `429c9dc08b394e91f310cf4c31f1a911add0e3da5ae130b4c584e8fe239faf2b`
- Internal lock SHA-256: `f9cea651d404e85ef0c592c29fb9365a4e09df723d92deeededb994061ec6683`
- `multi_swe_evaluation_contract_lock.json` raw SHA-256: `63b79b81ceae9d4ede463bfeec2d617cd5fcffd44bafd5a4829c187da10e2574`
- Official adapter SHA-256: `84ed38f01ec2ef4dae63e3ed4ad6ac1880f61119afd7cf0c92ec8ea088a3f4ec`
- Prebuilt entrypoint SHA-256: `16c021ac3c0eb18bc78376164307b53cfb294ac0f206415d465a1b11f1ec63ac`

이 lock은 dependency 선언뿐 아니라 `run_evaluation`, argument parsing, image/session control, report/final-report semantics 및 선택된 target별 patch script 계약을 Git blob bytes로 고정한다.

## 7. old/new `human_mode`

P0.1.3의 old value는 `false`, P0.1.4의 new value는 `true`이다. New value는 prebuilt image 내부 checkout과 `/home/fix-run.sh`를 사용하는 exact evaluation mode를 선택한다.

## 8. `force_build`

`force_build=false`로 유지했다. 이 값은 `human_mode=true`, `need_clone=false`와 함께 사용되며, target source image build를 허용하지 않는다.

## 9. submitted-patch bind-mount proof

Multi-SWE adapter는 각 request의 exact patch bytes를 per-cell host `evaluation_instance_fix.patch`로 materialize하고 `/home/fix.patch`에 bind mount한다. 실행 직전 host bytes를 다시 SHA-256/byte-count로 확인하며, container status도 실행된 patch identity를 기록한다.

- Vue GOLD: 612 bytes, SHA-256 `3e2f441242f7ac30ce618e2c44bc780e84f54b641fd0f2424cdcaa04cc5c91e4`
- Vue NOOP_BASELINE: 165 bytes, SHA-256 `0f4fb705a73dd7e804773b35e2ab0e4e2f17248c571e69333e9b8de7c2025775`
- Container destination: `/home/fix.patch`
- Frozen command: `bash -e /home/fix-run.sh`

두 Vue cell 모두 request identity match, materialized-patch hash match, container-status patch hash match가 restricted evidence에 남았다.

## 10. image-baked patch non-use proof

실행은 image 안의 기존 `/home/fix.patch` 내용을 신뢰하지 않는다. Exact submitted patch bind가 같은 container path를 덮고, entrypoint는 bind source의 hash/bytes를 container 생성 직전 재검사하며, submitted identity와 다른 fallback patch를 허용하지 않는다. Vue GOLD와 NOOP의 서로 다른 request hash가 각각 materialized patch 및 container status에 그대로 나타난 것이 이 경계를 입증한다. 별도 Vue probe는 patch를 적용하거나 tests를 실행하지 않았다.

## 11. host `prepare.sh` access count

실행된 두 Multi-SWE Vue cell 모두 host `prepare.sh` access count는 `0`이다. P0.1.3의 missing host preparation-script 경로로 되돌아가지 않았다.

## 12. Vue image contract probe

Probe run `33626769644`, attempt 1, job `100237113081`, marker HEAD `2add387b7abb82508659758913ff6408f22658b8`, conclusion `success`이다. Exact image는 `mswebench/vuejs_m_core@sha256:2883a52a2eb4054e820dc3a88f9fb0b93fbef7ce10801a57e718f1c6d9f8e9c1`, tag는 `mswebench/vuejs_m_core:pr-8911`이며 observed digest가 expected digest와 일치했다. `/home/core` HEAD는 `3be4e3cbe34b394096210897c1be8deeb6d748d8`, `/home/fix-run.sh`와 `/home/test.patch`가 존재했고 probe 후 tag/digest reference 제거도 확인했다.

Probe artifact는 ID `9845231922`, archive digest `sha256:e11bfb00d9a37755d2a01f111b5bb509959eeeec13c92c60dac0a84c8c85ce08`, result raw SHA-256 `4e3aaebcc4a7a812d480145f252cbf0851ad478cc078a6ef7b4aa606d7dd1dba`이다. Probe accounting은 image pull 1, probe container 1이고 patch application, official tests, official grading, model/API call은 모두 0이다. 이는 image-contract probe이지 점수가 아니다.

## 13. old/new freeze hashes

- P0.1.3 old freeze raw SHA-256: `02324655201497c0593f98e70d62f2cbb49f820b05a4d70f5af924638cfdc099`
- P0.1.4 pre-probe freeze raw SHA-256: `609aba7e2acdbce07f411bcb30c8c45e6d130b5a12376525785db0709b988d4e`
- `_004`가 결속한 final new freeze raw SHA-256: `583b8cf815ef78a1c29eb1f4c6cf25c01b0014cb511bd440e131e982e341eca1`

Old freeze를 current로 재사용하지 않았고, probe evidence 및 post-probe CI provenance를 포함해 final freeze를 다시 계산했다.

## 14. target-set and NOOP preservation

- Grader-smoke manifest raw SHA-256: `cf9a841a5509133d501dc83e7b69ddbd85770c371ab3ed9cda008f598349d409`
- Preserved target-set SHA-256: `01f9e41f1ce3f285c651c3bc857a1f7422ed7e0f9ccfb451b42aedf9a4aef52e`
- NOOP_BASELINE patch SHA-256: `0f4fb705a73dd7e804773b35e2ab0e4e2f17248c571e69333e9b8de7c2025775`
- Grader image-lock raw SHA-256: `12a90bcc8e9bf46a9e65ed7e606aeee44b9c50b68c311a01180dc5080e41adeb`

여섯 instance의 identity/order, 12개 GOLD/NOOP row, GOLD patches, image digests, M0/M1/M2, DEV/HELDOUT manifests는 변경하지 않았다.

## 15. `_004` path/hash

- Path: `artifacts/trimem_v1/exec_requests/GRADER_SMOKE_EXEC_REQUEST_004.json`
- Request ID: `TRIMEM_V1_GRADER_SMOKE_EXEC_004`
- Raw file SHA-256: `1cd2d983f9f140392c6c989a9a395c48d5ddc2176cb009b30a98a167c95218ef`
- Embedded canonical request SHA-256: `916eaa53fd167da581a4be4020dcee6bb74af12e44ed41e2246926542e0b9804`
- Sentinel-only commit: `0e9ed55196da922dcebf1fb33b73940873007180`

Sentinel 자체는 execution authorization이 아니며 external run-bound approval과 함께 한 번만 유효했다. `_001`, `_002`, `_003`, `_004`를 재작성하지 않는다.

## 16. grader workflow run ID/attempt

- Workflow run: `33630256522`
- Attempt: `1`
- Event/head: push / `0e9ed55196da922dcebf1fb33b73940873007180`
- Preflight job: `100247658511`, success
- Protected grader job: `100247757174`, failure
- Protected environment: `trimem-grader-smoke-exec`, ID `20971935382`
- Deployment: `6222359678`, one approval by `Scuttie`
- Authorization phrase: `TRIMEM_GRADER_SMOKE_MULTI_SWE_CONTRACT_RECOVERY_EXEC_APPROVED_ONCE`

External approval JSON은 759 bytes, SHA-256 `26d65d462b09d2db6988bbe6842244278f49c58b559750a4b6455ceb1559c392`; strict Base64는 1012 ASCII bytes, SHA-256 `c47e86d5195cb78ed3fb314480d2ee7d7f5ddb9761d9e6ef8438d7643c9224e9`였다. Secret 값이나 approval payload는 이 문서, repository, public log 또는 public artifact에 포함하지 않는다.

## 17. six instance IDs

Frozen order는 다음과 같다.

1. `astropy__astropy-13579`
2. `pydata__xarray-6721`
3. `vuejs__core-8911`
4. `django__django-16493`
5. `expressjs__express-3870`
6. `jqlang__jq-2919`

앞의 세 instance만 GOLD/NOOP pair가 실행되었고, 뒤의 세 instance 여섯 row는 adapter failure 이후 시도되지 않았다.

## 18. GOLD result

실행된 GOLD는 3/3 resolved였다: 두 SWE-bench row와 Vue row가 모두 official evidence를 거쳐 normalized result가 되었다. 전체 frozen 요구량 기준으로는 `3/6 executed`, `3/6 resolved evidence available`이며 나머지 3개 GOLD는 unattempted다. 따라서 요구된 `6/6` GOLD endpoint는 충족되지 않았다.

## 19. NOOP_BASELINE result

실행된 NOOP는 official final-report 기준 3/3 unresolved였다. 두 SWE-bench NOOP는 normalized result가 되었고, Vue NOOP는 정확히 unresolved였으나 primary adapter semantics bug 때문에 normalized result가 되지 못했다. 즉 `3/6 executed`, `2/6 adapter-normalized`, `3/3 executed underlying outcome unresolved`, `3/6 unattempted`이다. 요구된 6/6 NOOP classification은 완결되지 않았다.

## 20. patch-applied count

Restricted execution evidence상 실행된 셀 6/6에서 non-empty requested patch stage가 수행되었다. 그러나 adapter-normalized row는 5/12뿐이고 campaign 요구량은 12/12이다. 여섯 번째 Vue NOOP의 exact patch materialization/mount와 fix-stage execution은 보존됐지만 normalization 실패로 final result row가 없다. 따라서 `patch applied = 12/12`라고 보고할 수 없다.

## 21. tests-executed count

실행된 셀 6/6에는 non-empty official test output/status와 final-report evidence가 있다. Adapter-normalized row는 5/12, 전체 요구량은 12/12이다. 여섯 번째 test execution은 primary validator에서 거부되었고, 나머지 6개 row는 실행되지 않았다.

## 22. digest-match count

실행된 셀 6/6에서 expected target digest와 observed digest가 일치했다. Multi-SWE support digest도 일치했다. Adapter-normalized row는 5/12이고 full campaign requirement는 12/12이므로 전체 digest-match endpoint는 미충족이다.

## 23. submitted-patch identity count

실행된 셀 6/6에 exact request patch materialization/mount identity evidence가 있다. Vue NOOP도 `request_identity_match=true`, 165 bytes, frozen NOOP hash 일치가 보존됐다. Adapter-normalized result는 5/12, full requirement는 12/12이므로 submitted identity 12/12 PASS를 주장하지 않는다.

## 24. source-build count

Source image build count는 `0`이다. Vue 두 실행 모두 `force_build=false`, `human_mode=true`, `need_clone=false`이고 structurally excluded build path를 사용했다.

## 25. infrastructure failures

Infrastructure/adapter failure는 `1`이다. 이는 image pull, target patch, official tests 또는 runner preemption 실패가 아니라 post-report adapter evidence-validation failure다. Target image pull 3, support image pull 1, exact removal 4였고 종료 시 resident target/support image는 0/0이었다. Always-run fallback cleanup은 14개 frozen reference가 모두 이미 absent임을 확인했다.

Primary error는 `Multi-SWE official per-instance status identity/result mismatch`, masking error는 `official grader private-input identity set differs`이다. 둘을 하나의 scientific NOOP failure로 해석하지 않는다.

## 26. evidence inventory/hashes

- Non-sensitive inventory artifact: ID `9847127657`, archive SHA-256 `0b9379644d3a1e6dc15156bbb6e2e8a54ea7ec9fa94128c01bb50949e128aa75`, 9,231 bytes, expiry `2026-10-02T12:47:19Z`
- Inventory raw SHA-256: `c61ffdff2ab8857e8ebd212df9d8190b9424ebafd0c3a092b91de3a311108004`
- Canonical inventory seal: `493bf56cd4919cb3924cc4e9e5ca21d7571818de0b36ec6682676df55be5dd76`
- Inventory: 234 files / 8,416,230 plaintext bytes
- Committed sanitized failure receipt: 10,213 bytes, raw SHA-256 `fe9f98a07be06d7c5ee56110b0bc2058e9271f26ef0086b2232332aa7da42978`
- Failure-receipt payload seal: `sha256:8e87fc1a06b702d6b2860772086c7518f95ec231ec9ae63d430197260279b847`
- Encrypted restricted-evidence artifact: ID `9847128643`, archive SHA-256 `c37878ac3076cb7abf2a5b746476e7f0664922e927a72f92b4ba30e72814219a`, 8,819,557 bytes, expiry `2026-09-16T12:47:19Z`
- Encrypted payload SHA-256: `6bcf9b094edb93246d915ac99a283474dc64e6e8288e4d2abaf5ab5d32ea501e`, 8,816,672 bytes

Restricted bundle audit에서 unsafe tar member는 0, embedded inventory와 uploaded inventory는 byte-identical, listed/actual path·size·SHA-256은 234/234 bidirectional match였다. Workflow의 image cleanup, inventory, encryption/upload, runner plaintext/approval cleanup은 성공했다. GitHub protected-environment secrets는 폐쇄 확인 시 0개였다. 외부 검증용 임시 passphrase, approval material, plaintext는 검증 후 삭제 대상이며 장기 evidence나 repository/public artifact로 보존해서는 안 된다. 이 문서는 그 값이나 private payload를 포함하지 않는다.

Aggregate, public result, attestation subject/bundle은 upstream failure로 생성·업로드되지 않았다. 이를 임의로 재구성하지 않는다.

## 27. model/API/token/USD counters

```text
task-arm runs       = 0
solve calls         = 0
decomposition calls = 0
extraction calls    = 0
model calls         = 0
model gateway calls = 0
paid model calls    = 0
API calls           = 0
input tokens        = 0
cached input tokens = 0
output tokens       = 0
reasoning tokens    = 0
total USD           = 0
```

Official grader/container executions은 6이며 model/task-arm accounting과 혼합하지 않는다. 별도 Vue probe의 image pull/container도 official grader count에 넣지 않는다.

## 28. exact endpoint

정확한 endpoint는 다음 하나다.

```text
TRIMEM_GRADER_SMOKE_ADAPTER_CONTRACT_NOT_READY
```

이는 `TRIMEM_V1_GRADER_SMOKE_PASS_READY_FOR_DEVELOPMENT_APPROVAL`, `TRIMEM_V1_GRADER_SMOKE_FAIL`, `TRIMEM_V1_GRADER_SMOKE_INCOMPLETE`, `TRIMEM_MULTI_SWE_PREBUILT_IMAGE_CONTRACT_FAIL`이 아니다. Prebuilt image execution contract는 Vue에서 동작했지만 post-report adapter contract가 완결되지 않았고 12-cell campaign도 끝나지 않았기 때문이다.

## 29. DEV approval allowed

`DEV_APPROVAL_ALLOWED = NO`이다. P0.1.4의 일회성 authorization은 run `33630256522` attempt 1에서 소비되었다. 같은 run의 rerun, attempt 2, `_005`, DEV, HELDOUT, ablation, target replacement, merge, tag, release는 승인되지 않았으며 수행해서는 안 된다. Adapter 수정 후 새로운 실행이 필요하면 기존 approval을 재사용하지 말고 별도의 명시적 승인을 받아야 한다.
