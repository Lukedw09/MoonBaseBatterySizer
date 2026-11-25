@echo off
setlocal
cd /d "%~dp0" || (
  echo Could not open the launcher folder. Move the script out of a path that blocks access.
  pause
  exit /b 1
)

set "PY="
where py >nul 2>&1 && py -3 --version >nul 2>&1 && set "PY=py -3"
if not defined PY (
  where python >nul 2>&1 && python -c "import sys; raise SystemExit(0 if sys.version_info[:1] == (3,) else 1)" 2>nul && set "PY=python"
)
if not defined PY (
  echo.
  echo  Python 3 is not installed or could not be found on this computer.
  echo  Download Python 3.9 or newer for free at:
  echo    https://www.python.org/downloads/
  echo.
  echo  During install on Windows, check "Add python.exe to PATH".
  echo.
  pause
  exit /b 1
)

%PY% -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)" 2>nul
if errorlevel 1 (
  echo.
  echo  This sizer needs Python 3.9 or newer.
  echo  Download a current Python 3 at:
  echo    https://www.python.org/downloads/
  echo.
  pause
  exit /b 1
)

if exist ".venv" (
  if not exist ".venv\Scripts\pip.exe" (
    echo Removing incomplete .venv folder...
    rmdir /s /q .venv
  )
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating a local Python environment in .venv - one-time setup...
  %PY% -m venv .venv
  if errorlevel 1 (
    echo Failed to create .venv.
    pause
    exit /b 1
  )
)

echo Installing or updating dependencies from requirements.txt...
call ".venv\Scripts\python.exe" -m pip install -q --upgrade pip
call ".venv\Scripts\pip.exe" install -q -r requirements.txt
if errorlevel 1 (
  echo pip install failed.
  pause
  exit /b 1
)

echo Starting Moon Base Battery Sizer in your browser...
call ".venv\Scripts\streamlit.exe" run app.py
if errorlevel 1 (
  echo.
  echo The app stopped with an error - see message above.
  pause
  exit /b 1
)

endlocal