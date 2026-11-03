@echo off
setlocal
cd /d "%~dp0"
echo Tasmee Personal Reviews - Install
python -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" >nul 2>&1
if errorlevel 1 (
    echo Python 3.11 or newer is required. Install it from https://python.org/downloads/
    echo Select "Add Python to PATH" during installation.
    pause
    exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
    python -m venv .venv
    if errorlevel 1 (
        echo Could not create the local Python environment.
        pause
        exit /b 1
    )
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo Installation failed. Check your internet connection and the error above.
    pause
    exit /b 1
)
echo.
".venv\Scripts\python.exe" check_setup.py --initialize --install-browser
if errorlevel 1 (
    pause
    exit /b 1
)
echo Installed. run.bat defaults to the dedicated Firefox extension workflow.
echo Install the Mozilla-signed Tasmee 1.0.7 XPI separately; this installer does not sign add-ons.
echo Open run.bat to start your personal dashboard.
pause
exit /b 0
