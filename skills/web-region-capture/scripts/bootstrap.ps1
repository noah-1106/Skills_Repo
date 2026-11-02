# Thin Windows bootstrap; does not change execution policy or require Chrome.
$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $Root
$Python = if (Get-Command py -ErrorAction SilentlyContinue) { @('py', '-3') } else { @('python') }
& $Python[0] $Python[1..($Python.Length-1)] -c "import sys; assert sys.version_info >= (3, 11), 'Python 3.11+ required'"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$VenvPython = Join-Path $Root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $VenvPython)) { & $Python[0] $Python[1..($Python.Length-1)] -m venv (Join-Path $Root '.venv') }
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install --no-deps -r (Join-Path $Root 'requirements.txt')
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $Root 'runtime\ms-playwright'
New-Item -ItemType Directory -Force -Path $env:PLAYWRIGHT_BROWSERS_PATH, (Join-Path $Root 'runtime\tmp') | Out-Null
& $VenvPython -m playwright install chromium
if (-not (Test-Path -LiteralPath (Join-Path $Root 'config\local.json'))) { Copy-Item -LiteralPath (Join-Path $Root 'config\local.example.json') -Destination (Join-Path $Root 'config\local.json') }
& (Join-Path $Root 'scripts\doctor.ps1')
exit $LASTEXITCODE
