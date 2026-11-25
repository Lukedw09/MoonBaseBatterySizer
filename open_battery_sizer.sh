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