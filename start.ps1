# ============================================================
# Polymarket Wallet Tracker Terminal - PowerShell Launcher
# ============================================================
# Usage:
#   PowerShell: .\start.ps1
#   If blocked:  powershell -ExecutionPolicy Bypass -File start.ps1
# ============================================================

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"

# --- cd to script directory ---
Set-Location $PSScriptRoot

Write-Host ""
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host " Polymarket Wallet Tracker Terminal - Setup"   -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host ""

# --- Check Python ---
try {
    $pyVer = python --version 2>&1
    Write-Host "[OK] $pyVer" -ForegroundColor Green
} catch {
    Write-Host "[ERROR] python が見つかりません。" -ForegroundColor Red
    Write-Host "Python 3.11+ をインストールしてください:"
    Write-Host "  https://www.python.org/downloads/"
    Write-Host '  インストール時に「Add Python to PATH」にチェックを入れてください。'
    Read-Host "Enter で終了"
    exit 1
}

# --- Check required files ---
if (-not (Test-Path "main.py")) {
    Write-Host "[ERROR] main.py が見つかりません。プロジェクトルートで実行してください。" -ForegroundColor Red
    Read-Host "Enter で終了"
    exit 1
}

# --- Create .env if missing ---
if (-not (Test-Path ".env")) {
    if (Test-Path ".env.example") {
        Copy-Item ".env.example" ".env"
        Write-Host "[SETUP] .env.example → .env を作成しました" -ForegroundColor Yellow
    } else {
        Write-Host "[WARN] .env.example が見つかりません。デフォルト設定で起動します。" -ForegroundColor Yellow
    }
} else {
    Write-Host "[OK] .env 読み込み" -ForegroundColor Green
}

# --- Check wallets_seed.csv ---
if (-not (Test-Path "wallets_seed.csv")) {
    Write-Host "[WARN] wallets_seed.csv が見つかりません。監視ウォレット0件で起動します。" -ForegroundColor Yellow
}

# --- Create venv if missing ---
if (-not (Test-Path "venv\Scripts\Activate.ps1")) {
    Write-Host ""
    Write-Host "[SETUP] 仮想環境を作成中..." -ForegroundColor Yellow
    python -m venv venv
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] 仮想環境の作成に失敗しました。" -ForegroundColor Red
        Read-Host "Enter で終了"
        exit 1
    }
    Write-Host "[OK] 仮想環境を作成しました" -ForegroundColor Green

    & "venv\Scripts\Activate.ps1"

    Write-Host "[SETUP] 依存パッケージをインストール中..." -ForegroundColor Yellow
    pip install --upgrade pip 2>$null | Out-Null
    pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] パッケージのインストールに失敗しました。" -ForegroundColor Red
        Read-Host "Enter で終了"
        exit 1
    }
    Write-Host "[OK] インストール完了" -ForegroundColor Green
} else {
    & "venv\Scripts\Activate.ps1"
    Write-Host "[OK] 仮想環境をアクティベート" -ForegroundColor Green
}

# --- Launch ---
Write-Host ""
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host " Starting Polymarket Wallet Tracker..."       -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host " Ctrl+C で停止できます" -ForegroundColor DarkGray
Write-Host ""

python main.py

Write-Host ""
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host " Tracker が終了しました"                      -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan
Read-Host "Enter で終了"
