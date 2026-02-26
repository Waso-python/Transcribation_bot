param(
    [switch]$AsSystem
)

$ErrorActionPreference = "Stop"

$TaskName = "TranscribationServer"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ScriptPath = Join-Path $ProjectRoot "scripts\start_server.ps1"

if (-not (Test-Path $ScriptPath)) {
    throw "Start script not found: $ScriptPath"
}

$Action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$ScriptPath`""

$Trigger = New-ScheduledTaskTrigger -AtStartup
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

if ($AsSystem) {
    $Principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $Action `
        -Trigger $Trigger `
        -Principal $Principal `
        -Settings $Settings `
        -Force | Out-Null
}
else {
    $CurrentUser = "$env:USERDOMAIN\$env:USERNAME"
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $Action `
        -Trigger $Trigger `
        -User $CurrentUser `
        -RunLevel Highest `
        -Settings $Settings `
        -Force | Out-Null
}

Start-ScheduledTask -TaskName $TaskName
Get-ScheduledTask -TaskName $TaskName | Get-ScheduledTaskInfo
