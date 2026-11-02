$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$VenvPython = Join-Path $Root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $VenvPython)) { Write-Error 'Run scripts/bootstrap.ps1 first'; exit 1 }
$env:PYTHONPATH = Join-Path $Root 'src'
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $Root 'runtime\ms-playwright'
$env:TMPDIR = Join-Path $Root 'runtime	mp'
New-Item -ItemType Directory -Force -Path $env:TMPDIR | Out-Null
& $VenvPython -m web_region_capture --root $Root doctor @args
exit $LASTEXITCODE
