#!/bin/bash
# DreadOS AI for macOS: double-click to start. Runs in the background; you can close this window afterwards.
cd "$(dirname "$0")" || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:/Library/Frameworks/Python.framework/Versions/Current/bin:$PATH"

find_python() {
  if [ -x .venv-voice/bin/python ]; then echo .venv-voice/bin/python; return; fi
  for name in python3.14 python3.13 python3.12 python3.11 python3.10 python3; do
    path=$(command -v "$name") || continue
    # Skip Apple's /usr/bin/python3 stub: it is too old and pops up a developer-tools installer.
    [ "$path" = /usr/bin/python3 ] && continue
    "$path" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null && { echo "$path"; return; }
  done
}

PY=$(find_python)
if [ -z "$PY" ]; then
  echo "DreadOS AI needs Python 3.10 or newer."
  echo "Opening the Python download page. Install it, then double-click Start-DreadOS again."
  open "https://www.python.org/downloads/macos/"
  read -r -p "Press Return to close."
  exit 1
fi

if "$PY" launcher/control.py start; then
  echo "DreadOS AI is running at http://127.0.0.1:8765"
  echo "To stop it, double-click Stop-DreadOS. You can close this window."
else
  echo "Startup failed. Details are in data/launcher-server.log."
  read -r -p "Press Return to close."
  exit 1
fi
