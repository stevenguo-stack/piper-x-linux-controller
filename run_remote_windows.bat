@echo off
setlocal EnableExtensions DisableDelayedExpansion
call "%~dp0windows_bootstrap.bat" remote %*
set "PIPER_EXIT_CODE=%errorlevel%"
if not "%PIPER_EXIT_CODE%"=="0" pause
exit /b %PIPER_EXIT_CODE%
