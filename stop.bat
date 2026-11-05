@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ============================================
echo   StarTrip 停止
echo ============================================
echo.

echo [1/2] 停止本地后端（8000 端口）...
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do (
  taskkill /PID %%p /F >nul 2>&1
)

echo [2/2] 停止 Docker 服务...
docker compose down

echo.
echo StarTrip stopped.
pause
