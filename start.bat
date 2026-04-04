@echo off
chcp 65001 >nul 2>&1
set PYTHONIOENCODING=utf-8

if not exist ".env" (
    echo .env が見つかりません。.env.example からコピーします...
    copy .env.example .env
)

if not exist "venv" (
    echo 仮想環境を作成中...
    python -m venv venv
    call venv\Scripts\activate.bat
    pip install -r requirements.txt
) else (
    call venv\Scripts\activate.bat
)

echo.
echo === Polymarket Wallet Tracker Terminal ===
echo.
python main.py
pause
