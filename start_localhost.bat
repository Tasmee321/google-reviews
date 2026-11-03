@echo off
setlocal
cd /d "%~dp0"
title Tasmee - Local Dashboard
set "PYTHON=python"
if exist ".venv\Scripts\python.exe" set "PYTHON=%~dp0.venv\Scripts\python.exe"
"%PYTHON%" -c "import flask, dotenv, playwright" >nul 2>&1
if errorlevel 1 (
    echo Dependencies are missing. Run install.bat first.
    pause
    exit /b 1
)
"%PYTHON%" "%~dp0check_localhost.py"
if errorlevel 2 (
    pause
    exit /b 2
)
if not errorlevel 1 (
    echo No duplicate server was started.
    pause
    exit /b 0
)
"%PYTHON%" "%~dp0check_setup.py"
if errorlevel 1 (
    pause
    exit /b 1
)
echo Starting the local dashboard using config.json...
echo Connect Avast VPN to a UK server and enable its kill switch before Google sign-in.
echo Keep this terminal open. Ctrl+C stops the server.
"%PYTHON%" "%~dp0app.py"
set "RESULT=%errorlevel%"
if not "%RESULT%"=="0" pause
exit /b %RESULT%
