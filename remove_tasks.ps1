# remove_tasks.ps1 - Remove all PolyTracker tasks from Task Scheduler
#
# Usage:
#   Run PowerShell as Administrator:
#   cd C:\my-ai-project
#   powershell -ExecutionPolicy Bypass -File remove_tasks.ps1

$ErrorActionPreference = "Stop"

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
Write-Host "=== PolyTracker - Remove Tasks ===" -ForegroundColor Cyan
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
        Write-Host "  SKIP: $name (not registered)" -ForegroundColor Gray
    }
}

Write-Host ""
Write-Host "Removed: $removed task(s)" -ForegroundColor Cyan
Write-Host ""
Write-Host "To re-register: powershell -ExecutionPolicy Bypass -File setup_tasks.ps1" -ForegroundColor Gray
Write-Host ""
