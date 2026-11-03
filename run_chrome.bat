@echo off
setlocal
cd /d "%~dp0"
set REVIEW_BROWSER=chrome
set REVIEW_MODE=extension
echo Optional legacy Chrome mode. This uses your existing Chrome session.
echo Use run.bat for the configured poster workflow instead.
call "%~dp0start_localhost.bat"
exit /b %errorlevel%
