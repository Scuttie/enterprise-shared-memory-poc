param([ValidateSet('Start','Run','Status')][string]$Mode = 'Status')
$ErrorActionPreference = 'Stop'
$driverRepo = Split-Path -Parent $PSScriptRoot
$driverPublic = Join-Path $driverRepo 'artifacts\skhynix_v1\architecture_scale_001'
$driverRoot = Join-Path $driverPublic 'recovery-v10-driver'
$driverIntent = Join-Path $driverRoot 'intent.json'
$driverState = Join-Path $driverRoot 'state.json'
$driverUtf8 = [System.Text.UTF8Encoding]::new($false)
$null = New-Item -ItemType Directory -Path $driverRoot -Force

function Write-DriverState([string]$Phase, [string]$Failure = '') {
    $value = [ordered]@{schema='skhynix/grading-continuation-driver/1.0'; at=[DateTime]::UtcNow.ToString('o');
        phase=$Phase; error=$Failure; solver_retries=$false; grader_retries=$false;
        pipeline_configuration='architecture_002_pipeline_v10.json'}
    $next = $driverState + '.next'
    [System.IO.File]::WriteAllText($next, ($value | ConvertTo-Json), $driverUtf8)
    if (Test-Path -LiteralPath $driverState) {
        $backup = $driverState + '.backup'
        [System.IO.File]::Replace($next, $driverState, $backup)
        Remove-Item -LiteralPath $backup
    } else { [System.IO.File]::Move($next, $driverState) }
    $value | ConvertTo-Json -Compress
}

