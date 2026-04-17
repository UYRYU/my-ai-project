# Polymarket Tracker - タスクスケジューラ自動登録スクリプト
# 管理者権限のPowerShellで実行: .\register_tasks.ps1

$ProjectDir = $PSScriptRoot
$MainBat = Join-Path $ProjectDir "run_main.bat"
$WatchdogBat = Join-Path $ProjectDir "run_watchdog.bat"

Write-Host "Polymarket Tracker タスクスケジューラ登録" -ForegroundColor Cyan
Write-Host "プロジェクト: $ProjectDir" -ForegroundColor Gray

# ===== 1. PolyTracker-Main (起動時に自動開始) =====
$TaskName1 = "PolyTracker-Main"
Write-Host "`n[1/2] $TaskName1 を登録..." -ForegroundColor Yellow

# 既存を削除
schtasks /Delete /TN $TaskName1 /F 2>$null

# ログオン時に自動起動
$Trigger1 = New-ScheduledTaskTrigger -AtLogOn
$Action1 = New-ScheduledTaskAction -Execute $MainBat -WorkingDirectory $ProjectDir
$Settings1 = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd -ExecutionTimeLimit (New-TimeSpan -Days 0)
Register-ScheduledTask -TaskName $TaskName1 `
    -Trigger $Trigger1 `
    -Action $Action1 `
    -Settings $Settings1 `
    -Description "Polymarket tracker main scheduler (auto-start on login)" `
    -Force | Out-Null

Write-Host "  → $TaskName1 登録完了 (ログオン時に自動起動)" -ForegroundColor Green

# ===== 2. PolyTracker-Watchdog (5分おき) =====
$TaskName2 = "PolyTracker-Watchdog"
Write-Host "`n[2/2] $TaskName2 を登録..." -ForegroundColor Yellow

schtasks /Delete /TN $TaskName2 /F 2>$null

# 5分おきに実行
$Trigger2 = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 5)
$Action2 = New-ScheduledTaskAction -Execute $WatchdogBat -WorkingDirectory $ProjectDir
$Settings2 = New-ScheduledTaskSettingsSet -StartWhenAvailable
Register-ScheduledTask -TaskName $TaskName2 `
    -Trigger $Trigger2 `
    -Action $Action2 `
    -Settings $Settings2 `
    -Description "Checks if PolyTracker main is running, restarts if dead" `
    -Force | Out-Null

Write-Host "  → $TaskName2 登録完了 (5分おきに生存確認)" -ForegroundColor Green

Write-Host "`n=========================================" -ForegroundColor Cyan
Write-Host " 登録完了" -ForegroundColor Green
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "確認: タスクスケジューラを開いて以下を確認してください" -ForegroundColor Gray
Write-Host "  - PolyTracker-Main    (ログオン時に自動起動)" -ForegroundColor Gray
Write-Host "  - PolyTracker-Watchdog (5分おきに生存確認)" -ForegroundColor Gray
Write-Host ""
Write-Host "今すぐmain.pyを起動するには:" -ForegroundColor Yellow
Write-Host "  schtasks /Run /TN PolyTracker-Main" -ForegroundColor White
Write-Host ""
Write-Host "削除する場合:" -ForegroundColor Yellow
Write-Host "  schtasks /Delete /TN PolyTracker-Main /F" -ForegroundColor White
Write-Host "  schtasks /Delete /TN PolyTracker-Watchdog /F" -ForegroundColor White
