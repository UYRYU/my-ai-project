@echo off
REM ============================================================
REM run_all.bat - Watchdog + Monitor を同時起動する
REM ============================================================
REM Usage:
REM   ダブルクリック or コマンドプロンプトで run_all.bat
REM   停止: 各ウィンドウで Ctrl+C
REM ============================================================

chcp 65001 >nul 2>&1
set PYTHONIOENCODING=utf-8

REM --- cd to project root ---
cd /d "%~dp0"

REM --- Python チェック ---
if exist "venv\Scripts\python.exe" (
    set PYTHON=venv\Scripts\python.exe
) else (
    python --version >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] Python が見つかりません。
        pause
        exit /b 1
    )
    set PYTHON=python
)

REM --- .env チェック ---
if not exist ".env" (
    if exist ".env.example" (
        copy /y ".env.example" ".env" >nul
        echo [SETUP] .env を .env.example から作成しました。
    )
)

echo.
echo =============================================
echo  Polymarket Tracker - 全プロセス起動
echo =============================================
echo.
echo  1. Watchdog (新しいウィンドウで起動)
echo  2. Monitor  (このウィンドウで起動)
echo.
echo  停止: 各ウィンドウで Ctrl+C
echo =============================================
echo.

REM --- Watchdog を別ウィンドウで起動 ---
start "PolyTracker-Watchdog" cmd /k "%PYTHON% watchdog.py"

REM --- 少し待ってから Monitor をループ起動 ---
timeout /t 3 /nobreak >nul
echo [Monitor] 10分間隔でモニタリング開始...
%PYTHON% monitor.py --loop 600
