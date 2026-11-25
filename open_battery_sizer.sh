#!/usr/bin/env bash
cd "$(dirname "$0")"

fail() {
  echo ""
  echo "$1"
  echo ""
  read -r -p "Press Enter to close this terminal..."
  exit 1
}

if ! command -v python3 >/dev/null 2>&1; then
  fail "Python 3 is not installed or not on your PATH.
Download Python 3 for free at:
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
On Debian/Ubuntu you may need: sudo apt install python3-venv"
  fi
fi

echo "Installing or updating dependencies from requirements.txt..."
.venv/bin/python -m pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt || fail "pip install failed."

echo "Starting Moon Base Battery Sizer in your browser..."
if ! .venv/bin/streamlit run app.py; then
  fail "The app stopped with an error - see message above."
fi