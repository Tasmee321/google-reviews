@echo off
echo ============================================
echo   GBP Poster — Starting...
echo ============================================
echo.

cd /d "%~dp0"

:: Check accounts.json
if not exist "accounts.json" (
    echo ERROR: accounts.json nahi mili!
    echo accounts.json banao aur apna Gmail daalo
    pause
    exit /b 1
)

:: Check targets.json
if not exist "targets.json" (
    echo ERROR: targets.json nahi mili!
    echo targets.json banao aur business details daalo
    pause
    exit /b 1
)

echo Accounts aur targets found. Starting poster...
echo.
python poster.py

echo.
echo ============================================
echo   Session khatam. Log check karo: logs\
echo ============================================
pause
