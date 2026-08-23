# Company acceptance check (Windows PowerShell). Mirrors scripts/company_acceptance_check.sh.
# Fails (exit 1) on any failed step; writes reports/company_acceptance_result.json.
$ErrorActionPreference = "Continue"
$root = Split-Path (Split-Path $PSCommandPath -Parent) -Parent
Set-Location $root
$py = if ($env:PYTHON) { $env:PYTHON } else { "python" }
New-Item -ItemType Directory -Force -Path reports | Out-Null
$fail = $false

Write-Host ">> 0. tool availability"
& $py --version; if ($LASTEXITCODE -ne 0) { $fail = $true }

Write-Host ">> 1. bootstrap"
& $py -m pip install -q -e ".[dev]" pytest pyyaml 2>$null
if ($LASTEXITCODE -ne 0) { & $py -m pip install -q -e . pytest pyyaml 2>$null }

Write-Host ">> 2. test"
$testOut = & $py -m pytest -q tests/unit/test_experience_compiler.py tests/unit/test_experience_schema_sql.py tests/unit/test_rule_router_v1.py tests/unit/test_agentic_search.py tests/unit/test_outcome_governance.py tests/unit/test_mcp_adapters.py tests/integration/test_company_demo.py 2>&1
$testRc = $LASTEXITCODE; if ($testRc -ne 0) { $fail = $true }
$testCount = ([regex]::Match(($testOut -join " "), '(\d+) passed')).Groups[1].Value
$testPassed = ($testRc -eq 0)

Write-Host ">> 3. offline demo"
$demoOut = & $py scripts/demo_company_handoff.py --offline 2>&1
$demoPassed = ($demoOut -match "DEMO_PASS: true").Count -gt 0
if (-not $demoPassed) { $fail = $true }

Write-Host ">> 4. docs-check"
& $py scripts/check_docs_consistency.py; $docsRc = $LASTEXITCODE; if ($docsRc -ne 0) { $fail = $true }
& $py scripts/render_project_status.py --check; if ($LASTEXITCODE -ne 0) { $fail = $true }
$docsPassed = ($docsRc -eq 0)

Write-Host ">> 5. package"
& $py -m pip install -q build 2>$null
& $py -m build 2>$null; $pkgRc = $LASTEXITCODE; if ($pkgRc -ne 0) { $fail = $true }
$pkgPassed = ($pkgRc -eq 0)

Write-Host ">> 6. release-check"
& $py scripts/make_handoff_manifest.py --check; $manRc = $LASTEXITCODE; if ($manRc -ne 0) { $fail = $true }
$manOk = ($manRc -eq 0)

Write-Host ">> 7. secret scan"
$scan = (Select-String -Path src\*,docs\*,configs\*,examples\*,scripts\* -Pattern 'sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|BEGIN [A-Z ]*PRIVATE KEY' -ErrorAction SilentlyContinue | Where-Object { $_ -notmatch 'example|placeholder|<' }).Count
$scanClean = ($scan -eq 0); if (-not $scanClean) { $fail = $true }

Write-Host ">> 8. write result json"
$overall = (-not $fail)
& $py scripts/_acceptance_result.py "$testPassed" "$testCount" "$demoPassed" "$docsPassed" "$pkgPassed" "$manOk" "$scanClean" "$overall"

Write-Host ""
if (-not $fail) { Write-Host "COMPANY_ACCEPTANCE_PASS: true"; Write-Host "DEMO_PASS: true"; exit 0 }
else { Write-Host "COMPANY_ACCEPTANCE_PASS: false"; exit 1 }
