# remove_tasks.ps1 - タスクスケジューラから PolyTracker タスクを全削除する
#
# 使い方:
#   PowerShell を管理者として実行し:
#   cd C:\my-ai-project
#   .\remove_tasks.ps1

$ErrorActionPreference = "Stop"

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
Write-Host "=== PolyTracker タスク削除 ===" -ForegroundColor Cyan
Write-Host ""

$taskNames = @("PolyTracker-Watchdog", "PolyTracker-Monitor", "PolyTracker-DailyReport")
$removed = 0

foreach ($name in $taskNames) {
    $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    if ($task) {
        try {
            Unregister-ScheduledTask -TaskName $name -Confirm:$false
            Write-Host "  REMOVED: $name" -ForegroundColor Green
            $removed++
        } catch {
            Write-Host "  FAIL: $name - $_" -ForegroundColor Red
        }
    } else {
        Write-Host "  SKIP: $name (未登録)" -ForegroundColor Gray
    }
}

Write-Host ""
Write-Host "削除完了: $removed 件" -ForegroundColor Cyan
Write-Host ""
Write-Host "再登録するには: .\setup_tasks.ps1" -ForegroundColor Gray
Write-Host ""
