@echo off
setlocal EnableExtensions

cd /d "%~dp0"
set "ROOT=%CD%"
set "BACKEND=%ROOT%\backend"
set "HOST=127.0.0.1"
set "PORT=8000"
set "URL=http://%HOST%:%PORT%/"

echo [INFO] Project root: %ROOT%
echo [INFO] Backend dir  : %BACKEND%

where python3 >nul 2>nul
if errorlevel 1 goto :no_python

echo [INFO] Using Python: python3
python3 -c "import sys; print(sys.version); print(sys.executable)"
if errorlevel 1 goto :python_failed

python3 -m pip --version >nul 2>nul
if errorlevel 1 goto :no_pip

if not exist "%BACKEND%\app.py" goto :missing_app

if not exist "%BACKEND%\data\passages.json" goto :missing_passages

cd /d "%BACKEND%"
python3 -c "import app; print('app import ok')"
if errorlevel 1 goto :app_import_failed

python3 -c "import uvicorn" >nul 2>nul
if errorlevel 1 goto :install_deps

goto :check_port

:install_deps
echo.
echo [WARN] uvicorn not found. Installing requirements to user site-packages...
python3 -m pip install --user -r "%BACKEND%\requirements.txt"
if errorlevel 1 goto :deps_failed

goto :check_port

:check_port
set "INUSE="
for /f "tokens=1,2,3,4,5" %%a in ('netstat -ano ^| find ":%PORT%" ^| find "LISTENING" 2^>nul') do set "INUSE=%%e"
if defined INUSE goto :port_in_use

echo.
echo [INFO] Starting verraco on %URL%
start "" "%URL%"
python3 -m uvicorn app:app --host %HOST% --port %PORT%
goto :end

:no_python
echo.
echo [ERROR] python3 not found. Please install Python 3 and ensure python3 works in terminal.
pause
exit /b 1

:python_failed
echo.
echo [ERROR] python3 failed to run.
pause
exit /b 1

:no_pip
echo.
echo [ERROR] pip is not available for python3.
pause
exit /b 1

:missing_app
echo.
echo [ERROR] Missing backend\app.py
pause
exit /b 1

:missing_passages
echo.
echo [ERROR] Missing backend\data\passages.json
echo [ERROR] Run: python3 "%BACKEND%\scripts\import_pdf_to_json.py"
pause
exit /b 1

:app_import_failed
echo.
echo [ERROR] app.py import failed. Run this to see traceback:
echo         cd "%BACKEND%" ^&^& python3 -c "import app"
pause
exit /b 1

:deps_failed
echo.
echo [ERROR] Failed to install requirements.
pause
exit /b 1

:port_in_use
echo.
echo [ERROR] Port %PORT% is already in use (PID=%INUSE%).
echo [ERROR] Stop the other process or change PORT in run.bat.
pause
exit /b 1

:end
echo.
pause
exit /b 0
