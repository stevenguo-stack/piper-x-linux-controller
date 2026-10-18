#!/usr/bin/env python3
"""Windows installation, import checks, and entry-point dispatch.

This helper never creates a CAN bus or an arm object. Hardware communication is
owned by the explicitly launched controller application. The preview entry point
uses a separate task file and cannot accept arguments that change its dry-run mode.
"""

from __future__ import annotations

import argparse
import importlib
from importlib import metadata
from pathlib import Path
import struct
import subprocess
import sys


ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv-windows"
VENV_PYTHON = VENV / "Scripts" / "python.exe"
LAUNCHER = ROOT / "windows_launcher.py"
APPS = {
    "remote": "piper_x_remote.py",
    "gui": "piper_x_gui.py",
    "cli": "piper_x_cli.py",
}
PYTHON_PROBE = (
    "import struct,sys; "
    "sys.exit(0 if sys.platform == 'win32' and "
    "(3,10) <= sys.version_info[:2] <= (3,12) and "
    "struct.calcsize('P') == 8 else 1)"
)


def require_supported_python() -> None:
    if sys.platform != "win32":
        raise RuntimeError(
            "These launchers target native Windows 10/11 x64. "
            "Use the .sh launchers on Linux."
        )
    if not (3, 10) <= sys.version_info[:2] <= (3, 12):
        raise RuntimeError(
            "Install the 64-bit Windows release of Python 3.10, 3.11, or 3.12 "
            "from python.org. This package does not claim support for other versions."
        )
    if struct.calcsize("P") != 8:
        raise RuntimeError("This package requires a 64-bit Python installation.")


def check_tk() -> str:
    """Import Tcl/Tk without showing a window or using any hardware."""
    try:
        tk = importlib.import_module("tkinter")
        interp = tk.Tcl()
        tcl_version = interp.eval("info patchlevel")
    except Exception as exc:
        raise RuntimeError(
            "Tcl/Tk is unavailable. Modify/reinstall Python from python.org and "
            "include 'tcl/tk and IDLE', then rerun the launcher."
        ) from exc
    return f"Tk {tk.TkVersion}, Tcl {tcl_version}"


def run_process(arguments: list[str]) -> int:
    """Pass an argv list directly, preserving spaces and Unicode in paths."""
    return subprocess.run(arguments, cwd=ROOT, check=False).returncode


