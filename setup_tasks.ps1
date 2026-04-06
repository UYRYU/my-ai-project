# setup_tasks.ps1 - Register PolyTracker tasks in Windows Task Scheduler
#
# Usage:
#   Run PowerShell as Administrator:
#   cd C:\my-ai-project
#   powershell -ExecutionPolicy Bypass -File setup_tasks.ps1
#
# Tasks:
#   1. PolyTracker-Watchdog    : At logon, auto-start watchdog.py
#   2. PolyTracker-Monitor     : At logon + repeat every 10 min
#   3. PolyTracker-DailyReport : Daily at 21:00

$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonExe = Join-Path $ProjectDir "venv\Scripts\python.exe"

# Fallback: try pythonw.exe, then system python
if (-not (Test-Path $PythonExe)) {
    $PythonExe = Join-Path $ProjectDir "venv\Scripts\pythonw.exe"
}
if (-not (Test-Path $PythonExe)) {
    $PythonExe = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $PythonExe) {
        Write-Host "[ERROR] Python not found. Create venv or add Python to PATH." -ForegroundColor Red
        exit 1
    }
}

# Admin check
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)
if (-not $isAdmin) {
    Write-Host ""
    Write-Host "[ERROR] Administrator privileges required." -ForegroundColor Red
    Write-Host "  Right-click PowerShell -> Run as Administrator" -ForegroundColor Yellow
    Write-Host ""
    exit 1
}

Write-Host ""
Write-Host "=== PolyTracker - Task Scheduler Setup ===" -ForegroundColor Cyan
Write-Host "Python : $PythonExe" -ForegroundColor Gray
Write-Host "Project: $ProjectDir" -ForegroundColor Gray
Write-Host ""

$successCount = 0
$totalTasks = 3

# --- Task 1: Watchdog (at logon) ---
Write-Host "[1/$totalTasks] PolyTracker-Watchdog (at logon)..." -ForegroundColor Yellow

$WatchdogAction = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "watchdog.py" `
    -WorkingDirectory $ProjectDir

$WatchdogTrigger = New-ScheduledTaskTrigger -AtLogon
$WatchdogSettings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartInterval (New-TimeSpan -Minutes 5) `
    -RestartCount 3 `
    -ExecutionTimeLimit (New-TimeSpan -Days 365)

try {
    Unregister-ScheduledTask -TaskName "PolyTracker-Watchdog" -Confirm:$false -ErrorAction SilentlyContinue
    Register-ScheduledTask `
        -TaskName "PolyTracker-Watchdog" `
        -Action $WatchdogAction `
        -Trigger $WatchdogTrigger `
        -Settings $WatchdogSettings `
        -Description "Auto-start watchdog.py at logon. Auto-restart on crash." | Out-Null
    Write-Host "  OK: PolyTracker-Watchdog registered" -ForegroundColor Green
    $successCount++
} catch {
    Write-Host "  FAIL: PolyTracker-Watchdog" -ForegroundColor Red
    Write-Host "  Error: $_" -ForegroundColor Gray
}

# --- Task 2: Monitor (at logon + repeat every 10 min) ---
Write-Host "[2/$totalTasks] PolyTracker-Monitor (at logon + 10min repeat)..." -ForegroundColor Yellow

$MonitorAction = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "monitor.py" `
    -WorkingDirectory $ProjectDir

$MonitorTrigger = New-ScheduledTaskTrigger -AtLogon
$MonitorTrigger.Repetition = (New-ScheduledTaskTrigger -Once -At "00:00" `
    -RepetitionInterval (New-TimeSpan -Minutes 10) `
    -RepetitionDuration ([TimeSpan]::MaxValue)).Repetition

$MonitorSettings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
    -MultipleInstances IgnoreNew

try {
    Unregister-ScheduledTask -TaskName "PolyTracker-Monitor" -Confirm:$false -ErrorAction SilentlyContinue
    Register-ScheduledTask `
        -TaskName "PolyTracker-Monitor" `
        -Action $MonitorAction `
        -Trigger $MonitorTrigger `
        -Settings $MonitorSettings `
        -Description "Alert check + report save every 10 min (starts at logon)" | Out-Null
    Write-Host "  OK: PolyTracker-Monitor registered" -ForegroundColor Green
    $successCount++
} catch {
    Write-Host "  FAIL: PolyTracker-Monitor" -ForegroundColor Red
    Write-Host "  Error: $_" -ForegroundColor Gray
}

# --- Task 3: DailyReport (daily at 21:00) ---
Write-Host "[3/$totalTasks] PolyTracker-DailyReport (daily 21:00)..." -ForegroundColor Yellow

$ReportAction = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "report.py --v2-only --daily" `
    -WorkingDirectory $ProjectDir

$ReportTrigger = New-ScheduledTaskTrigger -Daily -At "21:00"
$ReportSettings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5)

try {
    Unregister-ScheduledTask -TaskName "PolyTracker-DailyReport" -Confirm:$false -ErrorAction SilentlyContinue
    Register-ScheduledTask `
        -TaskName "PolyTracker-DailyReport" `
        -Action $ReportAction `
        -Trigger $ReportTrigger `
        -Settings $ReportSettings `
        -Description "Save v2 daily report to reports/ at 21:00" | Out-Null
    Write-Host "  OK: PolyTracker-DailyReport registered" -ForegroundColor Green
    $successCount++
} catch {
    Write-Host "  FAIL: PolyTracker-DailyReport" -ForegroundColor Red
    Write-Host "  Error: $_" -ForegroundColor Gray
}

# --- Summary ---
Write-Host ""
if ($successCount -eq $totalTasks) {
    Write-Host "=== Setup complete ($successCount/$totalTasks tasks registered) ===" -ForegroundColor Cyan
} else {
    Write-Host "=== Setup complete ($successCount/$totalTasks tasks registered) ===" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Registered tasks:" -ForegroundColor White
Write-Host "  1. PolyTracker-Watchdog    : at logon, auto-restart on crash" -ForegroundColor Gray
Write-Host "  2. PolyTracker-Monitor     : at logon + every 10 min alert check" -ForegroundColor Gray
Write-Host "  3. PolyTracker-DailyReport : daily 21:00 report save" -ForegroundColor Gray
Write-Host ""
Write-Host "Verify:" -ForegroundColor White
Write-Host "  Get-ScheduledTask -TaskName 'PolyTracker-*'" -ForegroundColor Gray
Write-Host ""
Write-Host "Remove all:" -ForegroundColor White
Write-Host "  powershell -ExecutionPolicy Bypass -File remove_tasks.ps1" -ForegroundColor Gray
Write-Host ""
Write-Host "Manual start:" -ForegroundColor White
Write-Host "  run_all.bat" -ForegroundColor Gray
Write-Host ""
