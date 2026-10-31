@echo off
setlocal
cd /d "%~dp0"
title Tasmee - Local Dashboard
where python >nul 2>&1
if errorlevel 1 (
    echo Python was not found. Install Python and enable Add Python to PATH.
    pause
    exit /b 1
)
python -c "import dotenv" >nul 2>&1
if errorlevel 1 (
    echo Dependencies are missing. Run install.bat first.
    pause
    exit /b 1
)
python "%~dp0check_localhost.py"
if errorlevel 2 (
    pause
    exit /b 2
)
if not errorlevel 1 (
    echo No duplicate server was started.
    pause
    exit /b 0
)
echo Starting localhost and the dedicated Firefox dashboard...
call "%~dp0run_firefox.bat"
exit /b %errorlevel%
