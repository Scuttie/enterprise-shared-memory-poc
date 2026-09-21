param(
    [ValidateSet('Check', 'Watch')][string]$Mode = 'Check',
    [ValidateRange(1, 1440)][int]$IntervalMinutes = 5,
    [ValidateRange(10, 1440)][int]$StaleMinutes = 60
)

$ErrorActionPreference = 'Stop'
$monitorRepo = Split-Path -Parent $PSScriptRoot
$monitorRoot = Join-Path $monitorRepo 'artifacts\skhynix_v1\architecture_scale_001\monitor'
$monitorReport = Join-Path $monitorRepo 'reports\SKHYNIX_MEMORY_MONITOR.md'
$null = New-Item -ItemType Directory -Path $monitorRoot -Force
$null = New-Item -ItemType Directory -Path (Join-Path $monitorRoot 'samples') -Force
$monitorUtf8 = [System.Text.UTF8Encoding]::new($false)

function Write-MonitorAtomic([string]$Path, [string]$Text) {
    $temporary = $Path + '.' + [Guid]::NewGuid().ToString('N') + '.tmp'
    [System.IO.File]::WriteAllText($temporary, $Text, $monitorUtf8)
    if (Test-Path -LiteralPath $Path) {
        # An explicit backup avoids PowerShell 5 converting null to an invalid path.
        $backup = $temporary + '.backup'
        [System.IO.File]::Replace($temporary, $Path, $backup)
        Remove-Item -LiteralPath $backup
    } else { [System.IO.File]::Move($temporary, $Path) }
}

function Invoke-MonitorProcess([string]$Program, [string[]]$Arguments, [int]$TimeoutSeconds = 45, [bool]$UnicodeOutput = $false) {
    foreach ($argument in $Arguments) {
        if ($argument -match '[\s"]') { throw 'Monitor subprocess argument requires unsupported quoting.' }
    }
    $info = New-Object System.Diagnostics.ProcessStartInfo
    $info.FileName = $Program
    $info.Arguments = $Arguments -join ' '
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $info.StandardOutputEncoding = if ($UnicodeOutput) { [Text.Encoding]::Unicode } else { [Text.Encoding]::UTF8 }
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $info
    try {
        $null = $process.Start()
        $stdout = $process.StandardOutput.ReadToEndAsync()
        $stderr = $process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
            # Only the read-only probe process created above is stopped.
            $process.Kill()
            throw 'READ_ONLY_PROBE_TIMEOUT'
        }
        $text = $stdout.GetAwaiter().GetResult()
        $null = $stderr.GetAwaiter().GetResult()
        if ($process.ExitCode -ne 0) { throw ('READ_ONLY_PROBE_EXIT_' + $process.ExitCode) }
        if ($text.Length -gt 262144) { throw 'READ_ONLY_PROBE_OUTPUT_TOO_LARGE' }
        return $text
    } finally { $process.Dispose() }
}

function Show-MonitorAlert([string]$Status) {
    try {
        Add-Type -AssemblyName System.Windows.Forms
        Add-Type -AssemblyName System.Drawing
        $icon = New-Object System.Windows.Forms.NotifyIcon
        $icon.Icon = [System.Drawing.SystemIcons]::Warning
        $icon.Visible = $true
        $icon.BalloonTipTitle = 'SK hynix experiment: ' + $Status
        $icon.BalloonTipText = 'The local monitor detected a condition to inspect. Open SKHYNIX_MEMORY_MONITOR.md in the repository reports folder.'
        $icon.ShowBalloonTip(15000)
        Start-Sleep -Seconds 3
        $icon.Dispose()
        return 'ATTEMPTED_DELIVERY_NOT_CONFIRMED'
    } catch { return 'UNAVAILABLE' }
}

