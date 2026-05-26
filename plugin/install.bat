@echo off
REM tokka-mo Claude Code plugin installer (Windows).
REM Run from inside the plugin directory:
REM   cd <middle-office-tools>\plugin
REM   install.bat

setlocal EnableExtensions

set "PLUGIN_SRC=%~dp0"
if "%PLUGIN_SRC:~-1%"=="\" set "PLUGIN_SRC=%PLUGIN_SRC:~0,-1%"
set "PLUGIN_DIR=%USERPROFILE%\.claude\plugins\tokka-mo"

echo tokka-mo installer
echo   source: %PLUGIN_SRC%

REM Check Python
where py >NUL 2>&1
if errorlevel 1 (
  where python >NUL 2>&1
  if errorlevel 1 (
    echo ERROR: Python not found on PATH. Install Python 3.10+ first.
    exit /b 1
  )
)

REM Register plugin via mklink /D (requires admin OR Developer Mode)
if exist "%PLUGIN_DIR%" rmdir /S /Q "%PLUGIN_DIR%"
mklink /D "%PLUGIN_DIR%" "%PLUGIN_SRC%" >NUL 2>&1
if errorlevel 1 (
  echo NOTE: mklink failed (need admin or Developer Mode). Falling back to copy.
  xcopy /E /I /Y "%PLUGIN_SRC%" "%PLUGIN_DIR%" >NUL
)
echo   linked plugin to %PLUGIN_DIR%

REM Config + cache dirs
if not exist "%APPDATA%\tokka-mo" mkdir "%APPDATA%\tokka-mo"
if not exist "%LOCALAPPDATA%\tokka-mo" mkdir "%LOCALAPPDATA%\tokka-mo"
echo   created %APPDATA%\tokka-mo and %LOCALAPPDATA%\tokka-mo

REM Add bin/tokka-mo.bat to user PATH if not present
echo.
echo NOTE: Add %PLUGIN_SRC%\bin to your user PATH for `tokka-mo` to work in a shell.
echo Then open Claude Code and run /login.
