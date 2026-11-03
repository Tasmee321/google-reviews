@echo off
setlocal
cd /d "%~dp0"
echo Tasmee Personal Reviews - Install
python --version >nul 2>&1
if errorlevel 1 (
    echo Python 3.11 or newer is required. Install it from https://python.org/downloads/
    echo Select "Add Python to PATH" during installation.
    pause
    exit /b 1
)
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo Installation failed. Check your internet connection and the error above.
    pause
    exit /b 1
)
echo.
echo Installed. run.bat uses your dedicated ordinary Firefox profile.
echo Open run.bat to start your personal dashboard.
pause
