@echo off
setlocal
cd /d "%~dp0"
set REVIEW_BROWSER=chrome
set REVIEW_MODE=extension
echo Optional Chrome extension mode. This uses your existing Chrome session.
echo Use run.bat for the default dedicated Firefox workflow instead.
echo Extension 1.0.7 is required for UK-IP checks before Google actions.
call "%~dp0start_localhost.bat"
exit /b %errorlevel%
