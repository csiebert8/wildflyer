#!/bin/bash
# Double-click to build "AUSL Schedule Solver.app" on this Mac (takes a few minutes).
# Run "AUSL Schedule Solver.command" once first, so the Python environment exists.
cd "$(dirname "$0")" || exit 1
if [ ! -f .venv/bin/activate ]; then
  echo "Please double-click 'AUSL Schedule Solver.command' once first (it sets things up), then try again."
  read -r; exit 1
fi
source .venv/bin/activate
echo "Installing the packaging tools..."
pip install -q -e . pyinstaller pillow || { echo "Install failed; see the messages above."; read -r; exit 1; }
echo "Building the app (a few minutes)..."
pyinstaller packaging/ausl_solver.spec --noconfirm || { echo "Build failed; see the messages above."; read -r; exit 1; }
ditto -c -k --keepParent "dist/AUSL Schedule Solver.app" "dist/AUSL-Schedule-Solver-mac.zip"
echo
echo "Done!"
echo "  The app:            dist/AUSL Schedule Solver.app  (drag it into Applications)"
echo "  To share (zipped):  dist/AUSL-Schedule-Solver-mac.zip"
open dist
