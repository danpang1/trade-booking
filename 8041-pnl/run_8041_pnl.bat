@echo off
REM ============================================================
REM  Run the Portfolio 8041 daily PnL + full-account recon.
REM  Usage:
REM    Double-click            -> prompts for the COB date
REM    run_8041_pnl.bat 2026-06-16            (date as arg)
REM    run_8041_pnl.bat 2026-06-16 205.8975372  (date + pinned EOD mark)
REM ============================================================
setlocal
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"

REM --- locate Python (full path first, then PATH fallback) ---
set "PY=C:\Users\peter\AppData\Local\Programs\Python\Python311\python.exe"
if not exist "%PY%" set "PY=python"

cd /d "C:\Users\peter\OneDrive\Desktop\Claude\middle-office-tools\8041-pnl"

set "COB=%~1"
set "MARK=%~2"

if "%COB%"=="" set /p COB="Enter COB date (YYYY-MM-DD): "
if "%COB%"=="" (
    echo No date entered. Exiting.
    pause
    exit /b 1
)

echo.
if "%MARK%"=="" (
    echo Running 8041 PnL for COB %COB%  ^(marks auto from Binance perp^)...
    echo.
    "%PY%" pnl_8041_daily.py --date %COB%
) else (
    echo Running 8041 PnL for COB %COB%  ^(pinned EOD mark %MARK%^)...
    echo.
    "%PY%" pnl_8041_daily.py --date %COB% --mark %MARK%
)

echo.
echo ============================================================
echo  Done.  Press any key to close.
pause >nul
endlocal
