$ErrorActionPreference = 'Stop'
$recoveryRepo = Split-Path -Parent $PSScriptRoot
$recoveryPublic = Join-Path $recoveryRepo 'artifacts\skhynix_v1\architecture_scale_001'
$recoveryProcesses = Join-Path $recoveryPublic 'processes'

function Get-RecoveryReference([string]$Path) {
    [ordered]@{path = '/mnt/c/' + $Path.Substring(3).Replace('\', '/');
        sha256 = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()}
}

function Assert-RecoveryReference([object]$Reference) {
    if (-not $Reference.path.StartsWith('/mnt/c/')) { throw 'Expected a C-drive retained reference.' }
    $boundPath = 'C:\' + $Reference.path.Substring(7).Replace('/', '\')
    if ((Get-FileHash -LiteralPath $boundPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Reference.sha256) {
        throw 'A retained startup reference changed.'
    }
}

$recoveryLock = [System.IO.File]::Open((Join-Path $recoveryProcesses 'launcher.lock'),
    [System.IO.FileMode]::OpenOrCreate, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
try {
    foreach ($receiptFile in Get-ChildItem -LiteralPath $recoveryProcesses -Filter '*.launch.json') {
        $receipt = Get-Content -LiteralPath $receiptFile.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
        $process = Get-Process -Id $receipt.process_id -ErrorAction SilentlyContinue
        if ($null -ne $process -and $process.StartTime.ToUniversalTime().ToString('o') -eq $receipt.process_started_at) {
            throw 'A scale controller is still running.'
        }
    }
    foreach ($intent in Get-ChildItem -LiteralPath $recoveryProcesses -Filter '*.intent.json') {
        if (-not (Test-Path -LiteralPath $intent.FullName.Replace('.intent.json', '.launch.json'))) {
            throw 'An unresolved launch intent needs inspection.'
        }
    }
    $activePath = Join-Path $recoveryPublic 'active-controller.json'
    $previous = Get-Content -LiteralPath $activePath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($previous.configuration_name -ne 'architecture_002_pipeline_v3.json' -or
        (Get-FileHash -LiteralPath $activePath -Algorithm SHA256).Hash.ToLowerInvariant() -ne '35ef87510af1d8fb0e8e9d5082ab26b7271ed99ad1ac956338f541908e88abd7') {
        throw 'The active predecessor differs from the reviewed v3 activation.'
    }
    $configPath = Join-Path $recoveryRepo 'configs\skhynix_v1\architecture_002_pipeline_v4.json'
    $config = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $configRef = Get-RecoveryReference $configPath
    $validationPath = Join-Path $recoveryPublic 'startup-validation-v4.json'
    $validation = Get-Content -LiteralPath $validationPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($validation.status -ne 'VALIDATED_NOT_LAUNCHED' -or
        $validation.configuration_reference.path -ne $configRef.path -or
        $validation.configuration_reference.sha256 -ne $configRef.sha256 -or
        $validation.controller_reference.sha256 -ne $config.pipeline_source_reference.sha256 -or
        $validation.captured_cells -ne 45 -or $validation.remaining_training120_count -ne 75 -or
        $validation.replacement_task_id -ne 'swebench--django__django-16686' -or
        $validation.native_infrastructure_replacements_authorized -ne 1 -or
        $validation.official_outcome_retries -ne $false -or
        $validation.model_calls -ne 0 -or $validation.official_grader_runs -ne 0 -or
        $validation.controller_tests_passed -lt 1) {
        throw 'The startup evidence does not authorize the exact reviewed recovery.'
    }
    Assert-RecoveryReference $validation.controller_reference
    Assert-RecoveryReference $validation.source_recovery_reference
    Assert-RecoveryReference $validation.replacement_reference
    Assert-RecoveryReference $validation.controller_test_reference
    Assert-RecoveryReference $validation.quota_probe_reference
    $archivePath = Join-Path $recoveryPublic 'active-controller-v3.json'
    if (Test-Path -LiteralPath $archivePath) {
        if ((Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash -ne
            (Get-FileHash -LiteralPath $activePath -Algorithm SHA256).Hash) { throw 'Prior activation archive differs.' }
    } else { [System.IO.File]::Copy($activePath, $archivePath, $false) }
    $activation = [ordered]@{schema='skhynix/architecture-active-controller/1.0';
        configuration_name='architecture_002_pipeline_v4.json'; configuration_reference=$configRef;
        startup_validation_reference=(Get-RecoveryReference $validationPath);
        superseded_scale_configuration_reference=$previous.configuration_reference;
        superseded_activation_reference=(Get-RecoveryReference $archivePath);
        superseded_pilot_configuration_reference=$previous.superseded_pilot_configuration_reference;
        superseded_prelaunch_configuration_reference=$previous.superseded_prelaunch_configuration_reference;
        native_outcome_retries=$false; official_grading_retries=$false;
        native_infrastructure_replacements_authorized=1;
        infrastructure_replacement_reference=$validation.replacement_reference;
        activated_at=[DateTime]::UtcNow.ToString('o');
        reason='Preserve45 valid sources and the failed quota attempt; authorize one separately recorded fresh-budget infrastructure replacement and74 never-started sources. Fixed datasets and scoring remain bound.'}
    $versionPath = Join-Path $recoveryPublic 'active-controller-v4.json'
    $nextPath = Join-Path $recoveryPublic 'active-controller.next.json'
    $backupPath = Join-Path $recoveryPublic 'active-controller-v3-replacement-backup.json'
    foreach ($target in @($versionPath, $nextPath, $backupPath)) {
        if (Test-Path -LiteralPath $target) { throw 'Recovery activation staging already exists; inspect before repeating.' }
    }
    [System.IO.File]::WriteAllText($versionPath, ($activation | ConvertTo-Json -Depth 8), [System.Text.UTF8Encoding]::new($false))
    [System.IO.File]::Copy($versionPath, $nextPath, $false)
    [System.IO.File]::Replace($nextPath, $activePath, $backupPath)
    Get-RecoveryReference $versionPath | ConvertTo-Json -Depth 4
} finally { $recoveryLock.Dispose() }
