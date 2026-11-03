@echo off
setlocal
cd /d "%~dp0"
set REVIEW_BROWSER=firefox
set REVIEW_MODE=extension
echo Starting with the dedicated permanent Firefox profile, not personal Chrome.
echo Keep your existing Avast VPN connected and its kill switch enabled before Google sign-in.
echo Signed Tasmee add-on 1.0.7 is required for browser UK-IP checks.
echo The launcher does not control Avast or change your IP.
echo If this Firefox profile is already open, use its existing dashboard tab.
echo Close that dedicated Firefox window before restarting the launcher.
echo Keep this terminal open. Ctrl+C stops the local server.
call "%~dp0start_localhost.bat"
exit /b %errorlevel%
