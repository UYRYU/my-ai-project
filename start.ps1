[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"

if (-not (Test-Path ".env")) {
    Write-Host ".env が見つかりません。.env.example からコピーします..."
    Copy-Item ".env.example" ".env"
}

if (-not (Test-Path "venv")) {
    Write-Host "仮想環境を作成中..."
    python -m venv venv
    & "venv\Scripts\Activate.ps1"
    pip install -r requirements.txt
} else {
    & "venv\Scripts\Activate.ps1"
}

Write-Host ""
Write-Host "=== Polymarket Wallet Tracker Terminal ==="
Write-Host ""
python main.py
