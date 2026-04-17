@echo off
REM Polymarket Tracker - メインスケジューラを起動するバッチ
REM タスクスケジューラ登録用

cd /d "%~dp0"
python main.py
