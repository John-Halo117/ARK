@echo off
setlocal

set "ROOT_DIR=%~dp0"
set "ROOT_ARG=%ROOT_DIR:~0,-1%"
set "FORGE_PORT=4765"
set "FORGE_URL=http://127.0.0.1:%FORGE_PORT%/"
set "WINDOWS_DIR=%SystemRoot%"
if not defined WINDOWS_DIR set "WINDOWS_DIR=C:\Windows"
set "NETSTAT=%WINDOWS_DIR%\System32\netstat.exe"
set "TASKKILL=%WINDOWS_DIR%\System32\taskkill.exe"
set "TIMEOUT=%WINDOWS_DIR%\System32\timeout.exe"

if /I "%~1"=="--desktop-server" goto desktop_server
if /I "%~1"=="--status" goto status
if /I "%~1"=="--stop" goto stop_desktop
if /I "%~1"=="--cleanup" goto cleanup
if "%~1"=="" goto launch_desktop
goto run

:launch_desktop
call :resolve_python
if errorlevel 1 exit /b 1

call :stop_desktop_listener

start "Forge" /min "%PYTHON_BIN%" "%ROOT_DIR%ark-core\scripts\ai\forge.py" --repo-root "%ROOT_ARG%" --desktop --no-browser --desktop-port %FORGE_PORT%

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
if exist "%TIMEOUT%" (
  "%TIMEOUT%" /t 1 /nobreak >nul
) else (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Start-Sleep -Seconds 1" >nul 2>nul
)
goto wait_for_forge

:desktop_failed
echo Forge started but the browser app did not become ready at %FORGE_URL%.
echo If Ollama is not running yet, that is okay. Forge should still open a runtime screen once the UI server is up.
echo Retry in a few seconds, or run: "%ROOT_DIR%forge.cmd --check"
exit /b 1

:stop_desktop_listener
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
  "$port = %FORGE_PORT%;" ^
  "$pids = @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique);" ^
  "$forge = @(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'forge.py' -and $_.CommandLine -match '--desktop-port %FORGE_PORT%' } | Select-Object -ExpandProperty ProcessId);" ^
  "foreach ($procId in @($pids + $forge | Select-Object -Unique)) { Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue }" >nul 2>nul
exit /b 0

:status
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
  "$url = '%FORGE_URL%api/state';" ^
  "try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 1 -Uri $url | Out-Null; Write-Host 'Forge is running at %FORGE_URL%'; exit 0 } catch { Write-Host 'Forge is not running.'; exit 1 }"
exit /b %errorlevel%

:stop_desktop
call :stop_desktop_listener
echo Stopped Forge browser app if it was running.
exit /b 0

:cleanup
call :stop_desktop_listener
echo Cleaned Forge desktop listener on %FORGE_PORT%.
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
set "PYTHON_BIN="

set "PYTHON_BIN=%LocalAppData%\Programs\Python\Python313\python.exe"
if exist "%PYTHON_BIN%" exit /b 0
set "PYTHON_BIN="

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
    if not defined PYTHON_BIN if exist "%%I" set "PYTHON_BIN=%%I"
  )
  if defined PYTHON_BIN if exist "%PYTHON_BIN%" exit /b 0
  set "PYTHON_BIN="
)

where python3 >nul 2>nul
if not errorlevel 1 (
  for /f "usebackq delims=" %%I in (`where python3 2^>nul`) do (
    if not defined PYTHON_BIN if exist "%%I" set "PYTHON_BIN=%%I"
  )
  if defined PYTHON_BIN if exist "%PYTHON_BIN%" exit /b 0
  set "PYTHON_BIN="
)

echo Forge could not find a usable Python interpreter.
exit /b 1
