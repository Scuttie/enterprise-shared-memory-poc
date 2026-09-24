param(
    [ValidateSet('Start', 'Status')]
    [string]$Mode = 'Status',
    [ValidatePattern('^architecture_[0-9]+_pipeline_v[0-9]+\.json$')]
    [string]$ConfigurationName = 'architecture_001_pipeline_v3.json'
)

$ErrorActionPreference = 'Stop'
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$scaleActivationPath = Join-Path $repositoryRoot 'artifacts\skhynix_v1\architecture_scale_001\active-controller.json'
if (Test-Path -LiteralPath $scaleActivationPath) {
    $scaleActivation = Get-Content -LiteralPath $scaleActivationPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not $PSBoundParameters.ContainsKey('ConfigurationName') -or $ConfigurationName.StartsWith('architecture_002_')) {
        $scaleConfigurationName = if ($PSBoundParameters.ContainsKey('ConfigurationName')) { $ConfigurationName } else { $scaleActivation.configuration_name }
        & (Join-Path $PSScriptRoot 'Start-SkhynixScalePipeline.ps1') -Mode $Mode -ConfigurationName $scaleConfigurationName
        exit $LASTEXITCODE
    }
    if ($Mode -eq 'Start') { throw 'The original pilot controller is superseded by the expanded scale experiment. Use Start-SkhynixScalePipeline.ps1.' }
}
$configurationPath = Join-Path $repositoryRoot ('configs\skhynix_v1\' + $ConfigurationName)
$progressPath = Join-Path $repositoryRoot 'artifacts\skhynix_v1\architecture_execution_001\progress.json'
$processRoot = Join-Path $repositoryRoot 'artifacts\skhynix_v1\architecture_execution_001\processes'

function Convert-CMountToWindowsPath([string]$Value) {
    if (-not $Value.StartsWith('/mnt/c/')) { throw 'Expected an explicit C-drive mount path.' }
    return 'C:\' + $Value.Substring(7).Replace('/', '\')
}

function Get-VerifiedReference([object]$Reference) {
    $referencePath = Convert-CMountToWindowsPath $Reference.path
    $actualHash = (Get-FileHash -LiteralPath $referencePath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -ne $Reference.sha256) { throw "Frozen reference changed: $referencePath" }
    return $referencePath
}

$configuration = Get-Content -LiteralPath $configurationPath -Raw -Encoding UTF8 | ConvertFrom-Json
$null = Get-VerifiedReference $configuration.pipeline_source_reference
$trainingPath = Get-VerifiedReference $configuration.training_experiment_reference
$training = Get-Content -LiteralPath $trainingPath -Raw -Encoding UTF8 | ConvertFrom-Json
$linuxConfiguration = '/mnt/c/' + $configurationPath.Substring(3).Replace('\', '/')
$configurationHash = (Get-FileHash -LiteralPath $configurationPath -Algorithm SHA256).Hash.ToLowerInvariant()
$wslArguments = @(
    '-d', 'TriMemRunner2404', '-u', 'trimem-runner', '--', 'env',
    'PYTHONDONTWRITEBYTECODE=1',
    'LD_LIBRARY_PATH=/opt/trimem-runner-cache/work-ci/_tool/Python/3.11.10/x64/lib',
    'HF_HUB_OFFLINE=1', 'TRANSFORMERS_OFFLINE=1',
    ('PYTHONPATH=' + $training.source_root + '/scripts:' + $training.source_root + '/src'),
    '/opt/trimem-rehearsals/e932-preflight/venv/bin/python',
    $configuration.pipeline_source_reference.path
)

$null = New-Item -ItemType Directory -Path $processRoot -Force
$launcherLock = $null
try {
$launcherLock = [System.IO.File]::Open((Join-Path $processRoot 'launcher.lock'),
    [System.IO.FileMode]::OpenOrCreate, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
$unresolvedIntents = @()
foreach ($intentFile in Get-ChildItem -LiteralPath $processRoot -Filter '*.intent.json') {
    $existingIntent = Get-Content -LiteralPath $intentFile.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
    $matchingReceipt = $intentFile.FullName.Replace('.intent.json', '.launch.json')
    if ($existingIntent.configuration_sha256 -eq $configurationHash -and -not (Test-Path -LiteralPath $matchingReceipt)) {
        $unresolvedIntents += $intentFile.FullName
    }
}
if ($Mode -eq 'Start' -and $unresolvedIntents.Count -gt 0) {
    throw 'An earlier launch has no PID receipt. Inspect its intent and logs before another start.'
}
$active = @()
if (Test-Path -LiteralPath $processRoot) {
    foreach ($receiptPath in Get-ChildItem -LiteralPath $processRoot -Filter '*.launch.json') {
        $receipt = Get-Content -LiteralPath $receiptPath.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($receipt.configuration_sha256 -ne $configurationHash) { continue }
        $process = Get-Process -Id $receipt.process_id -ErrorAction SilentlyContinue
        if ($null -ne $process -and $process.StartTime.ToUniversalTime().ToString('o') -eq $receipt.process_started_at) {
            $active += $receipt
        }
    }
}

if ($Mode -eq 'Status') {
    $statusRaw = & wsl.exe @wslArguments status --config $linuxConfiguration
    if ($LASTEXITCODE -ne 0) { throw 'Pipeline status validation failed.' }
    $status = ($statusRaw -join "`n") | ConvertFrom-Json
    $progress = Get-Content -LiteralPath $progressPath -Raw -Encoding UTF8 | ConvertFrom-Json
    [ordered]@{
        process_running = ($active.Count -gt 0)
        process_ids = @($active | ForEach-Object { $_.process_id })
        unresolved_launch_intents = $unresolvedIntents
        pipeline_status = $status.status
        last_stage = $status.last_event.stage
        updated_at = $progress.updated_at
        training = $progress.training
        evaluation = $progress.evaluation
        completed_pairs = $progress.completed_pairs
        full_cohort_delta_percentage_points = $progress.full_cohort_delta_percentage_points
    } | ConvertTo-Json -Depth 8
    exit 0
}

if ($active.Count -gt 0) {
    Write-Output ('Pipeline already running; process IDs: ' + (($active | ForEach-Object { $_.process_id }) -join ', '))
    exit 0
}

$launchArguments = @($wslArguments) + @('run', '--config', $linuxConfiguration)
# These frozen machine paths contain no spaces or quotes. Refuse ambiguous
# Start-Process argument serialization instead of building a shell command.
foreach ($argument in $launchArguments) {
    if ($argument -match '[\s"]') { throw 'A frozen launcher argument requires unsupported quoting.' }
}
$stamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmss.fffffffZ')
$stdoutPath = Join-Path $processRoot ($stamp + '.stdout.log')
$stderrPath = Join-Path $processRoot ($stamp + '.stderr.log')
$intentPath = Join-Path $processRoot ($stamp + '.intent.json')
$receiptPath = Join-Path $processRoot ($stamp + '.launch.json')
$intent = [ordered]@{
    schema = 'skhynix/architecture-background-launch/1.0'
    configuration_path = $configurationPath
    configuration_sha256 = $configurationHash
    launcher_sha256 = (Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash.ToLowerInvariant()
    started_at = [DateTime]::UtcNow.ToString('o')
    stdout_path = $stdoutPath
    stderr_path = $stderrPath
    automatic_outcome_retries = $false
}
$intent | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $intentPath -Encoding UTF8
$jobProcess = Start-Process -FilePath (Get-Command wsl.exe).Source -ArgumentList $launchArguments `
    -WindowStyle Hidden -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath -PassThru
$receipt = [ordered]@{}
foreach ($key in $intent.Keys) { $receipt[$key] = $intent[$key] }
$receipt.process_id = $jobProcess.Id
$receipt.process_started_at = $jobProcess.StartTime.ToUniversalTime().ToString('o')
$receipt | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $receiptPath -Encoding UTF8
$receipt | ConvertTo-Json -Depth 6
} finally {
    if ($null -ne $launcherLock) { $launcherLock.Dispose() }
}
