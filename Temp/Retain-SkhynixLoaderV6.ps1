$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$path = Join-Path $repo 'artifacts\skhynix_v1\architecture_scale_001\official-harness-loader-v6.json'
if (Test-Path -LiteralPath $path) { throw 'Loader evidence already exists.' }
$payload = & wsl.exe -d TriMemRunner2404 -u trimem-runner -- env PYTHONDONTWRITEBYTECODE=1 `
    LD_LIBRARY_PATH=/opt/trimem-runner-cache/work-ci/_tool/Python/3.11.10/x64/lib `
    HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 `
    PYTHONPATH=/mnt/c/Users/jewon/AppData/Local/Temp/skhynix-architecture-scale-001-source-v6/scripts:/mnt/c/Users/jewon/AppData/Local/Temp/skhynix-architecture-scale-001-source-v6/src `
    /opt/trimem-rehearsals/e932-preflight/venv/bin/python `
    /mnt/c/Users/jewon/esm-r23-d115-writer/Temp/emit_skhynix_loader_v6.py
if ($LASTEXITCODE -ne 0) { throw 'Frozen loader API validation failed.' }
$raw = [Convert]::FromBase64String(($payload -join '').Trim())
$value = [Text.Encoding]::UTF8.GetString($raw) | ConvertFrom-Json
if ($value.status -ne 'PASS') { throw 'Loader API did not return PASS.' }
$stream = [System.IO.File]::Open($path, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
try { $stream.Write($raw, 0, $raw.Length); $stream.Flush($true) } finally { $stream.Dispose() }
[ordered]@{path=$path; sha256=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant(); status=$value.status} | ConvertTo-Json
