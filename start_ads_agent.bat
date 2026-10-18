@echo off
setlocal
cd /d "%~dp0"

set PORT=8010
set HOST=127.0.0.1
set PYTHON_EXE=%~dp0.venv\Scripts\python.exe

if not exist "%PYTHON_EXE%" (
  set PYTHON_EXE=D:\anaconda\python.exe
)

if not exist "%PYTHON_EXE%" (
  set PYTHON_EXE=python
)

echo Stopping existing server on port %PORT%...
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\stop_local_server.ps1 -Port %PORT% >nul 2>nul

echo Starting ads agent at http://%HOST%:%PORT%/
echo Logs: .uvicorn-%PORT%.out.log and .uvicorn-%PORT%.err.log
echo Using Python: %PYTHON_EXE%

start "ads-agent-%PORT%" /min cmd.exe /c ""%PYTHON_EXE%" -X utf8 -m uvicorn backend.main:app --host %HOST% --port %PORT% > .uvicorn-%PORT%.out.log 2> .uvicorn-%PORT%.err.log"

timeout /t 4 /nobreak >nul
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8010/api/config' -UseBasicParsing -TimeoutSec 10; Write-Host ('Started OK: ' + $r.StatusCode) } catch { Write-Host ('Health check failed: ' + $_.Exception.Message); if (Test-Path '.uvicorn-8010.err.log') { Get-Content '.uvicorn-8010.err.log' -Tail 30 } }"

echo.
echo Open http://127.0.0.1:%PORT%/
pause
