@echo off
setlocal
cd /d "%~dp0"
set REVIEW_BROWSER=chrome
echo Optional legacy Chrome mode. This uses your existing Chrome session.
echo Use run.bat for the dedicated Firefox profile instead.
python app.py
if errorlevel 1 pause
