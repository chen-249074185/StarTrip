@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo   StarTrip Backend
echo ============================================
echo.

.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000

echo.
echo 后端已退出。按任意键关闭窗口...
pause >nul
