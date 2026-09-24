param(
    [ValidateSet('Start', 'Status', 'Check')][string]$Mode = 'Status',
    [ValidateRange(1, 1440)][int]$IntervalMinutes = 5,
    [ValidateRange(10, 1440)][int]$StaleMinutes = 60
)

$ErrorActionPreference = 'Stop'
$monitorRepo = Split-Path -Parent $PSScriptRoot
$monitorRoot = Join-Path $monitorRepo 'artifacts\skhynix_v1\architecture_scale_001\monitor'
$monitorScript = Join-Path $PSScriptRoot 'Watch-SkhynixScalePipeline.ps1'
$monitorEnrollment = Join-Path $monitorRoot 'enrollment.json'
$monitorTaskName = 'SkhynixMemoryScaleMonitor-ESM'
$monitorPowerShell = Join-Path $PSHOME 'powershell.exe'
$monitorUtf8 = [System.Text.UTF8Encoding]::new($false)
$null = New-Item -ItemType Directory -Path $monitorRoot -Force

if ($Mode -eq 'Check') {
    & $monitorScript -Mode Check -IntervalMinutes $IntervalMinutes -StaleMinutes $StaleMinutes
    exit 0
}

$monitorSetupLock = [System.IO.File]::Open((Join-Path $monitorRoot 'setup.lock'),
    [System.IO.FileMode]::OpenOrCreate, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
try {
    $existing = if (Test-Path -LiteralPath $monitorEnrollment) { Get-Content -LiteralPath $monitorEnrollment -Raw -Encoding UTF8 | ConvertFrom-Json } else { $null }
    $task = Get-ScheduledTask -TaskName $monitorTaskName -ErrorAction SilentlyContinue
    if ($Mode -eq 'Status') {
        $last = if (Test-Path -LiteralPath (Join-Path $monitorRoot 'latest.json')) { Get-Content -LiteralPath (Join-Path $monitorRoot 'latest.json') -Raw -Encoding UTF8 | ConvertFrom-Json } else { $null }
        $taskInfo = if ($null -ne $task) { Get-ScheduledTaskInfo -TaskName $monitorTaskName } else { $null }
        $loopAlive = $false
        if ($null -ne $existing -and $existing.mode -eq 'BACKGROUND_LOOP') {
            $process = Get-Process -Id $existing.process_id -ErrorAction SilentlyContinue
            $loopAlive = $null -ne $process -and $process.StartTime.ToUniversalTime().ToString('o') -eq $existing.process_started_at
        }
        [ordered]@{mode=$existing.mode; scheduled_task_present=($null -ne $task); task_state=$task.State;
            last_task_result=$taskInfo.LastTaskResult; next_run=$taskInfo.NextRunTime; background_loop_running=$loopAlive;
            interval_minutes=$existing.interval_minutes; last_check=$last.checked_at; status=$last.status;
            controller_running=$last.controller_running; report=(Join-Path $monitorRepo 'reports\SKHYNIX_MEMORY_MONITOR.md')} | ConvertTo-Json -Depth 5
        exit 0
    }
    if ($null -ne $existing) {
        if ($existing.interval_minutes -ne $IntervalMinutes -or $existing.stale_minutes -ne $StaleMinutes) { throw 'Existing monitor uses different settings; review it before changing the schedule.' }
        if ($existing.mode -eq 'TASK_SCHEDULER' -and $null -ne $task) {
            if ($task.Actions.Execute -ne $monitorPowerShell -or $task.Actions.Arguments -ne $existing.arguments) { throw 'Scheduled task action differs from this monitor enrollment.' }
            Write-Output 'Monitor already scheduled.'
            exit 0
        }
        if ($existing.mode -eq 'BACKGROUND_LOOP') {
            $process = Get-Process -Id $existing.process_id -ErrorAction SilentlyContinue
            if ($null -ne $process -and $process.StartTime.ToUniversalTime().ToString('o') -eq $existing.process_started_at) {
                Write-Output 'Monitor already running.'
                exit 0
            }
        }
        throw 'Existing monitor registration is inactive; inspect before creating a replacement.'
    }
    if ($null -ne $task) { throw 'A task with this name already exists without this monitor enrollment.' }
    if ($monitorScript -match '[\r\n"]') { throw 'Invalid monitor script path.' }
    $arguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $monitorScript + '" -Mode Check -IntervalMinutes ' + $IntervalMinutes + ' -StaleMinutes ' + $StaleMinutes
    $monitorUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    $enrollment = [ordered]@{schema='skhynix/scale-monitor-enrollment/1.0'; task_name=$monitorTaskName;
        interval_minutes=$IntervalMinutes; stale_minutes=$StaleMinutes; registered_at=[DateTime]::UtcNow.ToString('o');
        user=$monitorUser; executable=$monitorPowerShell; arguments=$arguments;
        watcher_sha256=(Get-FileHash -LiteralPath $monitorScript -Algorithm SHA256).Hash.ToLowerInvariant();
        probe_sha256=(Get-FileHash -LiteralPath (Join-Path $PSScriptRoot 'trimem_skhynix_scale_health.py') -Algorithm SHA256).Hash.ToLowerInvariant();
        automatic_solver_retries=$false; automatic_grader_retries=$false; automatic_pipeline_restart=$false}
    $action = New-ScheduledTaskAction -Execute $monitorPowerShell -Argument $arguments -WorkingDirectory $monitorRepo
    $timer = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes)
    $logon = New-ScheduledTaskTrigger -AtLogOn -User $monitorUser
    $principal = New-ScheduledTaskPrincipal -UserId $monitorUser -LogonType Interactive -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 2) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    $definition = New-ScheduledTask -Action $action -Trigger @($timer, $logon) -Principal $principal -Settings $settings -Description 'Read-only SK hynix memory experiment health checks. Never restarts the solver or grader.'
    $taskXml = $definition | Export-ScheduledTask
    [System.IO.File]::WriteAllText((Join-Path $monitorRoot 'task-definition.xml'), $taskXml, [System.Text.Encoding]::Unicode)
    try {
        $null = Register-ScheduledTask -TaskName $monitorTaskName -InputObject $definition
        $enrollment.mode = 'TASK_SCHEDULER'
    } catch {
        # Task creation may be restricted for a non-administrator. The fallback
        # checks immediately and remains local to the current Windows session.
        $enrollment.mode = 'BACKGROUND_LOOP'
        $enrollment.scheduler_registration_error = $_.Exception.Message
        $loopArguments = $arguments.Replace('-Mode Check', '-Mode Watch')
        $loop = Start-Process -FilePath $monitorPowerShell -ArgumentList $loopArguments -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput (Join-Path $monitorRoot 'watcher-stdout.log') -RedirectStandardError (Join-Path $monitorRoot 'watcher-stderr.log')
        $enrollment.process_id = $loop.Id
        $enrollment.process_started_at = $loop.StartTime.ToUniversalTime().ToString('o')
    }
    [System.IO.File]::WriteAllText($monitorEnrollment, ($enrollment | ConvertTo-Json -Depth 6), $monitorUtf8)
    if ($enrollment.mode -eq 'TASK_SCHEDULER') { Start-ScheduledTask -TaskName $monitorTaskName }
    $enrollment | ConvertTo-Json -Depth 6
} finally { $monitorSetupLock.Dispose() }
