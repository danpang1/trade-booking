@echo off
REM ============================================================
REM  8041 MTD PnL split (Dinari vs Native) - daily breakdown.
REM  Self-contained: refreshes the trade DB first, then prints
REM  ONLY the MTD split-by-days table (inception .. COB).
REM    Phase 1: pull + fold + save ALL trades into the DB
REM    Phase 2: mtd_split.py --date <COB>  (the MTD table)
REM  Usage:
REM    Double-click                 -> prompts for the COB date
REM    run_mtd_split.bat 2026-06-28          (date as arg)
REM ============================================================
setlocal
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"

REM --- locate Python (full path first, then PATH fallback) ---
set "PY=C:\Users\peter\AppData\Local\Programs\Python\Python311\python.exe"
if not exist "%PY%" set "PY=python"

cd /d "C:\Users\peter\OneDrive\Desktop\Claude\middle-office-tools\8041-pnl"

set "COB=%~1"
if "%COB%"=="" set /p COB="Enter COB date (YYYY-MM-DD): "
if "%COB%"=="" (
    echo No date entered. Exiting.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  Refreshing trade DB for COB %COB% (pull + fold + save)...
echo ============================================================
"%PY%" pnl_8041_daily.py --date %COB% --ingest-only
if errorlevel 1 (
    echo.
    echo [DB refresh] FAILED - aborting before MTD split.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  MTD PnL split (Dinari vs Native) - daily breakdown - COB %COB%
echo ============================================================
echo.
"%PY%" mtd_split.py --date %COB%

echo.
echo ============================================================
echo  Done.  Press any key to close.
pause >nul
endlocal
