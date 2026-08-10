@echo off
REM Double-click this to run the whole workflow. No terminal typing.
REM
REM Change SCALE below if you switch OOTP's rating scale.
setlocal
set "SCALE=1 to 100"

cd /d "%~dp0"
title OOTP Scout

echo ================================================================
echo  OOTP SCOUT
echo ================================================================
echo.
echo  Before continuing, in OOTP:
echo    1. Open the player list you want
echo    2. Switch the view to Batting Ratings (or Pitching Ratings)
echo    3. Report -^> Write report to disk
echo.
pause
echo.

python -m ootp_scout prepare --latest --scale "%SCALE%"
if errorlevel 1 goto failed

echo.
echo ================================================================
echo  The ratings are on your clipboard. Now, in your browser:
echo.
echo    1. Open the projections page (link printed above)
echo    2. Set RATINGS SCALE to "%SCALE%"
echo    3. Click BATCH INPUT, press Ctrl+V, click SUBMIT
echo    4. Click DOWNLOAD CSV
echo ================================================================
echo.
pause
echo.

python -m ootp_scout flag latest latest --out targets.xlsx
if errorlevel 1 goto failed

echo.
echo Opening targets.xlsx...
start "" "targets.xlsx"
echo.
echo Done. Green rows are the strongest flags.
pause
exit /b 0

:failed
echo.
echo ================================================================
echo  Something went wrong - the error is printed above.
echo.
echo  Most common causes:
echo    - The OOTP view was not switched to a Ratings view
echo    - The projections CSV was never downloaded
echo    - targets.xlsx is still open in Excel (close it and retry)
echo ================================================================
echo.
pause
exit /b 1
