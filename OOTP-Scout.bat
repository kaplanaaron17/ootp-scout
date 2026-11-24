@echo off
REM Double-click this to open the OOTP Scout window.
REM
REM pythonw runs it without a console, so only the window appears and this
REM prompt closes straight away. If pythonw is missing the console stays open
REM behind the window, which at least shows an error if one happens.
REM
REM The old numbered menu is OOTP-Scout-Menu.bat.
setlocal
cd /d "%~dp0"
where pythonw >nul 2>nul
if errorlevel 1 goto CONSOLE
start "" pythonw -m ootp_scout gui
exit /b 0

:CONSOLE
python -m ootp_scout gui
if errorlevel 1 pause
exit /b %errorlevel%
