#!/usr/bin/env sh
set -eu
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
if [ -n "${AMVISION_PYTHON_EXECUTABLE:-}" ]; then
  PYTHON_EXE="$AMVISION_PYTHON_EXECUTABLE"
elif [ -x "$SCRIPT_DIR/python/bin/python3" ]; then
  PYTHON_EXE="$SCRIPT_DIR/python/bin/python3"
elif [ -x "$SCRIPT_DIR/python/bin/python" ]; then
  PYTHON_EXE="$SCRIPT_DIR/python/bin/python"
else
  PYTHON_EXE=python3
fi
exec "$PYTHON_EXE" "$SCRIPT_DIR/stop_amvision_full.py" "$@"