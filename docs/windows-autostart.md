# Windows 11: Background Run + Auto Start

This guide shows how to run Transcribation Server in background and start it automatically when Windows boots.

## 1) One-time setup

Open PowerShell and run:

```powershell
cd C:\Users\waso\Transcribation_server
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .[dev]
copy .env.example .env
.\.venv\Scripts\python.exe -m alembic upgrade head
```

Edit `.env` and set production values (`API_KEYS`, `ASR_*`, Telegram settings if needed).

## 2) Create start script

Use ready script `scripts\start_server.ps1`:

```powershell
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
& $VenvPython -m uvicorn app.main:app --host 0.0.0.0 --port 8008 --app-dir src 2>&1 |
    ForEach-Object -MemberName ToString |
    Add-Content -Path $LogFile -Encoding UTF8
```

Notes:
- Use absolute paths.
- Do not use `--reload` for background/autostart mode.
- `$ErrorActionPreference` переключается на `Continue` перед запуском uvicorn, потому что Python пишет INFO-логи в stderr, а PowerShell в режиме `Stop` считает это терминирующей ошибкой.
- `ForEach-Object -MemberName ToString` конвертирует `ErrorRecord`-объекты PowerShell в чистые строки, убирая метаданные `NativeCommandError` из лога.

## 3) Option A (recommended): Task Scheduler

This runs at system boot, hidden, without open terminal window.

Run PowerShell as Administrator:

```powershell
cd C:\Users\waso\Transcribation_server
.\scripts\register_autostart_task.ps1
```

By default this registers task for the current user (recommended for project in `C:\Users\...` and local `.venv`).
Use `-AsSystem` only if project path and permissions are prepared for `SYSTEM`.

**Служба отключается при выходе?** По умолчанию задача выполняется только при входе пользователя. Чтобы она работала после выхода/блокировки, перерегистрируйте с флагом `-RunWhenLoggedOff` (потребуется ввод пароля Windows):

```powershell
.\scripts\register_autostart_task.ps1 -RunWhenLoggedOff
```

Manual equivalent:

```powershell
$TaskName = "TranscribationServer"
$ScriptPath = "C:\Users\waso\Transcribation_server\scripts\start_server.ps1"

$Action = New-ScheduledTaskAction `
  -Execute "powershell.exe" `
  -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$ScriptPath`""

$Trigger = New-ScheduledTaskTrigger -AtStartup
$Principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Principal $Principal -Settings $Settings
Start-ScheduledTask -TaskName $TaskName
```

Check status:

```powershell
Get-ScheduledTask -TaskName "TranscribationServer" | Get-ScheduledTaskInfo
```

## 4) Option B: Windows service via NSSM

Use this if you prefer classic service management.

1. Install NSSM (https://nssm.cc/download).
2. Run as Administrator:

```powershell
nssm install TranscribationServer "powershell.exe" "-NoProfile -ExecutionPolicy Bypass -File C:\Users\waso\Transcribation_server\scripts\start_server.ps1"
nssm set TranscribationServer AppDirectory "C:\Users\waso\Transcribation_server"
nssm set TranscribationServer Start SERVICE_AUTO_START
nssm start TranscribationServer
```

Check service:

```powershell
sc.exe query TranscribationServer
```

## 5) Health check

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8008/health/live"
Invoke-RestMethod -Uri "http://127.0.0.1:8008/health/ready"
```

Expected:

```json
{"status":"ok"}
{"status":"ready"}
```

## 6) Update / restart

After code changes:

```powershell
cd C:\Users\waso\Transcribation_server
.\.venv\Scripts\python.exe -m pip install -e .[dev]
.\.venv\Scripts\python.exe -m alembic upgrade head
```

Then restart:
- Task Scheduler: `Restart-ScheduledTask -TaskName "TranscribationServer"`
- NSSM service: `nssm restart TranscribationServer`