function Assert-DriverDependencies([object]$Binding) {
    foreach ($reference in $Binding.dependencies) {
        if ((Get-FileHash -LiteralPath $reference.path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $reference.sha256) {
            throw ('Bound recovery dependency changed: ' + $reference.path)
        }
    }
}

function Test-PreparationRunning([object]$Binding) {
    $process = Get-Process -Id $Binding.process_id -ErrorAction SilentlyContinue
    return $null -ne $process -and $process.StartTime.ToUniversalTime().ToString('o') -eq $Binding.process_started_at
}

if ($Mode -eq 'Status') {
    if (Test-Path -LiteralPath $driverState) { Get-Content -LiteralPath $driverState -Raw -Encoding UTF8 }
    exit 0
}
if ($Mode -eq 'Start') {
    $setupLock = [System.IO.File]::Open((Join-Path $driverRoot 'setup.lock'),
        [System.IO.FileMode]::OpenOrCreate, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
    try {
        if (Test-Path -LiteralPath $driverIntent) { throw 'This continuation driver is already enrolled.' }
        $preparations = @(Get-CimInstance Win32_Process -Filter "Name='wsl.exe'" | Where-Object {
            $_.CommandLine -like '*prepare_skhynix_scale_recovery_v10.py prepare*'
        } | ForEach-Object {
            $process = Get-Process -Id $_.ProcessId
            [ordered]@{process_id=$process.Id; process_started_at=$process.StartTime.ToUniversalTime().ToString('o')}
        })
        if ($preparations.Count -lt 1) { throw 'Expected the existing preparation process; no automatic preparation retry is permitted.' }
        $dependencies = @('Temp\prepare_skhynix_scale_recovery_v10.py', 'Temp\validate_skhynix_scale_recovery_v10.py',
            'Temp\Activate-SkhynixScaleRecoveryV10.ps1', 'Temp\Continue-SkhynixScaleRecoveryV10.ps1',
            'scripts\Start-SkhynixScalePipeline.ps1', 'configs\skhynix_v1\architecture_002_pipeline_v10.json',
            'artifacts\skhynix_v1\architecture_scale_001\runtime-freeze-006.json',
            'artifacts\skhynix_v1\architecture_scale_001\official-harness-loader-v3.json',
            'artifacts\skhynix_v1\architecture_scale_001\native-binary-001.json',
            'artifacts\skhynix_v1\architecture_scale_001\continuation-controller-tests-010.xml',
            'artifacts\skhynix_v1\architecture_scale_001\continuation-runtime-tests-006.xml',
            'C:\Users\jewon\AppData\Local\Temp\skhynix-architecture-scale-001-codex-v1\codex.exe',
            'C:\Users\jewon\AppData\Local\Temp\skhynix-architecture-scale-001-controller-v10\trimem_skhynix_architecture_scale_pipeline.py')
        $references = @($dependencies | ForEach-Object {
            $path = if ([System.IO.Path]::IsPathRooted($_)) { $_ } else { Join-Path $driverRepo $_ }
            [ordered]@{path=$path; sha256=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()}
        })
        $intent = [ordered]@{schema='skhynix/grading-continuation-driver-intent/1.0'; at=[DateTime]::UtcNow.ToString('o');
            preparation_processes=$preparations; dependencies=$references; solver_retries=$false; grader_retries=$false}
        [System.IO.File]::WriteAllText($driverIntent, ($intent | ConvertTo-Json -Depth 8), $driverUtf8)
        $arguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $PSCommandPath + '" -Mode Run'
        $process = Start-Process -FilePath (Join-Path $PSHOME 'powershell.exe') -ArgumentList $arguments -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput (Join-Path $driverRoot 'stdout.log') -RedirectStandardError (Join-Path $driverRoot 'stderr.log')
        $launch = [ordered]@{process_id=$process.Id; process_started_at=$process.StartTime.ToUniversalTime().ToString('o');
            intent_path=$driverIntent; launched_at=[DateTime]::UtcNow.ToString('o')}
        [System.IO.File]::WriteAllText((Join-Path $driverRoot 'launch.json'), ($launch | ConvertTo-Json), $driverUtf8)
        $launch | ConvertTo-Json
    } finally { $setupLock.Dispose() }
    exit 0
}

$driverLock = [System.IO.File]::Open((Join-Path $driverRoot 'run.lock'),
    [System.IO.FileMode]::OpenOrCreate, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
try {
    $intent = Get-Content -LiteralPath $driverIntent -Raw -Encoding UTF8 | ConvertFrom-Json
    Assert-DriverDependencies $intent
    if (Test-Path -LiteralPath $driverState) { throw 'This driver has already run; inspect the retained result before taking further action.' }
    Write-DriverState 'WAITING_FOR_SOURCE_PREPARATION'
    $deadline = [DateTime]::UtcNow.AddMinutes(90)
    while (@($intent.preparation_processes | Where-Object { Test-PreparationRunning $_ }).Count -gt 0) {
        if ([DateTime]::UtcNow -gt $deadline) { throw 'Preparation exceeded90 minutes; original process left intact.' }
        Start-Sleep -Seconds 5
    }
    Assert-DriverDependencies $intent
    if (-not (Test-Path -LiteralPath (Join-Path $driverPublic 'source-recovery-010.json'))) {
        throw 'Preparation ended without a completed receipt; no solver started.'
    }
    Write-DriverState 'VALIDATING_PREPARED_RECOVERY'
    & wsl.exe -d TriMemRunner2404 -u trimem-runner -- env PYTHONDONTWRITEBYTECODE=1 `
        LD_LIBRARY_PATH=/opt/trimem-runner-cache/work-ci/_tool/Python/3.11.10/x64/lib `
        HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 `
        PYTHONPATH=/mnt/c/Users/jewon/AppData/Local/Temp/skhynix-architecture-scale-001-source-v3/scripts:/mnt/c/Users/jewon/AppData/Local/Temp/skhynix-architecture-scale-001-source-v3/src `
        /opt/trimem-rehearsals/e932-preflight/venv/bin/python `
        /mnt/c/Users/jewon/esm-r23-d115-writer/Temp/validate_skhynix_scale_recovery_v10.py `
        --tests-xml /mnt/c/Users/jewon/esm-r23-d115-writer/artifacts/skhynix_v1/architecture_scale_001/continuation-controller-tests-010.xml `
        --runtime-tests-xml /mnt/c/Users/jewon/esm-r23-d115-writer/artifacts/skhynix_v1/architecture_scale_001/continuation-runtime-tests-006.xml
    if ($LASTEXITCODE -ne 0) { throw 'Startup validation failed; no solver started.' }
    Assert-DriverDependencies $intent
    Write-DriverState 'ACTIVATING_VALIDATED_CONTROLLER'
    & (Join-Path $PSScriptRoot 'Activate-SkhynixScaleRecoveryV10.ps1')
    Assert-DriverDependencies $intent
    & (Join-Path $driverRepo 'scripts\Start-SkhynixScalePipeline.ps1') -Mode Start -ConfigurationName architecture_002_pipeline_v10.json
    Write-DriverState 'CONTROLLER_LAUNCHED'
    & (Join-Path $driverRepo 'scripts\Start-SkhynixScaleMonitor.ps1') -Mode Check
} catch {
    Write-DriverState 'BLOCKED' $_.Exception.Message
    throw
} finally { $driverLock.Dispose() }
