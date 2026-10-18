@echo off
setlocal EnableExtensions DisableDelayedExpansion
call "%~dp0windows_bootstrap.bat" install %*
set "PIPER_EXIT_CODE=%errorlevel%"
echo.
pause
exit /b %PIPER_EXIT_CODE%
