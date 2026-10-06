#!/bin/bash
# Double-click to open the Wildflyer app in your browser.
# Keep this window open while you use the app; close it (or press Ctrl+C) to quit.
cd "$(dirname "$0")" || exit 1
if [ ! -f .venv/bin/activate ]; then
  echo "Setting up for the first time (a few minutes)..."
  python3 -m venv .venv || { echo "Python 3 is needed: install it from python.org"; read -r; exit 1; }
fi
source .venv/bin/activate
if ! python -c "import wildflyer, streamlit" 2>/dev/null; then
  echo "Installing / updating Wildflyer..."
  pip install -q -e . || { echo "Install failed; see the messages above."; read -r; exit 1; }
fi
wildflyer app
