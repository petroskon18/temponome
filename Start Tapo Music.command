#!/bin/bash
# Double-click launcher for the Tapo Music Sync color-wheel app.
# Keep this file and tapo_music_ui.py in the same folder.
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is not installed. Opening the download page..."
  open "https://www.python.org/downloads/macos/"
  read -p "Install Python, then double-click this file again. Press Enter to close."
  exit 1
fi

echo "Checking packages (first run may take a minute)..."
python3 -m pip install --quiet --user tapo sounddevice numpy

echo "Opening the app in your browser. Close this window or press Ctrl+C to quit."
python3 tapo_music_ui.py
read -p "Stopped. Press Enter to close."
