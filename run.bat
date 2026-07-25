@echo off
chcp 65001 >nul
cd /d "D:\文件AI-AGENT"
call .venv\Scripts\python -m src.main
pause
