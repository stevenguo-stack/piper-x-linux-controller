#!/usr/bin/env bash
set -euo pipefail

IFACE="${1:-can0}"
BITRATE="1000000"

if ! command -v ip >/dev/null 2>&1; then
  echo "The 'ip' command is missing. Install iproute2." >&2
  exit 1
fi

sudo modprobe can 2>/dev/null || true
sudo modprobe can_raw 2>/dev/null || true
sudo modprobe can_dev 2>/dev/null || true
sudo modprobe gs_usb 2>/dev/null || true

if ! ip link show "$IFACE" >/dev/null 2>&1; then
  cat >&2 <<MSG
SocketCAN interface '$IFACE' was not found.

Check that the official USB-CAN module supplied for PiPER is connected.
Then run:
  ip -brief link

If it appears under another name, call this script with that name, for example:
  ./setup_can.sh can1
MSG
  exit 2
fi

sudo ip link set "$IFACE" down 2>/dev/null || true
sudo ip link set "$IFACE" type can bitrate "$BITRATE" restart-ms 100
sudo ip link set "$IFACE" txqueuelen 1000
sudo ip link set "$IFACE" up

echo
echo "Activated $IFACE at 1,000,000 bit/s:"
ip -details -statistics link show "$IFACE"
echo
echo "Optional receive test (Ctrl+C to stop): candump $IFACE"
