@echo off
setlocal

set "CVAT_DIR=%~dp0..\cvat"
set "DOCKER_DESKTOP=C:\Program Files\Docker\Docker\Docker Desktop.exe"

if not exist "%CVAT_DIR%\docker-compose.yml" (
    echo CVAT was not found at "%CVAT_DIR%".
    goto :error
)

where docker >nul 2>&1
if errorlevel 1 (
    echo Docker CLI was not found. Install Docker Desktop first.
    goto :error
)

docker info >nul 2>&1
if not errorlevel 1 goto :docker_ready

if not exist "%DOCKER_DESKTOP%" (
    echo Docker Desktop was not found at "%DOCKER_DESKTOP%".
    goto :error
)
echo Starting Docker Desktop...
powershell -NoProfile -Command "Start-Process -FilePath '%DOCKER_DESKTOP%' -WindowStyle Hidden"
if errorlevel 1 goto :error
set /a WAIT_COUNT=0
:wait_docker
docker info >nul 2>&1
if not errorlevel 1 goto :docker_ready
set /a WAIT_COUNT+=1
if %WAIT_COUNT% GEQ 60 (
    echo Docker Desktop did not become ready within 2 minutes.
    goto :error
)
timeout /t 2 /nobreak >nul
goto :wait_docker

:docker_ready
pushd "%CVAT_DIR%" || goto :error
echo Starting CVAT...
docker compose up -d
if errorlevel 1 (
    popd
    goto :error
)

set /a WAIT_COUNT=0
:wait_cvat
docker exec cvat_server python manage.py health_check >nul 2>&1
if not errorlevel 1 goto :cvat_ready
set /a WAIT_COUNT+=1
if %WAIT_COUNT% GEQ 60 (
    echo CVAT did not become healthy within 2 minutes.
    popd
    goto :error
)
timeout /t 2 /nobreak >nul
goto :wait_cvat

:cvat_ready
popd
echo CVAT is ready at http://localhost:8080
if not defined CVAT_NO_BROWSER start "" "http://localhost:8080"
exit /b 0

:error
echo CVAT could not be started.
pause
exit /b 1
