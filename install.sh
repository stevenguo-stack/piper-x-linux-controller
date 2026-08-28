#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is not installed." >&2
  exit 1
fi

if command -v apt-get >/dev/null 2>&1; then
  echo "Installing Ubuntu system packages (sudo may ask for your password)..."
  sudo apt-get update
  sudo apt-get install -y \
    python3 python3-venv python3-pip python3-tk \
    git can-utils ethtool iproute2
else
  echo "apt-get not found. Install Python 3, Tk, Git, can-utils, ethtool and iproute2 manually."
fi

python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt

cat <<'MSG'

Installation complete.

Next:
  1) Connect the official PiPER USB-CAN adapter.
  2) Power PiPER X with stable 24 V DC.
  3) Run: ./setup_can.sh can0
  4) Test the remote UI without hardware: ./run_remote.sh --dry-run
  5) Real arm remote UI: ./run_remote.sh --can can0 --speed 10
  6) Optional application-menu launcher: ./install_desktop_launcher.sh can0 10
  7) Advanced GUI: ./run_gui.sh --can can0 --speed 10
MSG
