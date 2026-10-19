@echo off
setlocal EnableExtensions DisableDelayedExpansion
rem No arguments are forwarded: this entry always starts a hardware-free preview.
call "%~dp0windows_bootstrap.bat" preview
set "PIPER_EXIT_CODE=%errorlevel%"
if not "%PIPER_EXIT_CODE%"=="0" pause
exit /b %PIPER_EXIT_CODE%
