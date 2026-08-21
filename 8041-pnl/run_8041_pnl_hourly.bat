@echo off
REM ============================================================
REM  Run the Portfolio 8041 HOURLY PnL (24 buckets, COB day).
REM  Marks from Binance markPriceKlines (1h); NO ClickHouse.
REM  Usage:
REM    Double-click            -> prompts for the COB date
REM    run_8041_pnl_hourly.bat 2026-06-17           (date as arg)
REM    run_8041_pnl_hourly.bat 2026-06-17 pg        (date + pg mark source)
REM ============================================================
setlocal
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"

REM --- locate Python (full path first, then PATH fallback) ---
set "PY=C:\Users\peter\AppData\Local\Programs\Python\Python311\python.exe"
if not exist "%PY%" set "PY=python"

cd /d "C:\Users\peter\OneDrive\Desktop\Claude\middle-office-tools\8041-pnl"

set "COB=%~1"
set "SRC=%~2"

if "%COB%"=="" set /p COB="Enter COB date (YYYY-MM-DD): "
if "%COB%"=="" (
    echo No date entered. Exiting.
    pause
    exit /b 1
)
if "%SRC%"=="" set "SRC=binance"

echo.
echo Running 8041 HOURLY PnL for COB %COB%  ^(marks: %SRC%^)...
echo.
"%PY%" pnl_8041_hourly.py --date %COB% --mark-source %SRC%

echo.
echo ============================================================
echo  Done.  Press any key to close.
pause >nul
endlocal
