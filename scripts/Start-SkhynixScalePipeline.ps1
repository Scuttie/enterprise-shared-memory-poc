param(
    [ValidateSet('Start', 'Status')]
    [string]$Mode = 'Status',
    [ValidatePattern('^architecture_002_pipeline_v[0-9]+\.json$')]
    [string]$ConfigurationName = 'architecture_002_pipeline_v2.json'
)

$ErrorActionPreference = 'Stop'
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$activationPath = Join-Path $repositoryRoot 'artifacts\skhynix_v1\architecture_scale_001\active-controller.json'
if (Test-Path -LiteralPath $activationPath) {
    $activation = Get-Content -LiteralPath $activationPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not $PSBoundParameters.ContainsKey('ConfigurationName')) {
        $ConfigurationName = $activation.configuration_name
    }
    if ($Mode -eq 'Start' -and $ConfigurationName -ne $activation.configuration_name) { throw 'This scale controller was superseded before launch; use the active configuration.' }
}
$configurationPath = Join-Path $repositoryRoot ('configs\skhynix_v1\' + $ConfigurationName)
$configuration = Get-Content -LiteralPath $configurationPath -Raw -Encoding UTF8 | ConvertFrom-Json
$configurationHash = (Get-FileHash -LiteralPath $configurationPath -Algorithm SHA256).Hash.ToLowerInvariant()

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

$null = Get-VerifiedReference $configuration.pipeline_source_reference
$trainingPath = Get-VerifiedReference $configuration.training_experiment_reference
$training = Get-Content -LiteralPath $trainingPath -Raw -Encoding UTF8 | ConvertFrom-Json
$progressRoot = Convert-CMountToWindowsPath $configuration.progress_root
$processRoot = Join-Path $progressRoot 'processes'
$null = New-Item -ItemType Directory -Path $processRoot -Force
$launcherLock = $null
try {
    $launcherLock = [System.IO.File]::Open((Join-Path $processRoot 'launcher.lock'),
        [System.IO.FileMode]::OpenOrCreate, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
    $active = @()
    foreach ($receiptPath in Get-ChildItem -LiteralPath $processRoot -Filter '*.launch.json') {
        $receipt = Get-Content -LiteralPath $receiptPath.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
        $process = Get-Process -Id $receipt.process_id -ErrorAction SilentlyContinue
        if ($null -ne $process -and $process.StartTime.ToUniversalTime().ToString('o') -eq $receipt.process_started_at) {
            $active += $receipt
        }
    }
    $unresolved = @()
    foreach ($intentFile in Get-ChildItem -LiteralPath $processRoot -Filter '*.intent.json') {
        if (-not (Test-Path -LiteralPath $intentFile.FullName.Replace('.intent.json', '.launch.json'))) {
            $unresolved += $intentFile.FullName
        }
    }
    if ($Mode -eq 'Status') {
        $progressPath = Join-Path $progressRoot 'progress.json'
        $progress = if (Test-Path -LiteralPath $progressPath) {
            Get-Content -LiteralPath $progressPath -Raw -Encoding UTF8 | ConvertFrom-Json
        } else { $null }
        [ordered]@{process_running = ($active.Count -gt 0); process_ids = @($active | ForEach-Object { $_.process_id });
            unresolved_launch_intents = $unresolved; configuration = $ConfigurationName; progress = $progress} |
            ConvertTo-Json -Depth 14
        exit 0
    }
    if ($active.Count -gt 0) {
        Write-Output ('Scale pipeline already running; process IDs: ' + (($active | ForEach-Object { $_.process_id }) -join ', '))
        exit 0
    }
    if ($unresolved.Count -gt 0) { throw 'A previous launch intent has no receipt; inspect it before another launch.' }
    $linuxConfiguration = '/mnt/c/' + $configurationPath.Substring(3).Replace('\', '/')
    $launchArguments = @('-d', 'TriMemRunner2404', '-u', 'trimem-runner', '--', 'env',
        'PYTHONDONTWRITEBYTECODE=1', 'LD_LIBRARY_PATH=/opt/trimem-runner-cache/work-ci/_tool/Python/3.11.10/x64/lib',
        'HF_HUB_OFFLINE=1', 'TRANSFORMERS_OFFLINE=1',
        ('PYTHONPATH=' + $training.source_root + '/scripts:' + $training.source_root + '/src'),
        '/opt/trimem-rehearsals/e932-preflight/venv/bin/python', '-P', $configuration.pipeline_source_reference.path,
        'run', '--config', $linuxConfiguration)
    foreach ($argument in $launchArguments) {
        if ($argument -match '[\s"]') { throw 'A launcher argument requires unsupported quoting.' }
    }
    $stamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmss.fffffffZ')
    $prefix = Join-Path $processRoot $stamp
    $intent = [ordered]@{schema = 'skhynix/scale-background-launch/1.0'; configuration_sha256 = $configurationHash;
        configuration_path = $configurationPath; requested_at = [DateTime]::UtcNow.ToString('o');
        launcher_sha256 = (Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash.ToLowerInvariant();
        stdout_path = ($prefix + '.stdout.log'); stderr_path = ($prefix + '.stderr.log');
        reasoning_effort = 'high'; model = 'gpt-6-astra'; native_outcome_retries = $false}
    [System.IO.File]::WriteAllText(($prefix + '.intent.json'), ($intent | ConvertTo-Json -Depth 6), [System.Text.UTF8Encoding]::new($false))
    $process = Start-Process -FilePath 'wsl.exe' -ArgumentList $launchArguments -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput ($prefix + '.stdout.log') -RedirectStandardError ($prefix + '.stderr.log')
    $receipt = [ordered]@{schema = $intent.schema; configuration_sha256 = $configurationHash;
        configuration_path = $configurationPath; process_id = $process.Id;
        process_started_at = $process.StartTime.ToUniversalTime().ToString('o');
        intent_path = ($prefix + '.intent.json'); stdout_path = $intent.stdout_path; stderr_path = $intent.stderr_path}
    [System.IO.File]::WriteAllText(($prefix + '.launch.json'), ($receipt | ConvertTo-Json -Depth 6), [System.Text.UTF8Encoding]::new($false))
    $receipt | ConvertTo-Json -Depth 6
}
finally {
    if ($null -ne $launcherLock) { $launcherLock.Dispose() }
}
