@echo off
REM ============================================================
REM Polymarket Wallet Tracker Terminal - Windows Launcher
REM ============================================================
REM Usage:
REM   - Double-click this file in Explorer
REM   - cmd.exe:    start.bat
REM   - PowerShell: cmd /c start.bat  OR  .\start.ps1
REM ============================================================

chcp 65001 >nul 2>&1
set PYTHONIOENCODING=utf-8

REM --- cd to the folder where this .bat lives ---
cd /d "%~dp0"

echo.
echo =============================================
echo  Polymarket Wallet Tracker Terminal - Setup
echo =============================================
echo.

REM --- Check Python ---
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] python が見つかりません。
    echo Python 3.11 以上をインストールしてください:
    echo   https://www.python.org/downloads/
    echo.
    echo インストール時に「Add Python to PATH」にチェックを入れてください。
    pause
    exit /b 1
)

REM --- Check required files ---
if not exist "main.py" (
    echo [ERROR] main.py が見つかりません。
    echo このバッチファイルはプロジェクトルートに配置してください。
    pause
    exit /b 1
)

if not exist "requirements.txt" (
    echo [ERROR] requirements.txt が見つかりません。
    pause
    exit /b 1
)

REM --- Create .env if missing ---
if not exist ".env" (
    if exist ".env.example" (
        echo [SETUP] .env.example から .env を作成します...
        copy /y ".env.example" ".env" >nul
        echo [OK] .env を作成しました。必要に応じて編集してください。
    ) else (
        echo [WARN] .env.example が見つかりません。デフォルト設定で起動します。
    )
) else (
    echo [OK] .env 読み込み
)

REM --- Check wallets_seed.csv ---
if not exist "wallets_seed.csv" (
    echo [WARN] wallets_seed.csv が見つかりません。
    echo 監視ウォレットが0件の状態で起動します。
)

REM --- Create venv if missing ---
if not exist "venv\Scripts\activate.bat" (
    echo.
    echo [SETUP] 仮想環境を作成中...
    python -m venv venv
    if errorlevel 1 (
        echo [ERROR] 仮想環境の作成に失敗しました。
        pause
        exit /b 1
    )
    echo [OK] 仮想環境を作成しました。

    call venv\Scripts\activate.bat

    echo [SETUP] 依存パッケージをインストール中...
    pip install --upgrade pip >nul 2>&1
    pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] パッケージのインストールに失敗しました。
        pause
        exit /b 1
    )
    echo [OK] インストール完了
) else (
    call venv\Scripts\activate.bat
    echo [OK] 仮想環境をアクティベート
)

REM --- Launch ---
echo.
echo =============================================
echo  Starting Polymarket Wallet Tracker...
echo =============================================
echo  Ctrl+C で停止できます
echo.
python main.py

echo.
echo =============================================
echo  Tracker が終了しました
echo =============================================
pause