function Invoke-MonitorCheck {
    $lock = $null
    try {
        $lock = [System.IO.File]::Open((Join-Path $monitorRoot 'check.lock'),
            [System.IO.FileMode]::OpenOrCreate, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
    } catch [System.IO.IOException] { return }
    try {
        $latestPath = Join-Path $monitorRoot 'latest.json'
        $previous = if (Test-Path -LiteralPath $latestPath) { Get-Content -LiteralPath $latestPath -Raw -Encoding UTF8 | ConvertFrom-Json } else { $null }
        $probe = $null
        $probeError = $null
        $activeProcesses = @()
        $processCheckCompleted = $false
        $configurationName = $null
        $configurationHash = $null
        $stderrBytes = 0
        $runningDistro = $false
        try {
            $activation = Get-Content -LiteralPath (Join-Path $monitorRepo 'artifacts\skhynix_v1\architecture_scale_001\active-controller.json') -Raw -Encoding UTF8 | ConvertFrom-Json
            $configurationName = $activation.configuration_name
            if ($configurationName -notmatch '^architecture_002_pipeline_v[0-9]+\.json$') { throw 'ACTIVE_CONFIGURATION_NAME_INVALID' }
            $configPath = Join-Path $monitorRepo ('configs\skhynix_v1\' + $configurationName)
            $configurationHash = (Get-FileHash -LiteralPath $configPath -Algorithm SHA256).Hash.ToLowerInvariant()
            $linuxConfigPath = '/mnt/c/' + $configPath.Substring(3).Replace('\', '/')
            if ($configurationHash -ne $activation.configuration_reference.sha256 -or $linuxConfigPath -ne $activation.configuration_reference.path) { throw 'ACTIVE_CONFIGURATION_BINDING_CHANGED' }
            $configuration = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
            if (-not $configuration.progress_root.StartsWith('/mnt/c/')) { throw 'ACTIVE_PROGRESS_ROOT_INVALID' }
            $activeProgressRoot = 'C:\' + $configuration.progress_root.Substring(7).Replace('/', '\')
            $processFolder = Join-Path $activeProgressRoot 'processes'
            foreach ($path in Get-ChildItem -LiteralPath $processFolder -Filter '*.launch.json') {
                $receipt = Get-Content -LiteralPath $path.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
                if ($receipt.configuration_sha256 -ne $configurationHash) { continue }
                $candidate = Get-Process -Id $receipt.process_id -ErrorAction SilentlyContinue
                if ($null -ne $candidate -and $candidate.StartTime.ToUniversalTime().ToString('o') -eq $receipt.process_started_at) {
                    $activeProcesses += $candidate.Id
                    if (Test-Path -LiteralPath $receipt.stderr_path) { $stderrBytes += (Get-Item -LiteralPath $receipt.stderr_path).Length }
                }
            }
            $processCheckCompleted = $true
            $distros = Invoke-MonitorProcess 'wsl.exe' @('--list', '--running', '--quiet') 15 $true
            $runningDistro = (($distros -replace "`0", '') -split '\r?\n' | ForEach-Object { $_.Trim() }) -contains 'TriMemRunner2404'
            if (-not $runningDistro) { throw 'WSL_DISTRO_NOT_RUNNING' }
            $linuxProbe = '/mnt/c/' + (Join-Path $PSScriptRoot 'trimem_skhynix_scale_health.py').Substring(3).Replace('\', '/')
            $probeText = Invoke-MonitorProcess 'wsl.exe' @('-d', 'TriMemRunner2404', '-u', 'trimem-runner', '--',
                'env', 'PYTHONDONTWRITEBYTECODE=1', '/usr/bin/python3', $linuxProbe,
                '--config', $linuxConfigPath, '--stale-seconds', [string]($StaleMinutes * 60))
            $probe = $probeText | ConvertFrom-Json
        } catch { $probeError = $_.Exception.Message }

        $freeGiB = [Math]::Round(([System.IO.DriveInfo]::new('C')).AvailableFreeSpace / 1GB, 2)
        $status = if ($null -ne $probe) { $probe.status } else { 'PROBE_ERROR' }
        $terminal = $status -in @('COMPLETE', 'COMPLETE_WITH_UNDETERMINED', 'NO_READY_MEMORY_BANK', 'NOT_READY')
        $warnings = @()
        if ($probeError) { $warnings += $probeError }
        if ($null -ne $probe -and $probe.warnings) { $warnings += @($probe.warnings) }
        if (-not $terminal -and $status -ne 'BLOCKED' -and $processCheckCompleted -and $activeProcesses.Count -eq 0) { $status = 'STOPPED' }
        if (-not $terminal -and $freeGiB -lt 10) { $warnings += 'HOST_DISK_BELOW_10_GIB'; if ($status -notin @('BLOCKED', 'STOPPED')) { $status = 'CRITICAL_DISK' } }
        elseif ($freeGiB -lt 25) { $warnings += 'HOST_DISK_BELOW_25_GIB' }
        if ($stderrBytes -gt 0) { $warnings += 'CONTROLLER_STDERR_NONEMPTY' }
        if ($activeProcesses.Count -gt 1) { $warnings += 'MULTIPLE_ACTIVE_CONTROLLERS' }
        $severity = if ($status -in @('BLOCKED', 'STOPPED', 'CRITICAL_DISK', 'PROBE_ERROR')) { 'ERROR' }
            elseif ($status.StartsWith('WARNING_') -or $status -in @('COMPLETE_WITH_UNDETERMINED', 'NO_READY_MEMORY_BANK', 'NOT_READY') -or $warnings.Count -gt 0) { 'WARNING' } else { 'INFO' }
        $at = [DateTime]::UtcNow.ToString('o')
        $fingerprint = $configurationHash + '|' + $status + '|' + (($warnings | Sort-Object) -join ',')
        $changed = $null -eq $previous -or $previous.alert_fingerprint -ne $fingerprint
        $notification = 'NOT_REQUESTED'
        if ($changed -and $severity -in @('ERROR', 'WARNING')) { $notification = Show-MonitorAlert $status }
        $sample = [ordered]@{
            schema='skhynix/scale-local-health/1.0'; checked_at=$at; checked_at_kst=[DateTimeOffset]::UtcNow.ToOffset([TimeSpan]::FromHours(9)).ToString('o');
            status=$status; severity=$severity; interval_minutes=$IntervalMinutes; stale_minutes=$StaleMinutes;
            configuration=$configurationName; configuration_sha256=$configurationHash;
            controller_running=$(if ($processCheckCompleted) { $activeProcesses.Count -gt 0 } else { $null }); controller_process_ids=$activeProcesses;
            process_check_completed=$processCheckCompleted;
            controller_stderr_bytes=$stderrBytes; wsl_running=$runningDistro; host_c_free_gib=$freeGiB;
            probe_error=$probeError; warnings=$warnings; probe=$probe;
            last_successful_probe_at=$(if ($null -ne $probe) { $at } elseif ($null -ne $previous) { $previous.last_successful_probe_at } else { $null });
            alert_fingerprint=$fingerprint; desktop_notification=$notification;
            automatic_solver_retries=$false; automatic_grader_retries=$false; automatic_pipeline_restart=$false;
            monitor_source_sha256=(Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash.ToLowerInvariant()
        }
        $json = $sample | ConvertTo-Json -Depth 16
        $samplePath = Join-Path $monitorRoot ('samples\' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmss.fffffffZ') + '.json')
        [System.IO.File]::WriteAllText($samplePath, $json, $monitorUtf8)
        Write-MonitorAtomic $latestPath $json
        if ($changed) {
            $event = [ordered]@{at=$at; status=$status; severity=$severity; sample_path=$samplePath; notification=$notification}
            [System.IO.File]::AppendAllText((Join-Path $monitorRoot 'events.jsonl'), (($event | ConvertTo-Json -Compress) + "`n"), $monitorUtf8)
        }
        $rows = @('# SK hynix experiment health', '', ('**' + $status + '** | ' + $sample.checked_at_kst), '',
            '| Item | Value |', '| --- | --- |',
            ('| Controller running | ' + $sample.controller_running + ' |'),
            ('| Process IDs | ' + ($activeProcesses -join ', ') + ' |'),
            ('| Configuration | ' + $configurationName + ' |'),
            ('| Check interval | ' + $IntervalMinutes + ' minutes |'),
            ('| Host C free space | ' + $freeGiB + ' GiB |'),
            ('| Last successful probe | ' + $sample.last_successful_probe_at + ' |'),
            ('| Warnings | ' + ($warnings -join ', ') + ' |'), '',
            'Local checks run while Windows is awake and the user is signed in. Desktop alert delivery is not guaranteed. Solver/grader/pipeline retries are never performed by this monitor.', '',
            '[Structured latest check](../artifacts/skhynix_v1/architecture_scale_001/monitor/latest.json) | [State changes](../artifacts/skhynix_v1/architecture_scale_001/monitor/events.jsonl)', '',
            'Training stages:', '', '| Sources target | New tasks completed (lower bound) | Captured sources | L1 | L2 nodes / edges | L3 | Current task |',
            '| --- | --- | --- | --- | --- | --- | --- |')
        if ($null -ne $probe) {
            foreach ($stage in $probe.stages) {
                $rows += ('| ' + $stage.size + ' | ' + $stage.cohort.completed + ' / ' + $stage.cohort.planned + ' | ' + $stage.learning.cells + ' | ' + $stage.learning.L1_episodes + ' | ' + $stage.learning.L2_nodes + ' / ' + $stage.learning.L2_relations + ' | ' + $stage.learning.L3_skills + ' | ' + $stage.cohort.last_event.task_id + ' |')
            }
        }
        $rows += @('', '<details><summary>Public experiment metadata</summary>', '', '```json')
        $rows += $(if ($null -ne $probe) { $probe | ConvertTo-Json -Depth 10 } else { '{"probe":"unavailable"}' })
        $rows += @('```', '', '</details>')
        Write-MonitorAtomic $monitorReport (($rows -join "`n") + "`n")
        [ordered]@{status=$status; severity=$severity; checked_at=$at; report=$monitorReport; controller_running=$sample.controller_running} | ConvertTo-Json -Compress
    } finally { $lock.Dispose() }
}

do {
    Invoke-MonitorCheck
    if ($Mode -eq 'Watch') { Start-Sleep -Seconds ($IntervalMinutes * 60) }
} while ($Mode -eq 'Watch')
