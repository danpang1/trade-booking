@echo off
REM ============================================================
REM  8041 COB report — full pipeline (three phases):
REM    Phase 1: ingest ALL venue trades into trades_spot_avgcost
REM             (Binance UM, HL spot+perps, Bitstamp bookings,
REM              Robinhood chain, Native CSV+ClickHouse union)
REM    Phase 2: full-account recon (trade completeness check)
REM    Phase 3: ITD PnL + Day PnL + Position Buildup -> Excel
REM             ptf8041_itd_pnl_DDMMYYYY.xlsx
REM             marks from eod_pins_YYYY-MM-DD.csv when present
REM             (drop the user rate sheet there first), else feeds
REM  Usage:
REM    Double-click                   -> prompts for the COB date
REM    run_cob_report.bat 2026-07-03            (date as arg)
REM ============================================================
setlocal
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"

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

REM ptf8041_itd_pnl_DDMMYYYY.xlsx from YYYY-MM-DD
set "DD=%COB:~8,2%"
set "MM=%COB:~5,2%"
set "YYYY=%COB:~0,4%"
set "OUT=ptf8041_itd_pnl_%DD%%MM%%YYYY%.xlsx"

echo.
echo ============================================================
echo  PHASE 1/3 — ingest all venue trades (COB %COB%)
echo ============================================================
"%PY%" native_topup.py
if errorlevel 1 (
    echo Native top-up FAILED — aborting.
    pause
    exit /b 1
)
"%PY%" pnl_8041_daily.py --date %COB% --ingest-only
if errorlevel 1 (
    echo Venue ingest FAILED — aborting.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  PHASE 2/3 — full-account recon (completeness check)
echo ============================================================
"%PY%" account_recon.py %COB%
if errorlevel 1 echo (recon reported an error — review above; continuing)

echo.
echo ============================================================
echo  PHASE 3/3 — ITD PnL + Day PnL + Position Buildup -^> %OUT%
echo ============================================================
if exist "eod_pins_%COB%.csv" (
    echo using pinned marks eod_pins_%COB%.csv
    "%PY%" itd_pnl_export.py --date %COB% --pins eod_pins_%COB%.csv --out "%OUT%"
) else (
    echo WARNING: eod_pins_%COB%.csv not found — feed marks only.
    echo Save the user rate sheet as eod_pins_%COB%.csv and rerun for official marks.
    "%PY%" itd_pnl_export.py --date %COB% --out "%OUT%"
)

echo.
echo ============================================================
echo  Done. Report: %OUT%
echo  Reminder: add the IBKR day figure for %COB% to
echo  itd_pnl_export.py IBKR_DAYS + mtd_split.py MANUAL if not yet done.
echo ============================================================
pause >nul
endlocal
