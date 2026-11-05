@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"

set "LOGDIR=%~dp0logs"
if not exist "%LOGDIR%" mkdir "%LOGDIR%" >nul 2>&1
set "LOG=%LOGDIR%\start.log"
> "%LOG%" echo [%date% %time%] start.bat 已被触发

echo ============================================
echo   StarTrip 一键启动（本地开发模式）
echo ============================================
echo.
call :log "日志文件：%LOG%"
echo.

REM ========== 1. Docker ==========
docker info >nul 2>&1
if errorlevel 1 (
  call :log "[1/5] Docker 未运行，正在尝试启动 Docker Desktop..."
  if exist "C:\Program Files\Docker\Docker\Docker Desktop.exe" (
    start "" "C:\Program Files\Docker\Docker\Docker Desktop.exe"
  ) else (
    call :log "      未找到 Docker Desktop，请先安装或手动启动后再试。"
    goto :fail
  )
  call :wait_docker
  if errorlevel 1 (
    call :log "      Docker Desktop 在 5 分钟内仍未就绪。"
    call :log "      请手动打开 Docker Desktop，等它显示 Running 后重新双击 start.bat。"
    goto :fail
  )
) else (
  call :log "[1/5] Docker 已运行"
)

REM ========== 2. .env ==========
if not exist ".env" (
  if exist ".env.example" (
    copy /y ".env.example" ".env" >nul
    call :log "[2/5] 已从 .env.example 创建 .env，请确认里面填了 API Key"
  ) else (
    call :log "[2/5] 未找到 .env / .env.example"
  )
) else (
  call :log "[2/5] .env 已存在"
)

REM ========== 3. PostgreSQL + Jaeger ==========
call :log "[3/5] 启动 PostgreSQL + Jaeger..."
docker compose up -d postgres jaeger
if errorlevel 1 (
  call :log "      首次启动失败，5 秒后自动重试一次..."
  timeout /t 5 /nobreak >nul
  docker compose up -d postgres jaeger
  if errorlevel 1 (
    call :log "      PostgreSQL / Jaeger 启动失败，请查看 Docker Desktop。"
    goto :fail
  )
)
call :wait_pg
if errorlevel 1 (
  call :log "      PostgreSQL 未在 90 秒内就绪，最后 20 行容器日志："
  docker logs --tail 20 startrip-postgres-1 2>&1
  goto :fail
)
call :log "      PostgreSQL 已就绪"

REM ========== 4. Redis ==========
call :port_busy 6379
if errorlevel 1 (
  call :log "[4/5] 本机 6379 没有 Redis，启动 compose redis..."
  docker compose up -d redis
  if errorlevel 1 (
    call :log "      Redis 启动失败，请查看 Docker Desktop。"
    goto :fail
  )
) else (
  call :log "[4/5] 检测到本机 Redis（Memurai），直接复用"
)

REM ========== 5. Backend ==========
call :port_busy 8000
if not errorlevel 1 (
  call :health_ok
  if not errorlevel 1 (
    call :log "[5/5] 8000 端口上 StarTrip 后端已在运行，直接打开浏览器"
    goto :open
  )
  for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r /c:"LISTENING" ^| findstr ":8000 "') do set "PORT_PID=%%p"
  call :log "[5/5] 8000 端口被占用（PID=!PORT_PID!），但它没有正常响应 /health。"
  powershell -NoProfile -Command "$p = Get-CimInstance Win32_Process -Filter 'ProcessId=!PORT_PID!' -ErrorAction SilentlyContinue; if ($p -and $p.CommandLine -match 'uvicorn') { exit 0 } else { exit 1 }" >nul 2>&1
  if not errorlevel 1 (
    call :log "      占用者是旧的 StarTrip 后端进程，正在结束它..."
    taskkill /PID !PORT_PID! /F >nul 2>&1
    timeout /t 2 /nobreak >nul
  ) else (
    call :log "      占用者不是 StarTrip 后端，请先运行 stop.bat 或手动结束该 PID 后重试。"
    goto :fail
  )
)

call :log "[5/5] 启动后端..."
start "StarTrip Backend" "%~dp0run-backend.bat"
call :wait_health
if errorlevel 1 (
  call :log "      后端未在 90 秒内就绪。请查看弹出的 StarTrip Backend 窗口里的报错。"
  goto :fail
)
call :log "      后端健康检查通过"
goto :open

REM ========== 子过程 ==========
:open
echo.
call :log "启动完成：http://127.0.0.1:8000"
call :log "健康检查：http://127.0.0.1:8000/health"
call :log "Jaeger：  http://127.0.0.1:16686"
start "" "http://127.0.0.1:8000"
echo.
echo 本窗口可以直接关闭，后端在单独的 StarTrip Backend 窗口里继续运行。
timeout /t 8 /nobreak >nul
exit /b 0

:fail
echo.
call :log "启动失败，完整输出见日志：%LOG%"
echo.
echo 按任意键关闭本窗口。
pause >nul
exit /b 1

:log
echo %~1
>>"%LOG%" echo %~1
exit /b 0

:port_busy
powershell -NoProfile -Command "if (Get-NetTCPConnection -LocalPort %~1 -State Listen -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }" >nul 2>&1
exit /b %errorlevel%

:health_ok
powershell -NoProfile -Command "try { $r = Invoke-RestMethod 'http://127.0.0.1:8000/health' -TimeoutSec 3; if ($r.status -eq 'ok') { exit 0 } } catch {}; exit 1" >nul 2>&1
exit /b %errorlevel%

:wait_docker
for /l %%i in (1,1,60) do (
  set /a "WAITED=%%i*5"
  set /a "TICK=%%i %% 6"
  if !TICK!==0 call :log "      等待 Docker 就绪... 已等 !WAITED! 秒"
  docker info >nul 2>&1
  if not errorlevel 1 (
    call :log "      Docker 已就绪，用时约 !WAITED! 秒"
    exit /b 0
  )
  timeout /t 5 /nobreak >nul
)
exit /b 1

:wait_pg
for /l %%i in (1,1,30) do (
  for /f "delims=" %%s in ('docker inspect --format "{{.State.Health.Status}}" startrip-postgres-1 2^>nul') do (
    if "%%s"=="healthy" exit /b 0
  )
  timeout /t 3 /nobreak >nul
)
exit /b 1

:wait_health
for /l %%i in (1,1,45) do (
  call :health_ok
  if not errorlevel 1 exit /b 0
  timeout /t 2 /nobreak >nul
)
exit /b 1