def require_windows_venv() -> Path:
    if not VENV_PYTHON.is_file():
        raise RuntimeError(
            "The Windows environment is not installed. Double-click "
            "install_windows.bat first. To preview without SDKs, use preview_windows.bat."
        )
    result = subprocess.run(
        [str(VENV_PYTHON), "-I", "-c", PYTHON_PROBE],
        cwd=ROOT,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if result.returncode:
        raise RuntimeError(
            "The existing .venv-windows cannot run a supported 64-bit Python. "
            "Close the app, rename that environment folder, and rerun "
            "install_windows.bat with Python 3.10, 3.11, or 3.12 installed."
        )
    return VENV_PYTHON


def install() -> int:
    print("Installing PiPER X Windows dependencies.", flush=True)
    print("This installs Python packages only; it does not open CAN or install drivers.", flush=True)
    print(f"[OK] {check_tk()}", flush=True)
    if not VENV_PYTHON.is_file():
        print(f"Creating environment: {VENV}", flush=True)
        result = run_process([sys.executable, "-m", "venv", str(VENV)])
        if result:
            return result
    python = require_windows_venv()
    commands = [
        [str(python), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"],
        [str(python), "-m", "pip", "install", "-r", str(ROOT / "windows_requirements.txt")],
        [str(python), "-m", "pip", "check"],
        [str(python), str(LAUNCHER), "check"],
    ]
    for command in commands:
        result = run_process(command)
        if result:
            print(
                "Installation/check did not finish successfully. Read the error above, "
                "resolve it, and rerun install_windows.bat.",
                flush=True,
            )
            return result
    print("\nInstallation complete. Start with preview_windows.bat.", flush=True)
    print("For the real arm, prepare the matching official USB-CAN driver and use run_remote_windows.bat.", flush=True)
    return 0


def check_dependencies() -> int:
    """Check imports only: never instantiate a backend, enumerate CAN, or enable."""
    print("PiPER X Windows environment check (no CAN connection or motion).", flush=True)
    print(f"Python: {sys.version.split()[0]} / {struct.calcsize('P') * 8}-bit")
    print(f"Executable: {sys.executable}")
    failures = 0
    try:
        print(f"[OK] {check_tk()}")
    except Exception as exc:
        print(f"[FAIL] Tcl/Tk: {exc}")
        failures += 1
    for distribution, module in (("python-can", "can"), ("pyAgxArm", "pyAgxArm")):
        try:
            imported = importlib.import_module(module)
            version = metadata.version(distribution)
            if module == "pyAgxArm":
                for required in (
                    "AgxArmFactory", "ArmModel", "create_agx_arm_config", "resolve_firmware_profile"
                ):
                    if not hasattr(imported, required):
                        raise ImportError(f"SDK API missing: {required}")
            print(f"[OK] {distribution} {version}")
        except Exception as exc:
            print(f"[FAIL] {distribution}: {exc}")
            failures += 1
    try:
        version = metadata.version("python-can-agx-cando")
        matches = [
            ep for ep in metadata.entry_points(group="can.interface")
            if ep.name == "agx_cando"
        ]
        if not matches:
            raise ImportError("The python-can 'agx_cando' backend is not registered.")
        # Loading the backend class imports its module. Do NOT call this class:
        # its constructor is what would open a CAN device.
        backend_class = matches[0].load()
        if not isinstance(backend_class, type):
            raise ImportError("The agx_cando backend entry point did not resolve to a class.")
        print(f"[OK] python-can-agx-cando {version}; backend import succeeded")
    except Exception as exc:
        print(f"[FAIL] python-can-agx-cando / agx_cando: {exc}")
        failures += 1
    print("\nThis check does not verify the Windows USB driver, CAN device, wiring, firmware, or arm motion.")
    if failures:
        print("Run install_windows.bat to install/repair Python dependencies.")
        print("If a DLL import still fails, retain the complete error and check the official adapter instructions.")
        return 1
    print("Imports are ready. Use preview_windows.bat to check the interface.")
    return 0


def check() -> int:
    if VENV_PYTHON.is_file() and Path(sys.executable).resolve() != VENV_PYTHON.resolve():
        python = require_windows_venv()
        return run_process([str(python), str(LAUNCHER), "check"])
    return check_dependencies()


def launch(mode: str, arguments: list[str]) -> int:
    if mode == "preview":
        if arguments:
            raise RuntimeError("The preview entry point does not accept extra arguments.")
        check_tk()
        return run_process([
            sys.executable,
            str(ROOT / APPS["remote"]),
            "--interface", "agx_cando",
            "--can", "0",
            "--speed", "5",
            "--dry-run",
        ])
    python = require_windows_venv()
    if mode != "cli":
        check_tk()
    # argparse uses the final occurrence of an option, so explicit user options
    # can override these defaults, including adapter index and gripper stroke.
    return run_process([
        str(python),
        str(ROOT / APPS[mode]),
        "--interface", "agx_cando",
        "--can", "0",
        "--speed", "5",
        *arguments,
    ])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install/check/launch the native Windows PiPER X controller.")
    parser.add_argument("action", choices=("install", "check", "preview", *APPS))
    parser.add_argument("arguments", nargs=argparse.REMAINDER, help="Controller options for remote/gui/cli.")
    args = parser.parse_args(argv)
    require_supported_python()
    if args.action in ("install", "check"):
        if args.arguments:
            parser.error(f"{args.action} does not accept extra arguments")
        return install() if args.action == "install" else check()
    return launch(args.action, args.arguments)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
