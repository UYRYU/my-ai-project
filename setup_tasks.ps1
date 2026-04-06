# setup_tasks.ps1 - Windows タスクスケジューラに自動化タスクを登録する
#
# 使い方:
#   PowerShell を管理者として実行し:
#   cd C:\my-ai-project
#   .\setup_tasks.ps1
#
# 登録されるタスク:
#   1. PolyTracker-Watchdog    : ログオン時に watchdog.py を自動起動
#   2. PolyTracker-Monitor     : ログオン時に起動 + 10分間隔でリピート実行
#   3. PolyTracker-DailyReport : 毎日 21:00 に report.py --v2-only --daily を実行

$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonExe = Join-Path $ProjectDir "venv\Scripts\python.exe"

# venvのpythonが見つからない場合はシステムのpythonを使用
if (-not (Test-Path $PythonExe)) {
    $PythonExe = Join-Path $ProjectDir "venv\Scripts\pythonw.exe"
}
if (-not (Test-Path $PythonExe)) {
    $PythonExe = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $PythonExe) {
        Write-Host "[ERROR] Python が見つかりません。venv を作成するか、Python を PATH に追加してください。" -ForegroundColor Red
        exit 1
    }
}

# 管理者権限チェック
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)
if (-not $isAdmin) {
    Write-Host ""
    Write-Host "[ERROR] 管理者権限が必要です。" -ForegroundColor Red
    Write-Host "  PowerShell を右クリック → 「管理者として実行」で再度実行してください。" -ForegroundColor Yellow
    Write-Host ""
    exit 1
}

Write-Host ""
Write-Host "=== Polymarket Tracker - タスクスケジューラ セットアップ ===" -ForegroundColor Cyan
Write-Host "Python : $PythonExe" -ForegroundColor Gray
Write-Host "Project: $ProjectDir" -ForegroundColor Gray
Write-Host ""

$successCount = 0
$totalTasks = 3

# --- タスク1: Watchdog (ログオン時) ---
Write-Host "[1/$totalTasks] PolyTracker-Watchdog (ログオン時に自動起動)..." -ForegroundColor Yellow

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
        -Description "Polymarket Tracker の watchdog.py を自動起動。クラッシュ時は自動再起動。" | Out-Null
    Write-Host "  OK: PolyTracker-Watchdog 登録完了" -ForegroundColor Green
    $successCount++
} catch {
    Write-Host "  FAIL: PolyTracker-Watchdog 登録失敗" -ForegroundColor Red
    Write-Host "  エラー: $_" -ForegroundColor Gray
}

# --- タスク2: Monitor (ログオン時 + 10分リピート) ---
Write-Host "[2/$totalTasks] PolyTracker-Monitor (ログオン時 + 10分間隔リピート)..." -ForegroundColor Yellow

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
        -Description "10分ごとにアラートチェック + レポート保存（ログオン時開始）" | Out-Null
    Write-Host "  OK: PolyTracker-Monitor 登録完了" -ForegroundColor Green
    $successCount++
} catch {
    Write-Host "  FAIL: PolyTracker-Monitor 登録失敗" -ForegroundColor Red
    Write-Host "  エラー: $_" -ForegroundColor Gray
}

# --- タスク3: DailyReport (毎日 21:00) ---
Write-Host "[3/$totalTasks] PolyTracker-DailyReport (毎日 21:00)..." -ForegroundColor Yellow

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
        -Description "毎日21:00にv2レポートを reports/ に自動保存" | Out-Null
    Write-Host "  OK: PolyTracker-DailyReport 登録完了" -ForegroundColor Green
    $successCount++
} catch {
    Write-Host "  FAIL: PolyTracker-DailyReport 登録失敗" -ForegroundColor Red
    Write-Host "  エラー: $_" -ForegroundColor Gray
}

# --- 結果サマリー ---
Write-Host ""
if ($successCount -eq $totalTasks) {
    Write-Host "=== セットアップ完了 ($successCount/$totalTasks タスク登録) ===" -ForegroundColor Cyan
} else {
    Write-Host "=== セットアップ完了 ($successCount/$totalTasks タスク登録) ===" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "登録されたタスク:" -ForegroundColor White
Write-Host "  1. PolyTracker-Watchdog    : ログオン時に watchdog.py 起動（自動再起動付き）" -ForegroundColor Gray
Write-Host "  2. PolyTracker-Monitor     : ログオン時 + 10分間隔でアラート + レポート" -ForegroundColor Gray
Write-Host "  3. PolyTracker-DailyReport : 毎日 21:00 にレポート保存" -ForegroundColor Gray
Write-Host ""
Write-Host "確認コマンド:" -ForegroundColor White
Write-Host "  Get-ScheduledTask -TaskName 'PolyTracker-*'" -ForegroundColor Gray
Write-Host "  Get-ScheduledTask -TaskName 'PolyTracker-*' | Get-ScheduledTaskInfo" -ForegroundColor Gray
Write-Host ""
Write-Host "削除:" -ForegroundColor White
Write-Host "  .\remove_tasks.ps1" -ForegroundColor Gray
Write-Host ""
Write-Host "手動起動:" -ForegroundColor White
Write-Host "  run_all.bat          # watchdog + monitor を同時起動" -ForegroundColor Gray
Write-Host "  python watchdog.py   # トラッカーのみ起動" -ForegroundColor Gray
Write-Host "  python monitor.py    # アラートチェック1回" -ForegroundColor Gray
Write-Host ""
