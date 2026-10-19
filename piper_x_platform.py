"""Platform-specific connection defaults; no SDK import or hardware access."""
from __future__ import annotations

import argparse
import os
import platform
from pathlib import Path
from typing import Optional, Tuple


CAN_INTERFACES = ("auto", "socketcan", "agx_cando")


def resolve_can_connection(
    can_port: Optional[str] = None,
    can_interface: Optional[str] = "auto",
    system: Optional[str] = None,
) -> Tuple[str, str]:
    """Resolve official Windows/Linux backends without opening the device."""
    system = platform.system() if system is None else system
    interface = can_interface or "auto"
    if interface not in CAN_INTERFACES:
        raise ValueError("CAN interface must be auto, socketcan, or agx_cando.")
    if interface == "auto":
        interface = "agx_cando" if system == "Windows" else "socketcan"
    channel = "" if can_port is None else str(can_port).strip()
    if not channel:
        channel = "0" if interface == "agx_cando" else "can0"
    if interface == "agx_cando":
        if not channel.isascii() or not channel.isdecimal():
            raise ValueError(
                "Windows CAN channel must be a non-negative device index "
                "such as 0, 1, or 2; do not enter Linux's can0."
            )
        channel = str(int(channel))
    return interface, channel


def add_can_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--interface", choices=CAN_INTERFACES, default="auto",
        help="CAN backend: Windows=agx_cando, Linux=socketcan (default: auto)",
    )
    parser.add_argument(
        "--can", default=None,
        help="CAN channel: Windows device index (default: 0), Linux name (default: can0)",
    )


def user_config_directory() -> Path:
    if platform.system() == "Windows":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "NXTektal" / "PiPER-X"
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "nxtektal-piper-x"


def default_pose_file(dry_run: bool = False) -> Path:
    """Keep original Linux poses and keep demonstration points out of real runs."""
    name = "poses_demo.json" if dry_run else "poses.json"
    if platform.system() == "Windows":
        return user_config_directory() / name
    return Path(__file__).resolve().with_name(name)


def prepare_windows_gui() -> None:
    """Use native DPI scaling when available, before creating the Tk window."""
    if platform.system() != "Windows":
        return
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass
