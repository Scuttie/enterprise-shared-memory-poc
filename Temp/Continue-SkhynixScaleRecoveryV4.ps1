param([ValidateSet('Start','Run','Status')][string]$Mode = 'Status')
$ErrorActionPreference = 'Stop'
$driverRepo = Split-Path -Parent $PSScriptRoot
$driverPublic = Join-Path $driverRepo 'artifacts\skhynix_v1\architecture_scale_001'
$driverRoot = Join-Path $driverPublic 'recovery-v4-driver'
$driverIntentPath = Join-Path $driverRoot 'intent.json'
$driverStatePath = Join-Path $driverRoot 'state.json'
$driverUtf8 = [System.Text.UTF8Encoding]::new($false)
$driverPowerShell = Join-Path $PSHOME 'powershell.exe'
$null = New-Item -ItemType Directory -Path $driverRoot -Force

function Test-DriverProcess([object]$Binding) {
    $process = Get-Process -Id $Binding.process_id -ErrorAction SilentlyContinue
    return $null -ne $process -and $process.StartTime.ToUniversalTime().ToString('o') -eq $Binding.process_started_at
}

function Assert-DriverDependencies([object]$Binding) {
    foreach ($reference in $Binding.source_references) {
        if ((Get-FileHash -LiteralPath $reference.path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $reference.sha256) {
            throw 'A reviewed recovery driver dependency changed.'
        }
    }
    $testsWindows = 'C:\Users\jewon\AppData\Local\Temp\skhynix-architecture-scale-001-controller-v4\validation.xml'
    if ((Get-FileHash -LiteralPath $testsWindows -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Binding.tests_xml_sha256) {
        throw 'The reviewed controller test evidence changed.'
    }
}

function Write-DriverState([string]$Phase, [string]$Failure = '') {
    $value = [ordered]@{schema='skhynix/quota-recovery-driver/1.0'; at=[DateTime]::UtcNow.ToString('o');
        phase=$Phase; error=$Failure; automatic_solver_retries=$false; automatic_grader_retries=$false;
        native_infrastructure_replacements_authorized=1; pipeline_configuration='architecture_002_pipeline_v4.json'}
    $temporary = $driverStatePath + '.next'
    [System.IO.File]::WriteAllText($temporary, ($value | ConvertTo-Json -Depth 5), $driverUtf8)
    if (Test-Path -LiteralPath $driverStatePath) {
        $backup = $driverStatePath + '.backup'
        [System.IO.File]::Replace($temporary, $driverStatePath, $backup)
        Remove-Item -LiteralPath $backup
    } else { [System.IO.File]::Move($temporary, $driverStatePath) }
    $value | ConvertTo-Json -Compress
}

if ($Mode -eq 'Status') {
    if (Test-Path -LiteralPath $driverStatePath) { Get-Content -LiteralPath $driverStatePath -Raw -Encoding UTF8 }
    exit 0
}
if ($Mode -eq 'Start') {
    $setupLock = [System.IO.File]::Open((Join-Path $driverRoot 'setup.lock'),
        [System.IO.FileMode]::OpenOrCreate, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
    try {
        if (Test-Path -LiteralPath $driverIntentPath) { throw 'Recovery driver already enrolled; inspect it before another start.' }
        $dependencies = @('Temp\prepare_skhynix_scale_recovery_v4.py', 'Temp\validate_skhynix_scale_recovery_v4.py',
            'Temp\Activate-SkhynixScaleRecoveryV4.ps1', 'Temp\Continue-SkhynixScaleRecoveryV4.ps1',
            'scripts\Start-SkhynixScalePipeline.ps1', 'configs\skhynix_v1\architecture_002_pipeline_v4.json')
        $references = @($dependencies | ForEach-Object {
            $path = Join-Path $driverRepo $_
            [ordered]@{path=$path; sha256=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()}
        })
        $preparations = @(Get-CimInstance Win32_Process -Filter "Name='wsl.exe'" | Where-Object {
            $_.CommandLine -like '*prepare_skhynix_scale_recovery_v4.py prepare*'
        } | ForEach-Object {
            $process = Get-Process -Id $_.ProcessId
            [ordered]@{process_id=$process.Id; process_started_at=$process.StartTime.ToUniversalTime().ToString('o')}
        })
        $intent = [ordered]@{schema='skhynix/quota-recovery-driver-intent/1.0'; at=[DateTime]::UtcNow.ToString('o');
            source_references=$references; preparation_processes=$preparations;
            controller_sha256='83ca91baa7b5987b61df9b34eccb1dc5b75b7a347dcc5b48af8b3d8812741f3e';
            tests_xml_sha256='926ce27bfb759c70192b687f15a14f4e89e390591161aa4f2b720c54cac26975';
            automatic_solver_retries=$false; preparation_only_recovery_attempts_allowed=1}
        [System.IO.File]::WriteAllText($driverIntentPath, ($intent | ConvertTo-Json -Depth 8), $driverUtf8)
        $arguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $PSCommandPath + '" -Mode Run'
        $process = Start-Process -FilePath $driverPowerShell -ArgumentList $arguments -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput (Join-Path $driverRoot 'stdout.log') -RedirectStandardError (Join-Path $driverRoot 'stderr.log')
        $launch = [ordered]@{process_id=$process.Id; process_started_at=$process.StartTime.ToUniversalTime().ToString('o');
            intent_path=$driverIntentPath; launched_at=[DateTime]::UtcNow.ToString('o')}
        [System.IO.File]::WriteAllText((Join-Path $driverRoot 'launch.json'), ($launch | ConvertTo-Json), $driverUtf8)
        $launch | ConvertTo-Json
    } finally { $setupLock.Dispose() }
    exit 0
}

$driverLock = [System.IO.File]::Open((Join-Path $driverRoot 'run.lock'),
    [System.IO.FileMode]::OpenOrCreate, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
try {
    $intent = Get-Content -LiteralPath $driverIntentPath -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-DriverDependencies $intent
    if (Test-Path -LiteralPath $driverStatePath) {
        $priorState = Get-Content -LiteralPath $driverStatePath -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($priorState.phase -eq 'CONTROLLER_LAUNCHED') {
            Write-Output 'This recovery already launched its controller.'
            exit 0
        }
    }
    Write-DriverState 'WAITING_FOR_SOURCE_PREPARATION'
    $deadline = [DateTime]::UtcNow.AddMinutes(90)
    while (@($intent.preparation_processes | Where-Object { Test-DriverProcess $_ }).Count -gt 0) {
        if ([DateTime]::UtcNow -gt $deadline) { throw 'Preparation did not finish within90 minutes; original process was left intact.' }
        Start-Sleep -Seconds 5
    }
    $wslPrefix = @('-d','TriMemRunner2404','-u','trimem-runner','--','env','PYTHONDONTWRITEBYTECODE=1',
        'LD_LIBRARY_PATH=/opt/trimem-runner-cache/work-ci/_tool/Python/3.11.10/x64/lib',
        '/opt/trimem-rehearsals/e932-preflight/venv/bin/python')
    $prepared = Join-Path $driverPublic 'source-recovery-004.json'
    Assert-DriverDependencies $intent
    if (-not (Test-Path -LiteralPath $prepared)) {
        # Preparation-only recovery is idempotent and has no solver/grader calls.
        # It is attempted once if the original tool process ended without a receipt.
        $recoveryAttemptPath = Join-Path $driverRoot 'preparation-recovery-attempt.json'
        if (Test-Path -LiteralPath $recoveryAttemptPath) {
            throw 'The one preparation recovery attempt was already used; inspect its result.'
        }
        $attempt = [ordered]@{at=[DateTime]::UtcNow.ToString('o'); operation='PREPARE_ONLY';
            model_calls=0; official_grader_runs=0; intent_sha256=(Get-FileHash -LiteralPath $driverIntentPath -Algorithm SHA256).Hash.ToLowerInvariant()}
        $attemptStream = [System.IO.File]::Open($recoveryAttemptPath, [System.IO.FileMode]::CreateNew,
            [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
        try {
            $attemptBytes = $driverUtf8.GetBytes(($attempt | ConvertTo-Json))
            $attemptStream.Write($attemptBytes, 0, $attemptBytes.Length)
            $attemptStream.Flush($true)
        } finally { $attemptStream.Dispose() }
        Write-DriverState 'RECOVERING_SOURCE_PREPARATION_ONCE'
        & wsl.exe @wslPrefix /mnt/c/Users/jewon/esm-r23-d115-writer/Temp/prepare_skhynix_scale_recovery_v4.py prepare --controller-sha256 $intent.controller_sha256
        if ($LASTEXITCODE -ne 0) { throw 'Source preparation failed; no solver was started.' }
    }
    Assert-DriverDependencies $intent
    Write-DriverState 'VALIDATING_PREPARED_RECOVERY'
    & wsl.exe @wslPrefix /mnt/c/Users/jewon/esm-r23-d115-writer/Temp/validate_skhynix_scale_recovery_v4.py `
        --tests-xml /mnt/c/Users/jewon/AppData/Local/Temp/skhynix-architecture-scale-001-controller-v4/validation.xml
    if ($LASTEXITCODE -ne 0) { throw 'Startup validation failed; no solver was started.' }
    Assert-DriverDependencies $intent
    Write-DriverState 'ACTIVATING_VALIDATED_CONTROLLER'
    & (Join-Path $PSScriptRoot 'Activate-SkhynixScaleRecoveryV4.ps1')
    Assert-DriverDependencies $intent
    & (Join-Path $driverRepo 'scripts\Start-SkhynixScalePipeline.ps1') -Mode Start -ConfigurationName architecture_002_pipeline_v4.json
    Write-DriverState 'CONTROLLER_LAUNCHED'
    & (Join-Path $driverRepo 'scripts\Start-SkhynixScaleMonitor.ps1') -Mode Check
} catch {
    Write-DriverState 'BLOCKED' $_.Exception.Message
    throw
} finally { $driverLock.Dispose() }
