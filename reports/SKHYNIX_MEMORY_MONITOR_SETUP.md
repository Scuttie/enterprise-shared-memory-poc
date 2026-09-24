# SK hynix 실험 자동 점검

2026-09-15 12:25 KST, 현재 Windows 사용자에게 작업 `SkhynixMemoryScaleMonitor-ESM`을 등록했다. [최신 점검 보고서](SKHYNIX_MEMORY_MONITOR.md)는 **5분마다** 갱신된다. 최초 등록 시 바로 한 번 실행하며, 첫 시간 트리거는 등록 1분 후이고 이후 5분 간격이다. 로그인 시에도 실행한다.

점검은 Windows가 깨어 있고 사용자가 로그인한 동안 실행된다. 절전 중에는 확인할 수 없다. 점검기가 실험을 자동 재시작하거나 풀이·채점을 재시도하지는 않는다. 상태 변화가 경고·오류일 때 Windows 바탕화면 알림을 시도하며, 알림 표시 성공을 보증하거나 이 대화에 메시지를 보내는 기능은 없다.

| 점검 | 판정 근거 |
| --- | --- |
| 컨트롤러 생존 | 현재 설정의 실행 기록과 PID·시작 시각을 함께 대조 |
| 실제 진행 | 최근 실행 이벤트·현재 broker 요청/worker 상태·경험 저장 시각 |
| 정체 | 마지막 활동 후 60분 경과 시 경고; 세션 교체·다음 문제 준비는 별도 상태로 처리 |
| 중단·채점 오류 | 공개 메타데이터의 명시적 BLOCKED/INFRA_ERROR/DISK_BLOCK 상태 |
| 메모리 준비 | 각 수집 단계의 경험·L2 노드/관계·L3 검증 스킬 수; 24개 bank의 NOT_READY는 전체 중단으로 처리하지 않음 |
| 저장 공간 | 실제 C 드라이브 25 GiB 미만 경고, 10 GiB 미만 심각; WSL 가상 여유 공간과 구분 |
| 점검 실패 | 읽기·프로세스 조회 실패는 정상 판정으로 숨기지 않고 오류로 기록 |

12:26:35 KST에 시간 트리거로 실행됐고 결과 코드 `0`과 새로운 점검 파일 생성을 확인했다. [예약 실행 검증](../artifacts/skhynix_v1/architecture_scale_001/monitor/installation-validation-001.json), [27개 회귀 검사 결과](../artifacts/skhynix_v1/architecture_scale_001/monitor/probe-validation-001.json), [검사 XML](../artifacts/skhynix_v1/architecture_scale_001/monitor/probe-validation-001.xml)을 보존했다.

학습된 메모리의 효과는 별도의 공식 OFF/ON 평가 결과로 판단한다. 진행 상태가 정상이라는 사실이나 점검 테스트 통과가 해결률 상승을 뜻하지 않는다.

실험 데이터는 읽기만 수행하고, 점검 결과는 별도 [monitor 디렉터리](../artifacts/skhynix_v1/architecture_scale_001/monitor)에 쓴다. `latest.json`과 보고서는 최신 상태로 교체하고, `samples`에는 개별 점검을, `events.jsonl`에는 상태 변화를 보존한다. [등록 기록](../artifacts/skhynix_v1/architecture_scale_001/monitor/enrollment.json)은 설정과 점검 코드 해시를 포함한다. 점검 코드의 회귀 검사 **27개가 통과**했으며, 별도 모델 호출이나 공식 채점은 없었다.

저장소에서 PowerShell로 실행 상태를 확인할 수 있다.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/Start-SkhynixScaleMonitor.ps1 -Mode Status
```

즉시 한 번 점검하려면 같은 명령에서 `-Mode Check`를 사용한다. 정기 점검만 비활성화하려면 다음 명령을 사용한다. 이 명령은 실험 컨트롤러에 영향을 주지 않는다.

```powershell
Disable-ScheduledTask -TaskName 'SkhynixMemoryScaleMonitor-ESM'
```
