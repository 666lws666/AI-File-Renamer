@echo off
chcp 65001 >nul
set "XUXIA_ROOT=%~dp0"
cd /d "%XUXIA_ROOT%"
if exist ".venv\Scripts\python.exe" (
    call ".venv\Scripts\python.exe" -m src.main %*
) else (
    python -m src.main %*
)
pause
