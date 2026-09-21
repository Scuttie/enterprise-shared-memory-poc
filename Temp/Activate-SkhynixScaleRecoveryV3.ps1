$ErrorActionPreference = 'Stop'
$recoveryRepo = Split-Path -Parent $PSScriptRoot
$recoveryPublic = Join-Path $recoveryRepo 'artifacts\skhynix_v1\architecture_scale_001'
$recoveryProcesses = Join-Path $recoveryPublic 'processes'
$recoveryLock = [System.IO.File]::Open((Join-Path $recoveryProcesses 'launcher.lock'),
    [System.IO.FileMode]::OpenOrCreate, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)

function Get-RecoveryReference([string]$Path) {
    [ordered]@{path = '/mnt/c/' + $Path.Substring(3).Replace('\', '/');
        sha256 = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()}
}

try {
    foreach ($recoveryReceiptPath in Get-ChildItem -LiteralPath $recoveryProcesses -Filter '*.launch.json') {
        $recoveryReceipt = Get-Content -LiteralPath $recoveryReceiptPath.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
        $recoveryProcess = Get-Process -Id $recoveryReceipt.process_id -ErrorAction SilentlyContinue
        if ($null -ne $recoveryProcess -and $recoveryProcess.StartTime.ToUniversalTime().ToString('o') -eq $recoveryReceipt.process_started_at) {
            throw 'An earlier scale controller is still running.'
        }
    }
    foreach ($recoveryIntent in Get-ChildItem -LiteralPath $recoveryProcesses -Filter '*.intent.json') {
        if (-not (Test-Path -LiteralPath $recoveryIntent.FullName.Replace('.intent.json', '.launch.json'))) {
            throw 'An unresolved scale launch intent needs inspection.'
        }
    }
    $recoveryActivePath = Join-Path $recoveryPublic 'active-controller.json'
    $recoveryPreviousHash = (Get-FileHash -LiteralPath $recoveryActivePath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($recoveryPreviousHash -ne 'e940bdaa5f9a5cf098a20548bc0c5f260c2edb28e0e429bf9852deddc3d8ae2d') {
        throw 'The prior active controller differs from the reviewed migration predecessor.'
    }
    $recoveryConfigPath = Join-Path $recoveryRepo 'configs\skhynix_v1\architecture_002_pipeline_v3.json'
    $recoveryConfigRef = Get-RecoveryReference $recoveryConfigPath
    $recoveryValidationPath = Join-Path $recoveryPublic 'startup-validation-v3.json'
    $recoveryValidation = Get-Content -LiteralPath $recoveryValidationPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($recoveryValidation.status -ne 'VALIDATED_NOT_LAUNCHED' -or
        $recoveryValidation.configuration_reference.sha256 -ne $recoveryConfigRef.sha256 -or
        $recoveryValidation.configuration_reference.path -ne $recoveryConfigRef.path -or
        $recoveryValidation.controller_reference.sha256 -ne 'a8cb381806243aadb70340cef80d129d7c2eee440a90dcc158ae519684608d50' -or
        $recoveryValidation.adopted_source_attempts -ne 21 -or $recoveryValidation.official_complete -ne 19 -or
        $recoveryValidation.official_undetermined -ne 2 -or $recoveryValidation.captured_cells -ne 21 -or
        $recoveryValidation.model_calls -ne 0 -or $recoveryValidation.official_grader_runs -ne 0 -or
        $recoveryValidation.outcome_retries -ne $false) {
        throw 'Recovery startup evidence is not the reviewed no-replay source adoption.'
    }
    $recoveryArchivePath = Join-Path $recoveryPublic 'active-controller-v2.json'
    if (Test-Path -LiteralPath $recoveryArchivePath) { throw 'Prior activation archive already exists; inspect before rerunning.' }
    [System.IO.File]::Copy($recoveryActivePath, $recoveryArchivePath, $false)
    $recoveryPrevious = Get-Content -LiteralPath $recoveryActivePath -Raw -Encoding UTF8 | ConvertFrom-Json
    $recoveryActivation = [ordered]@{
        schema = 'skhynix/architecture-active-controller/1.0';
        configuration_name = 'architecture_002_pipeline_v3.json'; configuration_reference = $recoveryConfigRef;
        startup_validation_reference = (Get-RecoveryReference $recoveryValidationPath);
        superseded_scale_configuration_reference = $recoveryPrevious.configuration_reference;
        superseded_activation_reference = (Get-RecoveryReference $recoveryArchivePath);
        superseded_pilot_configuration_reference = $recoveryPrevious.superseded_pilot_configuration_reference;
        superseded_prelaunch_configuration_reference = $recoveryPrevious.superseded_prelaunch_configuration_reference;
        native_outcome_retries = $false; official_grading_retries = $false;
        activated_at = [DateTime]::UtcNow.ToString('o');
        reason = 'Retain21sealedsourceattempts including2undeterminedgrades; collect exactremaining3 before frozen120/240,development60,final500. Originalresults unchanged.'
    }
    $recoveryVersionPath = Join-Path $recoveryPublic 'active-controller-v3.json'
    if (Test-Path -LiteralPath $recoveryVersionPath) { throw 'Recovery activation already exists; inspect before rerunning.' }
    [System.IO.File]::WriteAllText($recoveryVersionPath, ($recoveryActivation | ConvertTo-Json -Depth 8), [System.Text.UTF8Encoding]::new($false))
    $recoveryNextPath = Join-Path $recoveryPublic 'active-controller.next.json'
    if (Test-Path -LiteralPath $recoveryNextPath) { throw 'Unresolved activation staging file.' }
    [System.IO.File]::Copy($recoveryVersionPath, $recoveryNextPath, $false)
    $recoveryReplacementBackup = Join-Path $recoveryPublic 'active-controller-v2-replacement-backup.json'
    if (Test-Path -LiteralPath $recoveryReplacementBackup) { throw 'A prior activation replacement needs inspection.' }
    [System.IO.File]::Replace($recoveryNextPath, $recoveryActivePath, $recoveryReplacementBackup)
    Get-RecoveryReference $recoveryVersionPath | ConvertTo-Json -Depth 4
}
finally {
    $recoveryLock.Dispose()
}
