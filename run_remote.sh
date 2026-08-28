#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
  echo "Virtual environment not found. Run ./install.sh first." >&2
  exit 1
fi
exec "$ROOT/.venv/bin/python" "$ROOT/piper_x_remote.py" "$@"
