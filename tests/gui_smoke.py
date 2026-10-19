"""Construct both Tk interfaces without connecting or enabling any arm.

Run explicitly on the Windows CI runner with ``python tests/gui_smoke.py``.
This file is intentionally outside unittest's ``test*.py`` discovery pattern.
It needs a working desktop display; a headless Linux syntax check does not
validate the GUI. No SDK, driver, or physical hardware is tested here.
"""
from __future__ import annotations

import sys
import tempfile
import tkinter as tk
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch


# Direct script execution puts tests/ first, so add the project directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from piper_x_controller import PiperXController
from piper_x_gui import PiperXGUI
from piper_x_platform import prepare_windows_gui
from piper_x_remote import BasketTaskStore, PiperXRemoteGUI


def smoke_window(gui_type, data_directory: Path) -> None:
    controller = PiperXController(dry_run=True)
    assert controller.dry_run is True
    path = data_directory / f"{gui_type.__name__}_demo.json"
    argument = (
        BasketTaskStore(path, controller.gripper_max_mm)
        if gui_type is PiperXRemoteGUI
        else path
    )
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        raise RuntimeError(
            "Could not create a Tk window. This GUI smoke test requires a "
            f"working desktop display; no GUI was validated. Tk reported: {exc}"
        ) from exc

    app = None
    callback_errors = []

    def record_callback_error(exception_type, exception_value, traceback) -> None:
        # Tk normally prints callback errors and keeps running. Treat them as
        # failures so a CI run cannot pass with a broken startup callback.
        callback_errors.append((exception_type, exception_value))

    root.report_callback_exception = record_callback_error
    try:
        with ExitStack() as guards:
            guarded_methods = {
                name: guards.enter_context(
                    patch.object(
                        controller,
                        name,
                        side_effect=AssertionError(
                            f"GUI construction must not call {name}"
                        ),
                    )
                )
                for name in (
                    "_load_sdk", "connect", "enable", "move_joints_deg",
                    "move_pose_deg", "move_gripper_mm",
                )
            }
            app = gui_type(root, controller, argument)
            root.update_idletasks()
            root.update()

            assert not callback_errors, f"Tk callback errors: {callback_errors}"
            assert app.root is root and root.winfo_exists()
            assert "PiPER X" in root.title() and "模拟预览" in root.title()
            assert root.winfo_children(), "The window has no controls"
            assert root.winfo_reqwidth() > 100 and root.winfo_reqheight() > 100
            assert not controller.connected and not controller.motion_armed
            assert controller.robot is None and controller.gripper is None
            assert "锁定" in app.arm_text.get()
            assert app.enable_btn.instate(["disabled"])
            assert app.motion_widgets, "No motion controls were constructed"
            assert all(widget.instate(["disabled"]) for widget in app.motion_widgets)
            for guard in guarded_methods.values():
                guard.assert_not_called()
            print(
                f"PASS {gui_type.__name__}: window constructed and updated; "
                "dry-run, disconnected, motion locked."
            )
    finally:
        # Do not call the interactive on_close handler or any controller action.
        if app is not None:
            app._closing = True
            app.executor.shutdown(wait=True, cancel_futures=True)
        for callback_id in root.tk.call("after", "info"):
            root.after_cancel(callback_id)
        root.destroy()


def main() -> int:
    prepare_windows_gui()
    with tempfile.TemporaryDirectory(prefix="piper-x-gui-smoke-") as directory:
        for gui_type in (PiperXRemoteGUI, PiperXGUI):
            smoke_window(gui_type, Path(directory))
    print("Both GUI construction checks passed. No physical hardware was exercised.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
