@echo off
REM ================================================================
REM Tokka MO - Manual Trade Booking (standalone module)
REM Usage: double-click this file, or run "start.bat" from cmd
REM ================================================================

REM Run from this script's directory regardless of where it's launched
cd /d "%~dp0"

echo.
echo === Tokka MO - Manual Trade Booking ===
echo.

REM Auto-install if node_modules is missing
if not exist "node_modules" (
    echo Installing dependencies (first run only)...
    call npm install
    if errorlevel 1 (
        echo.
        echo ERROR: npm install failed. Make sure Node.js is installed.
        echo Download from https://nodejs.org/
        pause
        exit /b 1
    )
    echo.
)

echo Starting Vite dev server on http://localhost:5180
echo Open this URL in your browser, or it will open automatically in 3 seconds.
echo Press Ctrl+C to stop the server.
echo ---

REM Open the browser after a short delay so Vite has time to bind
start "" /min cmd /c "timeout /t 3 >nul & start http://localhost:5180/"

REM Run Vite in the foreground; window stays open while server runs
call npm run dev

REM If the server exits, pause so the user can see any error message
echo.
echo Server stopped.
pause
