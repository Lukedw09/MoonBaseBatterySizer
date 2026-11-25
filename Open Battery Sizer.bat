@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

set "PY="
where py >nul 2>&1 && py -3 --version >nul 2>&1 && set "PY=py -3"
if not defined PY (
  where python >nul 2>&1 && python -c "import sys; raise SystemExit(0 if sys.version_info[:1] == (3,) else 1)" 2>nul && set "PY=python"
)
if not defined PY (
  echo.
  echo  Python 3 is not installed or could not be found on this computer.
  echo  Download Python 3 for free at:
  echo    https://www.python.org/downloads/
  echo.
  echo  During install on Windows, check "Add python.exe to PATH".
  echo.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating a local Python environment (.venv) — one-time setup...
  %PY% -m venv .venv
  if errorlevel 1 (
    echo Failed to create .venv.
    pause
    exit /b 1
  )
)

set "MARKER=.venv\.requirements-installed"
set "NEED_PIP=0"
if not exist "%MARKER%" set "NEED_PIP=1"
if "%NEED_PIP%"=="0" (
  for %%F in (requirements.txt) do set "REQ_TIME=%%~tF"
  for %%F in ("%MARKER%") do set "MARK_TIME=%%~tF"
  if "!REQ_TIME!" gtr "!MARK_TIME!" set "NEED_PIP=1"
)
if "%NEED_PIP%"=="1" (
  echo Installing dependencies from requirements.txt...
  call ".venv\Scripts\python.exe" -m pip install -q --upgrade pip
  call ".venv\Scripts\pip.exe" install -r requirements.txt
  if errorlevel 1 (
    echo pip install failed.
    pause
    exit /b 1
  )
  copy /b nul "%MARKER%" >nul
)

echo Starting Moon Base Battery Sizer in your browser...
call ".venv\Scripts\streamlit.exe" run app.py
if errorlevel 1 (
  echo.
  echo The app stopped with an error (see message above).
  pause
  exit /b 1
)

endlocal