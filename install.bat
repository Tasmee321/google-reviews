@echo off
echo ============================================
echo   GBP Poster — Auto Install (Windows)
echo ============================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python nahi mila!
    echo Python install karo: https://python.org/downloads
    echo Install karte waqt "Add Python to PATH" tick karna na bhoolo
    pause
    exit /b 1
)

echo [1/3] Python mila — installing dependencies...
python -m pip install --upgrade pip --quiet
pip install patchright python-dotenv --quiet

echo [2/3] Patchright Chromium install ho raha hai...
python -m patchright install chromium

echo [3/3] Folders bana raha hai...
if not exist "logs" mkdir logs
if not exist "profiles" mkdir profiles

echo.
echo ============================================
echo   Install Complete!
echo   Ab run.bat chalao
echo ============================================
pause
