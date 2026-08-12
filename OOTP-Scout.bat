@echo off
REM Double-click this to run the workflow. It returns to the menu after each
REM action instead of closing.
REM
REM Everything you record accumulates in ootp_scout.db. Spreadsheets are made
REM on demand from that database rather than one per run.
REM
REM The rating scale is detected from the export, so this works whether OOTP
REM is set to 20-80 or 1-100. Match the site's RATINGS SCALE dropdown to the
REM scale it reports.
setlocal
cd /d "%~dp0"
title OOTP Scout

echo ================================================================
echo  OOTP SCOUT
echo ================================================================

set "blanks=0"

:MENU
echo.
echo ----------------------------------------------------------------
echo   ADD TO THE DATABASE
echo     [1]  Full run        export -^> calculator -^> database
echo     [2]  Prepare only    read the export, copy the paste block
echo     [3]  Record only     you have already downloaded the CSV
echo.
echo   USE THE DATABASE
echo     [4]  Look up a player
echo     [5]  League report   spreadsheet of one league
echo     [6]  Prospect report same, graded against POT
echo     [7]  What is stored
echo     [8]  List leagues
echo.
echo     [Q]  Quit
echo ----------------------------------------------------------------
set "pick="
set /p "pick=Choose: "

if /i "%pick%"=="1" goto FULL
if /i "%pick%"=="2" goto PREPARE_ONLY
if /i "%pick%"=="3" goto RECORD
if /i "%pick%"=="4" goto LOOKUP
if /i "%pick%"=="5" goto LEAGUE
if /i "%pick%"=="6" goto PROSPECTS
if /i "%pick%"=="7" goto STATS
if /i "%pick%"=="8" goto LEAGUES
if /i "%pick%"=="q" goto QUIT

REM A stray Enter should just redraw the menu, but if input has gone away
REM entirely - piped in, or the console closed under us - looping on an
REM unreadable prompt would spin forever. Give up after a few in a row.
REM Written without a parenthesised block on purpose: %blanks% inside one
REM expands when the block is parsed, so the increment would never be seen.
if not "%pick%"=="" goto BADPICK
set /a blanks+=1
if %blanks% GEQ 3 goto QUIT
goto MENU

:BADPICK
set "blanks=0"
echo.
echo   "%pick%" is not one of the options.
goto MENU


:FULL
echo.
echo  In OOTP, before continuing:
echo    1. Open the player list you want
echo    2. Switch the view to Batting Ratings or Pitching Ratings
echo    3. Report -^> Write report to disk
echo.
pause
echo.
python -m ootp_scout prepare --latest
if errorlevel 1 goto PROBLEM
echo.
echo  The ratings are on your clipboard. Now, in your browser:
echo    1. Open the projections page linked above
echo    2. Set RATINGS SCALE to the scale reported above
echo    3. Click BATCH INPUT, press Ctrl+V, click SUBMIT
echo    4. Click DOWNLOAD CSV
echo.
pause
echo.
goto RECORD


:PREPARE_ONLY
echo.
python -m ootp_scout prepare --latest
if errorlevel 1 goto PROBLEM
goto DONE


:RECORD
echo.
python -m ootp_scout flag latest latest --limit 15
if errorlevel 1 goto PROBLEM
goto DONE


:LOOKUP
echo.
set "who="
set /p "who=Player name (or part of one): "
if "%who%"=="" goto MENU
echo.
python -m ootp_scout lookup "%who%"
goto DONE


:LEAGUES
echo.
python -m ootp_scout leagues
goto DONE


:LEAGUE
echo.
python -m ootp_scout leagues
echo.
set "lg="
set /p "lg=League (blank if you only have one): "
echo.
if "%lg%"=="" python -m ootp_scout report --mode current --out league.xlsx
if not "%lg%"=="" python -m ootp_scout report --mode current --league "%lg%" --out league.xlsx
if errorlevel 1 goto PROBLEM
echo.
echo Opening league.xlsx...
start "" "league.xlsx"
goto DONE


:PROSPECTS
echo.
python -m ootp_scout leagues
echo.
set "lg="
set /p "lg=League (blank if you only have one): "
echo.
if "%lg%"=="" python -m ootp_scout report --mode potential --out prospects.xlsx
if not "%lg%"=="" python -m ootp_scout report --mode potential --league "%lg%" --out prospects.xlsx
if errorlevel 1 goto PROBLEM
echo.
echo Opening prospects.xlsx...
start "" "prospects.xlsx"
goto DONE


:STATS
echo.
python -m ootp_scout stats
goto DONE


:DONE
echo.
pause
goto MENU


:PROBLEM
echo.
echo ----------------------------------------------------------------
echo  That did not work - the error is printed above.
echo.
echo  Most common causes:
echo    - The OOTP view was not switched to a Ratings view
echo    - The projections CSV was never downloaded
echo    - The report and the CSV are from different pools
echo    - The spreadsheet is still open in Excel
echo ----------------------------------------------------------------
pause
goto MENU


:QUIT
endlocal
exit /b 0
