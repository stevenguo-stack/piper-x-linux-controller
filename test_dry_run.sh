#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${PYTHON:-python3}"

printf 'status\nquit\n' | "$PYTHON" "$ROOT/piper_x_cli.py" --dry-run --speed 10
