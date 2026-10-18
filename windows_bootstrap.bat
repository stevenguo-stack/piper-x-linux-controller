@echo off
setlocal EnableExtensions DisableDelayedExpansion
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

rem Keep the Windows environment separate from the Linux .venv directory.
if not exist "%~dp0.venv-windows\Scripts\python.exe" goto find_launcher
"%~dp0.venv-windows\Scripts\python.exe" -I -c "import struct,sys; sys.exit(0 if sys.platform == 'win32' and (3,10) <= sys.version_info[:2] <= (3,12) and struct.calcsize('P') == 8 else 1)" >nul 2>&1
if errorlevel 1 goto find_launcher
"%~dp0.venv-windows\Scripts\python.exe" "%~dp0windows_launcher.py" %*
exit /b %errorlevel%

:find_launcher
where py >nul 2>&1
if errorlevel 1 goto find_python
py -3.12 -I -c "import struct,sys; sys.exit(0 if sys.platform == 'win32' and struct.calcsize('P') == 8 else 1)" >nul 2>&1
if not errorlevel 1 goto python312
py -3.11 -I -c "import struct,sys; sys.exit(0 if sys.platform == 'win32' and struct.calcsize('P') == 8 else 1)" >nul 2>&1
if not errorlevel 1 goto python311
py -3.10 -I -c "import struct,sys; sys.exit(0 if sys.platform == 'win32' and struct.calcsize('P') == 8 else 1)" >nul 2>&1
if not errorlevel 1 goto python310
goto find_python

:python312
py -3.12 "%~dp0windows_launcher.py" %*
exit /b %errorlevel%

:python311
py -3.11 "%~dp0windows_launcher.py" %*
exit /b %errorlevel%

:python310
py -3.10 "%~dp0windows_launcher.py" %*
exit /b %errorlevel%

:find_python
where python >nul 2>&1
if errorlevel 1 goto missing_python
python -I -c "import struct,sys; sys.exit(0 if sys.platform == 'win32' and (3,10) <= sys.version_info[:2] <= (3,12) and struct.calcsize('P') == 8 else 1)" >nul 2>&1
if errorlevel 1 goto missing_python
python "%~dp0windows_launcher.py" %*
exit /b %errorlevel%

:missing_python
echo A supported Python installation was not found.
echo Install Python 3.10, 3.11, or 3.12 for Windows, 64-bit, from:
echo https://www.python.org/downloads/windows/
echo Include pip, Tcl/Tk, and the Python launcher, then try again.
echo If the launcher is unavailable, add that Python installation to PATH.
exit /b 1
