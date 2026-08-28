# PiPER X Linux Controller

A safety-oriented control package for **Ubuntu/Linux + AgileX PiPER X + the official USB-CAN adapter**.

[中文说明](README_CN.md)

## Interfaces

- `piper_x_remote.py` / `run_remote.sh`: recommended touch-friendly remote interface for Cartesian jogging, wrist rotation, gripper control, waypoint teaching, and basket-handling sequences.
- `piper_x_gui.py` / `run_gui.sh`: advanced GUI for six-joint and absolute Cartesian targets.
- `piper_x_cli.py` / `run_cli.sh`: terminal interface for debugging and scripted control.

## Remote Controller Features

- Small forward, backward, left, right, up, and down end-effector movements
- Incremental Roll, Pitch, and Yaw wrist rotation
- Gripper open, close, and target-width commands
- Teaching and saving safe, pre-grasp, grasp, lift, pre-dump, and dump poses
- One-click basket pickup, dumping, return, and full-cycle sequences
- Motion-completion checks, sequence cancellation, and software emergency stop
- Hardware-free dry-run mode
- Ubuntu application launcher, so normal operation does not require terminal commands

## Quick Start

```bash
chmod +x install.sh
./install.sh
./run_remote.sh --dry-run
```

Run the automated hardware-free check with:

```bash
./test_dry_run.sh
```

See [README_CN.md](README_CN.md) for complete installation, wiring, CAN setup, waypoint-teaching, and safety instructions.

> **Safety:** During the first real-hardware test, use low speed and no payload, keep the physical emergency stop within reach, and clear the entire work area. A software emergency stop cannot replace a physical emergency stop or power cutoff. Teach every task pose on the fully assembled robot before running an automated sequence.
