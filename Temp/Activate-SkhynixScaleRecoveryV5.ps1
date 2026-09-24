$ErrorActionPreference = 'Stop'
$recoveryRepo = Split-Path -Parent $PSScriptRoot
$recoveryPublic = Join-Path $recoveryRepo 'artifacts\skhynix_v1\architecture_scale_001'
$recoveryProcesses = Join-Path $recoveryPublic 'processes'

function Get-RecoveryReference([string]$Path) {
    [ordered]@{path = '/mnt/c/' + $Path.Substring(3).Replace('\', '/');
        sha256 = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()}
}

function Assert-RecoveryReference([object]$Reference) {
    if ($null -eq $Reference -or -not $Reference.path.StartsWith('/mnt/c/')) {
        throw 'Expected a C-drive retained reference.'
    }
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
    if ($previous.configuration_name -ne 'architecture_002_pipeline_v4.json' -or
        (Get-FileHash -LiteralPath $activePath -Algorithm SHA256).Hash.ToLowerInvariant() -ne
            '296bd3f9255049d5e3c049254d0206d03c0e0a874a41fbab51714c8638c126d8') {
        throw 'The active predecessor differs from the reviewed v4 activation.'
    }
    $configPath = Join-Path $recoveryRepo 'configs\skhynix_v1\architecture_002_pipeline_v5.json'
    $config = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $configRef = Get-RecoveryReference $configPath
    $validationPath = Join-Path $recoveryPublic 'startup-validation-v5.json'
    $validation = Get-Content -LiteralPath $validationPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($validation.status -ne 'VALIDATED_NOT_LAUNCHED' -or
        $validation.configuration_reference.path -ne $configRef.path -or
        $validation.configuration_reference.sha256 -ne $configRef.sha256 -or
        $validation.controller_reference.path -ne $config.pipeline_source_reference.path -or
        $validation.controller_reference.sha256 -ne $config.pipeline_source_reference.sha256 -or
        $validation.grading_continuation_reference.path -ne $config.grading_continuation_reference.path -or
        $validation.grading_continuation_reference.sha256 -ne $config.grading_continuation_reference.sha256 -or
        $validation.predecessor_activation_reference.path -ne (Get-RecoveryReference (Join-Path $recoveryPublic 'active-controller-v4.json')).path -or
        $validation.predecessor_activation_reference.sha256 -ne (Get-RecoveryReference $activePath).sha256 -or
        $validation.captured_cells -ne 60 -or $validation.official_complete -ne 57 -or
        $validation.official_undetermined -ne 3 -or $validation.remaining_training120_count -ne 60 -or
        @($validation.remaining_training120_task_ids).Count -ne 60 -or
        $validation.remaining_training120_task_ids[0] -ne 'swebench--mwaskom__seaborn-3190' -or
        $validation.all_capture_receipts_validated -ne $true -or
        $validation.native_infrastructure_replacements_authorized -ne 0 -or
        $validation.historical_native_infrastructure_replacements_authorized -ne 1 -or
        $validation.official_outcome_retries -ne $false -or $validation.native_outcome_retries -ne $false -or
        $validation.historical_results_reclassified -ne $false -or
        $validation.source_selection_changed -ne $false -or
        $validation.source_adoption_classifier_changed -ne $true -or
        $validation.grading_semantics_changed -ne $false -or
        $validation.model_calls -ne 0 -or $validation.official_grader_runs -ne 0 -or
        $validation.controller_tests_passed -lt 1) {
        throw 'The startup evidence does not authorize the exact reviewed no-retry continuation.'
    }
    foreach ($reference in @($validation.controller_reference, $validation.source_recovery_reference,
            $validation.grading_continuation_reference, $validation.runtime_change_reference,
            $validation.historical_replacement_reference, $validation.controller_test_reference,
            $validation.validator_source_reference, $validation.predecessor_activation_reference)) {
        Assert-RecoveryReference $reference
    }
    if ($null -ne $validation.runtime_test_reference) {
        Assert-RecoveryReference $validation.runtime_test_reference
        if ($validation.runtime_tests_passed -lt 1) { throw 'Runtime validation did not pass.' }
    }
    $continuationPath = 'C:\' + $validation.grading_continuation_reference.path.Substring(7).Replace('/', '\')
    $continuation = Get-Content -LiteralPath $continuationPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($continuation.runtime_change_reference.path -ne $validation.runtime_change_reference.path -or
        $continuation.runtime_change_reference.sha256 -ne $validation.runtime_change_reference.sha256) {
        throw 'The checked runtime amendment differs from the configured continuation.'
    }
    $archivePath = Join-Path $recoveryPublic 'active-controller-v4.json'
    if (Test-Path -LiteralPath $archivePath) {
        if ((Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash -ne
            (Get-FileHash -LiteralPath $activePath -Algorithm SHA256).Hash) {
            throw 'Prior activation archive differs.'
        }
    } else { [System.IO.File]::Copy($activePath, $archivePath, $false) }
    $activation = [ordered]@{schema='skhynix/architecture-active-controller/1.0';
        configuration_name='architecture_002_pipeline_v5.json'; configuration_reference=$configRef;
        startup_validation_reference=(Get-RecoveryReference $validationPath);
        superseded_scale_configuration_reference=$previous.configuration_reference;
        superseded_activation_reference=(Get-RecoveryReference $archivePath);
        superseded_pilot_configuration_reference=$previous.superseded_pilot_configuration_reference;
        superseded_prelaunch_configuration_reference=$previous.superseded_prelaunch_configuration_reference;
        native_outcome_retries=$false; official_grading_retries=$false;
        native_infrastructure_replacements_authorized=0;
        historical_native_infrastructure_replacements_authorized=1;
        historical_infrastructure_replacement_reference=$validation.historical_replacement_reference;
        grading_continuation_reference=$validation.grading_continuation_reference;
        runtime_change_reference=$validation.runtime_change_reference;
        activated_at=[DateTime]::UtcNow.ToString('o');
        reason='Preserve60 sealed sources and all original outcomes including3 undetermined; adopt the sealed public source through an amended source-adoption classifier and continue exactly60 never-started sources with unchanged grading semantics and no solver or grading retry.'}
    $versionPath = Join-Path $recoveryPublic 'active-controller-v5.json'
    $nextPath = Join-Path $recoveryPublic 'active-controller.next.json'
    $backupPath = Join-Path $recoveryPublic 'active-controller-v4-replacement-backup.json'
    foreach ($target in @($versionPath, $nextPath, $backupPath)) {
        if (Test-Path -LiteralPath $target) {
            throw 'Recovery activation staging already exists; inspect before repeating.'
        }
    }
    [System.IO.File]::WriteAllText($versionPath, ($activation | ConvertTo-Json -Depth 8), [System.Text.UTF8Encoding]::new($false))
    [System.IO.File]::Copy($versionPath, $nextPath, $false)
    [System.IO.File]::Replace($nextPath, $activePath, $backupPath)
    Get-RecoveryReference $versionPath | ConvertTo-Json -Depth 4
} finally { $recoveryLock.Dispose() }
