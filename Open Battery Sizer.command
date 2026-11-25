#!/usr/bin/env bash
cd "$(dirname "$0")"

fail() {
  echo ""
  echo "$1"
  echo ""
  read -r -p "Press Enter to close this window..."
  exit 1
}

if ! command -v python3 >/dev/null 2>&1; then
  fail "Python 3 is not installed or not on your PATH.
Download Python 3.9 or newer for free at:
  https://www.python.org/downloads/"
fi

if ! python3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)" 2>/dev/null; then
  fail "This sizer needs Python 3.9 or newer.
Download a current Python 3 at:
  https://www.python.org/downloads/"
fi

if [ -d .venv ] && [ ! -x .venv/bin/pip ]; then
  echo "Removing incomplete .venv folder..."
  rm -rf .venv
fi

if [ ! -x ".venv/bin/python" ]; then
  echo "Creating a local Python environment in .venv - one-time setup..."
  if ! python3 -m venv .venv; then
    fail "Failed to create .venv.
Install Python 3 from https://www.python.org/downloads/ and ensure the venv module is available."
  fi
fi

echo "Installing or updating dependencies from requirements.txt..."
.venv/bin/python -m pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt || fail "pip install failed."

if ! .venv/bin/python -c "import tkinter" 2>/dev/null; then
  fail "Tkinter is missing on this Mac Python install.
Reinstall Python from https://www.python.org/downloads/ (includes Tk),
or install a build that ships Tcl/Tk."
fi

echo "Starting Moon Base Battery Sizer..."
if ! .venv/bin/python gui.py; then
  fail "The app stopped with an error - see message above."
fi