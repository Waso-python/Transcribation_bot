$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$LogDir = Join-Path $ProjectRoot "logs"
$LogFile = Join-Path $LogDir "server.log"
$BootstrapLogFile = Join-Path $LogDir "bootstrap.log"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

if (-not (Test-Path $VenvPython)) {
    $msg = "Python from virtual environment not found: $VenvPython"
    Add-Content -Path $BootstrapLogFile -Value "$(Get-Date -Format s) failed: $msg"
    exit 1
}

Set-Location $ProjectRoot
Add-Content -Path $BootstrapLogFile -Value "$(Get-Date -Format s) starting uvicorn with $VenvPython"

$ErrorActionPreference = "Continue"
& $VenvPython -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --app-dir src 2>&1 |
    ForEach-Object -MemberName ToString |
    Add-Content -Path $LogFile -Encoding UTF8
$ExitCode = $LASTEXITCODE

Add-Content -Path $BootstrapLogFile -Value "$(Get-Date -Format s) uvicorn exited with code $ExitCode"
if ($ExitCode -ne 0) {
    exit $ExitCode
}
