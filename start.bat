@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo Starting StarTrip...
docker compose up -d
if errorlevel 1 (
  echo.
  echo 启动失败：请先打开 Docker Desktop，再双击本文件。
  pause
  exit /b 1
)

echo.
echo 前端 / 后端: http://localhost:8000
echo 健康检查:    http://localhost:8000/health
echo Jaeger:      http://localhost:16686
echo.
timeout /t 4 >nul
start "" http://localhost:8000
