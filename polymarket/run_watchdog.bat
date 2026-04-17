@echo off
REM Polymarket Tracker - Watchdog (5分おきに実行してmain.pyの生存確認)

cd /d "%~dp0"
python watchdog.py
