# PiPER X Controller — Windows and Linux

A control package for **Windows or Ubuntu/Linux + AgileX PiPER X + the official USB-CAN adapter**.

[Windows 中文使用说明](README_WINDOWS_CN.md) · [Linux 中文说明](README_CN.md)

## Windows quick start

Install 64-bit Python 3.10–3.12 from python.org with Tcl/Tk support. Extract this
folder before opening any launcher.

- Double-click `preview_windows.bat` to open the hardware-free remote. This does
  not install the CAN SDK or access a device.
- Double-click `install_windows.bat` once to prepare real-arm dependencies.
- Double-click `check_windows.bat` to check the Python/SDK/plugin environment.
- Double-click `run_remote_windows.bat` for the real-arm interface. Connect and
  enable remain explicit actions inside the interface.

Windows uses the official `agx_cando` backend with device index `0`; Linux keeps
`socketcan` with interface `can0`. This is a Python source package with launchers,
not a standalone executable. Installation, SDK/backend imports, both Tk window
constructors, batch launch arguments, and terminal simulation passed on Windows
Server 2025 x64 / Python 3.12.10 in [Windows CI](https://github.com/stevenguo-stack/piper-x-linux-controller/actions/runs/39176648946).
Physical USB-CAN drivers, device communication, and real arm motion still require
validation with the user's hardware.

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

## Linux quick start

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
