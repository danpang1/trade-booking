@echo off
REM tokka-mo Claude Code plugin installer (Windows).
REM
REM Usage:
REM   install.bat              # install from this local clone
REM   install.bat --remote     # install from the Bitbucket remote (sparse)

setlocal EnableExtensions

set "REMOTE=0"
if /I "%~1"=="--remote" set "REMOTE=1"

REM Repo root is the parent of this plugin/ directory
set "PLUGIN_PARENT=%~dp0.."
for %%I in ("%PLUGIN_PARENT%") do set "REPO_ROOT=%%~fI"

echo tokka-mo installer

REM Check Python 3.10+
where py >NUL 2>&1
if errorlevel 1 (
  where python >NUL 2>&1
  if errorlevel 1 (
    echo ERROR: Python not found on PATH. Install Python 3.10+ first.
    exit /b 1
  )
)
echo   Python OK

REM Check Claude Code
where claude >NUL 2>&1
if errorlevel 1 (
  echo ERROR: 'claude' command not found. Install Claude Code from claude.com/code first.
  exit /b 1
)
echo   Claude Code OK

REM Register the marketplace
if "%REMOTE%"=="1" (
  echo   - registering marketplace from Bitbucket ^(sparse^)
  claude plugin marketplace add "ssh://git@bitbucket.org/tokkalabs/middle-office-tools.git" --sparse plugin .claude-plugin
) else (
  echo   - registering marketplace from %REPO_ROOT%
  claude plugin marketplace add "%REPO_ROOT%"
)

REM Install the plugin
echo   - installing tokka-mo@tokka-mo-marketplace
claude plugin install tokka-mo@tokka-mo-marketplace

REM Config + cache dirs
if not exist "%APPDATA%\tokka-mo" mkdir "%APPDATA%\tokka-mo"
if not exist "%LOCALAPPDATA%\tokka-mo" mkdir "%LOCALAPPDATA%\tokka-mo"
echo   created %APPDATA%\tokka-mo and %LOCALAPPDATA%\tokka-mo

echo.
echo Done. Restart any running Claude Code session (/exit then claude)
echo so it picks up the new plugin, then try:
echo   /tokka-mo:login           # first-time auth
echo   /tokka-mo:book ...        # book a CASHFLOW draft
echo   /tokka-mo:drafts          # list your drafts
