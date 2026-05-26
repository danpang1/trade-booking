@echo off
REM Windows shim for the tokka-mo CLI. Requires "py -3" or "python".
REM Forwards all arguments to the Python script in the same directory.
where py >NUL 2>&1
if %ERRORLEVEL% EQU 0 (
  py -3 "%~dp0tokka-mo" %*
) else (
  python "%~dp0tokka-mo" %*
)
