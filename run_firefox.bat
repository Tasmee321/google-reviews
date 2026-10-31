@echo off
setlocal
cd /d "%~dp0"
python -c "import flask, dotenv, playwright" >nul 2>&1
if errorlevel 1 (
    echo Dependencies are missing. Run install.bat first.
    pause
    exit /b 1
)
python personal_browser.py --check
if errorlevel 1 (
    pause
    exit /b 1
)
python build_firefox_extension.py
if errorlevel 1 exit /b 1
set REVIEW_BROWSER=firefox
echo Starting with the dedicated permanent Firefox profile, not personal Chrome.
echo Keep your existing Avast VPN connected and its kill switch enabled before Google sign-in.
echo This launcher does not verify VPN protection or change your IP.
echo If this Firefox profile is already open, use its existing dashboard tab.
echo Close that dedicated Firefox window before restarting the launcher.
echo Keep this terminal open. Ctrl+C stops the local server.
python app.py
if errorlevel 1 pause
