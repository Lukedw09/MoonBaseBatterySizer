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

if [ ! -x ".venv/bin/python" ]; then
  echo "Creating a local Python environment (.venv) — one-time setup..."
  python3 -m venv .venv || fail "Failed to create .venv."
fi

MARKER=".venv/.requirements-installed"
if [ ! -f "$MARKER" ] || [ requirements.txt -nt "$MARKER" ]; then
  echo "Installing dependencies from requirements.txt..."
  .venv/bin/python -m pip install -q --upgrade pip
  .venv/bin/pip install -r requirements.txt || fail "pip install failed."
  touch "$MARKER"
fi

echo "Starting Moon Base Battery Sizer in your browser..."
if ! .venv/bin/streamlit run app.py; then
  fail "The app stopped with an error (see message above)."
fi