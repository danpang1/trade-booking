@echo off
REM ============================================================
REM  8041 MTD-aggregated full-account recon (one table).
REM  Balance delta, trade/cash delta, unreal, transfers and
REM  breaks aggregated over inception (2026-06-12) .. COB.
REM  Pulls LIVE venue data + snapshots; no DB refresh needed.
REM  Usage:
REM    Double-click                 -> prompts for the COB date
REM    run_mtd_recon.bat 2026-06-28          (date as arg)
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

echo.
echo ============================================================
echo  MTD-aggregated full-account recon - COB %COB%
echo ============================================================
echo.
"%PY%" account_recon.py %COB% --mtd

echo.
echo ============================================================
echo  Done.  Press any key to close.
pause >nul
endlocal
