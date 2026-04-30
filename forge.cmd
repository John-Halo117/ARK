@echo off
setlocal

set "ROOT_DIR=%~dp0"
set "ROOT_ARG=%ROOT_DIR:~0,-1%"
set "FORGE_PORT=4765"
set "FORGE_URL=http://127.0.0.1:%FORGE_PORT%/"

if /I "%~1"=="--desktop-server" goto desktop_server
if "%~1"=="" goto launch_desktop
goto run

:launch_desktop
call :resolve_python
if errorlevel 1 exit /b 1

call :stop_desktop_listener

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
  "$python = '%PYTHON_BIN%';" ^
  "$script = '%ROOT_DIR%ark-core\\scripts\\ai\\forge.py';" ^
  "$args = @($script, '--repo-root', '%ROOT_ARG%', '--desktop', '--no-browser', '--desktop-port', '%FORGE_PORT%');" ^
  "Start-Process -WindowStyle Hidden -FilePath $python -ArgumentList $args | Out-Null"

set /a ATTEMPT=0
:wait_for_forge
set /a ATTEMPT+=1
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ProgressPreference = 'SilentlyContinue';" ^
  "$url = '%FORGE_URL%api/state';" ^
  "try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 1 -Uri $url | Out-Null; exit 0 } catch { exit 1 }"
if not errorlevel 1 (
  start "" "%FORGE_URL%"
  exit /b 0
)

if %ATTEMPT% GEQ 40 goto desktop_failed
timeout /t 1 /nobreak >nul
goto wait_for_forge

:desktop_failed
echo Forge started but the browser app did not become ready at %FORGE_URL%.
echo If Ollama is not running yet, that is okay. Forge should still open a runtime screen once the UI server is up.
echo Retry in a few seconds, or run: "%ROOT_DIR%forge.cmd --check"
exit /b 1

:stop_desktop_listener
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":%FORGE_PORT% .*LISTENING"') do (
  taskkill /PID %%P /F >nul 2>nul
)
exit /b 0

:desktop_server
call :resolve_python
if errorlevel 1 exit /b 1
"%PYTHON_BIN%" "%ROOT_DIR%ark-core\scripts\ai\forge.py" --repo-root "%ROOT_ARG%" --desktop --no-browser --desktop-port %FORGE_PORT%
exit /b %errorlevel%

:run
call :resolve_python
if errorlevel 1 exit /b 1
"%PYTHON_BIN%" "%ROOT_DIR%ark-core\scripts\ai\forge.py" --repo-root "%ROOT_ARG%" %*
exit /b %errorlevel%

:resolve_python
set "PYTHON_BIN=%ROOT_DIR%ark-core\.venv\Scripts\python.exe"
if exist "%PYTHON_BIN%" exit /b 0

set "PYTHON_BIN=%ROOT_DIR%..\Home_Sys\Jarvis\ARK\ark\ark-core\.venv\Scripts\python.exe"
if exist "%PYTHON_BIN%" exit /b 0

where py >nul 2>nul
if not errorlevel 1 (
  for /f "usebackq delims=" %%I in (`py -3 -c "import sys; print(sys.executable)" 2^>nul`) do (
    set "PYTHON_BIN=%%I"
  )
  if defined PYTHON_BIN if exist "%PYTHON_BIN%" exit /b 0
)

where python >nul 2>nul
if not errorlevel 1 (
  for /f "usebackq delims=" %%I in (`where python 2^>nul`) do (
    if not defined PYTHON_BIN set "PYTHON_BIN=%%I"
  )
  if defined PYTHON_BIN if exist "%PYTHON_BIN%" exit /b 0
)

where python3 >nul 2>nul
if not errorlevel 1 (
  for /f "usebackq delims=" %%I in (`where python3 2^>nul`) do (
    if not defined PYTHON_BIN set "PYTHON_BIN=%%I"
  )
  if defined PYTHON_BIN if exist "%PYTHON_BIN%" exit /b 0
)

if defined PYTHON_BIN (
  exit /b 0
)

echo Forge could not find a usable Python interpreter.
exit /b 1
