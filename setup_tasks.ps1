# setup_tasks.ps1 - Windows タスクスケジューラに自動化タスクを登録する
#
# 使い方:
#   PowerShell を管理者として実行し:
#   cd C:\my-ai-project
#   .\setup_tasks.ps1
#
# 登録されるタスク:
#   1. PolyTracker-Watchdog   : PC起動時に watchdog.py を自動起動
#   2. PolyTracker-Monitor    : 毎日9:00にmonitor.py を実行（レポート+アラート）
#   3. PolyTracker-DailyReport: 毎日21:00にreport.py --v2-only --daily を実行

$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonExe = Join-Path $ProjectDir "venv\Scripts\python.exe"

# venvのpythonが見つからない場合はシステムのpythonを使用
if (-not (Test-Path $PythonExe)) {
    $PythonExe = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $PythonExe) {
        Write-Host "[ERROR] Python が見つかりません。" -ForegroundColor Red
        exit 1
    }
}

Write-Host ""
Write-Host "=== Polymarket Tracker - タスクスケジューラ セットアップ ===" -ForegroundColor Cyan
Write-Host "Python: $PythonExe" -ForegroundColor Gray
Write-Host "Project: $ProjectDir" -ForegroundColor Gray
Write-Host ""

# --- タスク1: Watchdog (PC起動時) ---
Write-Host "[1/3] PolyTracker-Watchdog (PC起動時に自動起動)..." -ForegroundColor Yellow

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
    -RestartCount 3

try {
    Unregister-ScheduledTask -TaskName "PolyTracker-Watchdog" -Confirm:$false -ErrorAction SilentlyContinue
    Register-ScheduledTask `
        -TaskName "PolyTracker-Watchdog" `
        -Action $WatchdogAction `
        -Trigger $WatchdogTrigger `
        -Settings $WatchdogSettings `
        -Description "Polymarket Tracker を自動起動・再起動する" | Out-Null
    Write-Host "  DONE: PolyTracker-Watchdog 登録完了" -ForegroundColor Green
} catch {
    Write-Host "  SKIP: 管理者権限が必要です。管理者として再実行してください。" -ForegroundColor Red
    Write-Host "  エラー: $_" -ForegroundColor Gray
}

# --- タスク2: Monitor (毎日9:00) ---
Write-Host "[2/3] PolyTracker-Monitor (毎日 09:00)..." -ForegroundColor Yellow

$MonitorAction = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "monitor.py" `
    -WorkingDirectory $ProjectDir

$MonitorTrigger = New-ScheduledTaskTrigger -Daily -At "09:00"
$MonitorSettings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable

try {
    Unregister-ScheduledTask -TaskName "PolyTracker-Monitor" -Confirm:$false -ErrorAction SilentlyContinue
    Register-ScheduledTask `
        -TaskName "PolyTracker-Monitor" `
        -Action $MonitorAction `
        -Trigger $MonitorTrigger `
        -Settings $MonitorSettings `
        -Description "日次レポート保存 + アラートチェック" | Out-Null
    Write-Host "  DONE: PolyTracker-Monitor 登録完了" -ForegroundColor Green
} catch {
    Write-Host "  SKIP: 管理者権限が必要です。" -ForegroundColor Red
}

# --- タスク3: DailyReport (毎日21:00) ---
Write-Host "[3/3] PolyTracker-DailyReport (毎日 21:00)..." -ForegroundColor Yellow

$ReportAction = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "report.py --v2-only --daily" `
    -WorkingDirectory $ProjectDir

$ReportTrigger = New-ScheduledTaskTrigger -Daily -At "21:00"
$ReportSettings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable

try {
    Unregister-ScheduledTask -TaskName "PolyTracker-DailyReport" -Confirm:$false -ErrorAction SilentlyContinue
    Register-ScheduledTask `
        -TaskName "PolyTracker-DailyReport" `
        -Action $ReportAction `
        -Trigger $ReportTrigger `
        -Settings $ReportSettings `
        -Description "v2レポートを reports/ に自動保存" | Out-Null
    Write-Host "  DONE: PolyTracker-DailyReport 登録完了" -ForegroundColor Green
} catch {
    Write-Host "  SKIP: 管理者権限が必要です。" -ForegroundColor Red
}

Write-Host ""
Write-Host "=== セットアップ完了 ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "登録されたタスク:" -ForegroundColor White
Write-Host "  1. PolyTracker-Watchdog    : ログオン時に watchdog.py 起動" -ForegroundColor Gray
Write-Host "  2. PolyTracker-Monitor     : 毎日 09:00 にアラート + レポート" -ForegroundColor Gray
Write-Host "  3. PolyTracker-DailyReport : 毎日 21:00 にレポート保存" -ForegroundColor Gray
Write-Host ""
Write-Host "確認: Get-ScheduledTask -TaskName 'PolyTracker-*'" -ForegroundColor Gray
Write-Host "削除: Unregister-ScheduledTask -TaskName 'PolyTracker-Watchdog'" -ForegroundColor Gray
Write-Host ""

# 手動実行の場合の案内
Write-Host "--- 手動で今すぐ実行する場合 ---" -ForegroundColor Yellow
Write-Host "  python watchdog.py          # トラッカー起動（自動再起動付き）" -ForegroundColor White
Write-Host "  python monitor.py           # アラートチェック + レポート保存" -ForegroundColor White
Write-Host "  python monitor.py --loop 600  # 10分間隔でモニタリング" -ForegroundColor White
