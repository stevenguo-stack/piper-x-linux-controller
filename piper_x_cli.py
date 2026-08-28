#!/usr/bin/env python3
"""Interactive terminal controller for AgileX PiPER X on Linux."""
from __future__ import annotations

import argparse
import cmd
import json
import math
import shlex
import sys
from pathlib import Path
from typing import List

from piper_x_controller import PiperXController


POSES_PATH = Path(__file__).resolve().with_name("poses.json")


def parse_numbers(arg: str, expected: int | None = None) -> List[float]:
    parts = shlex.split(arg)
    try:
        values = [float(x) for x in parts]
    except ValueError as exc:
        raise ValueError("All arguments must be numbers.") from exc
    if expected is not None and len(values) != expected:
        raise ValueError(f"Expected {expected} numbers, got {len(values)}.")
    return values


def load_poses() -> dict:
    if not POSES_PATH.exists():
        return {}
    try:
        return json.loads(POSES_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_poses(data: dict) -> None:
    POSES_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


class PiperShell(cmd.Cmd):
    intro = (
        "\nPiPER X terminal controller. Type 'help' for commands.\n"
        "Motion starts LOCKED. Run 'enable' only after clearing the work area.\n"
    )
    prompt = "piper-x> "

    def __init__(self, controller: PiperXController) -> None:
        super().__init__()
        self.c = controller

    def emptyline(self) -> None:
        pass

    def default(self, line: str) -> None:
        print(f"Unknown command: {line!r}. Type 'help'.")

    @staticmethod
    def _confirm(text: str, token: str) -> bool:
        answer = input(f"{text}\nType {token} to continue: ").strip()
        return answer == token

    def do_status(self, arg: str) -> None:
        """status
        Show firmware, communication, joint angles, flange pose, enable state,
        gripper state, and arm status.
        """
        try:
            s = self.c.get_snapshot()
            print(f"connected        : {s.connected}")
            print(f"communication_ok : {s.communication_ok}")
            print(f"firmware         : {s.firmware}")
            if s.joint_deg is not None:
                print(
                    "joint_deg       : "
                    + "  ".join(f"J{i+1}={v:8.3f}" for i, v in enumerate(s.joint_deg))
                )
            else:
                print("joint_deg        : no feedback")
            if s.flange_pose is not None:
                x, y, z, r, p, yv = s.flange_pose
                print(
                    "flange_pose      : "
                    f"xyz=({x:.4f}, {y:.4f}, {z:.4f}) m, "
                    f"rpy=({math.degrees(r):.2f}, {math.degrees(p):.2f}, "
                    f"{math.degrees(yv):.2f}) deg"
                )
            print(f"enabled_joints   : {s.enabled_joints}")
            print(f"arm_status       : {s.arm_status}")
            print(
                "gripper          : "
                f"width={s.gripper_width_mm} mm, force={s.gripper_force_n} N"
            )
            print(f"program armed    : {self.c.motion_armed}")
            print(f"speed            : {self.c.speed_percent}%")
        except Exception as exc:
            print(f"ERROR: {exc}")

    def do_enable(self, arg: str) -> None:
        """enable
        Enable all six joints. Requires a typed confirmation.
        """
        if not self._confirm(
            "Confirm: chassis stopped, arm firmly mounted, work area clear, "
            "physical E-stop reachable.",
            "ENABLE",
        ):
            print("Cancelled.")
            return
        try:
            ok = self.c.enable()
            print("Enabled." if ok else "Enable timed out; check status/E-stop.")
        except Exception as exc:
            print(f"ERROR: {exc}")

    def do_disable(self, arg: str) -> None:
        """disable
        Disable all joints. Place the arm in a supported pose first because it
        may lose holding torque.
        """
        if not self._confirm(
            "Disabling may release holding torque. Make sure the arm/load is supported.",
            "DISABLE",
        ):
            print("Cancelled.")
            return
        try:
            ok = self.c.disable()
            print("Disabled." if ok else "Disable timed out.")
        except Exception as exc:
            print(f"ERROR: {exc}")

    def do_stop(self, arg: str) -> None:
        """stop
        Send the SDK's damped electronic emergency-stop command immediately.
        The physical E-stop remains the primary safety device.
        """
        try:
            self.c.emergency_stop()
            print("Electronic emergency stop sent. Motion is locked.")
        except Exception as exc:
            print(f"ERROR: {exc}")

    def do_reset(self, arg: str) -> None:
        """reset
        Reset the arm motion controller after the cause of a stop/error is removed.
        Motion remains locked until 'enable' is run again.
        """
        if not self._confirm(
            "Reset only after removing the cause of the stop/error.", "RESET"
        ):
            print("Cancelled.")
            return
        try:
            self.c.reset()
            print("Reset command sent. Run 'status', then 'enable' if safe.")
        except Exception as exc:
            print(f"ERROR: {exc}")

    def do_speed(self, arg: str) -> None:
        """speed PERCENT
        Set motion speed to 1..50 percent. Example: speed 10
        """
        try:
            values = parse_numbers(arg, 1)
            percent = int(values[0])
            if percent != values[0]:
                raise ValueError("Speed must be an integer.")
            self.c.set_speed_percent(percent)
            print(f"Speed set to {percent}%.")
        except Exception as exc:
            print(f"ERROR: {exc}")

    def do_jog(self, arg: str) -> None:
        """jog JOINT DELTA_DEG
        Move one joint relative to live feedback. Joint is 1..6; each step must
        be within ±5 degrees. Example: jog 2 -1
        """
        try:
            values = parse_numbers(arg, 2)
            joint = int(values[0])
            if joint != values[0]:
                raise ValueError("Joint index must be an integer.")
            target = self.c.jog_joint_deg(joint, values[1])
            print("Target deg:", " ".join(f"{v:.3f}" for v in target))
        except Exception as exc:
            print(f"ERROR: {exc}")

    def do_joints(self, arg: str) -> None:
        """joints J1 J2 J3 J4 J5 J6
        Move to six absolute joint angles in degrees using ordinary Move-J.
        Example: joints 0 30 -60 0 30 0
        """
        try:
            values = parse_numbers(arg, 6)
            print("Requested absolute joint target (deg):", values)
            if not self._confirm("Review the target and collision path.", "MOVE"):
                print("Cancelled.")
                return
            self.c.move_joints_deg(values)
            print("Joint target sent.")
        except Exception as exc:
            print(f"ERROR: {exc}")

    def do_pose(self, arg: str) -> None:
        """pose X Y Z ROLL PITCH YAW
        Point-to-point Cartesian move. XYZ are metres; RPY are degrees.
        Use only after joint-space jog testing because IK can select an unexpected
        configuration. Example: pose 0.25 0 0.30 0 90 0
        """
        self._pose_common(arg, linear=False)

    def do_line(self, arg: str) -> None:
        """line X Y Z ROLL PITCH YAW
        Linear Cartesian move. XYZ are metres; RPY are degrees.
        Example: line 0.25 0 0.35 0 90 0
        """
        self._pose_common(arg, linear=True)

    def _pose_common(self, arg: str, linear: bool) -> None:
        try:
            values = parse_numbers(arg, 6)
            mode = "linear" if linear else "point-to-point"
            print(f"Requested {mode} pose: {values}")
            if not self._confirm(
                "Cartesian motion uses controller IK. Review workspace and path.",
                "MOVE",
            ):
                print("Cancelled.")
                return
            self.c.move_pose_deg(values, linear=linear)
            print("Pose target sent.")
        except Exception as exc:
            print(f"ERROR: {exc}")

    def do_grip(self, arg: str) -> None:
        """grip WIDTH_MM [FORCE_N]
        Command gripper width and force. Example: grip 35 3
        """
        try:
            values = parse_numbers(arg)
            if len(values) not in (1, 2):
                raise ValueError("Usage: grip WIDTH_MM [FORCE_N]")
            width = values[0]
            force = values[1] if len(values) == 2 else 1.0
            self.c.move_gripper_mm(width, force)
            print(f"Gripper target: {width:g} mm at {force:g} N.")
        except Exception as exc:
            print(f"ERROR: {exc}")

    def do_open(self, arg: str) -> None:
        """open [FORCE_N]
        Open the gripper to the configured maximum width.
        """
        try:
            values = parse_numbers(arg)
            if len(values) > 1:
                raise ValueError("Usage: open [FORCE_N]")
            force = values[0] if values else 1.0
            self.c.open_gripper(force)
            print("Gripper open command sent.")
        except Exception as exc:
            print(f"ERROR: {exc}")

    def do_close(self, arg: str) -> None:
        """close [FORCE_N]
        Close the gripper to 0 mm. Keep fingers and cables clear.
        """
        try:
            values = parse_numbers(arg)
            if len(values) > 1:
                raise ValueError("Usage: close [FORCE_N]")
            force = values[0] if values else 1.0
            if not self._confirm(
                "Closing can pinch or crush objects. Keep clear.", "CLOSE"
            ):
                print("Cancelled.")
                return
            self.c.close_gripper(force)
            print("Gripper close command sent.")
        except Exception as exc:
            print(f"ERROR: {exc}")

    def do_save(self, arg: str) -> None:
        """save NAME
        Save the current six-joint pose (degrees) to poses.json.
        """
        name = arg.strip()
        if not name or any(ch.isspace() for ch in name):
            print("ERROR: NAME must be one word.")
            return
        try:
            s = self.c.get_snapshot()
            if s.joint_deg is None:
                raise RuntimeError("No joint feedback available.")
            poses = load_poses()
            poses[name] = [round(v, 6) for v in s.joint_deg]
            save_poses(poses)
            print(f"Saved pose '{name}': {poses[name]}")
        except Exception as exc:
            print(f"ERROR: {exc}")

    def do_go(self, arg: str) -> None:
        """go NAME
        Move to a saved joint pose after confirmation.
        """
        name = arg.strip()
        poses = load_poses()
        if name not in poses:
            print(f"Unknown pose {name!r}. Use 'poses' to list saved poses.")
            return
        target = poses[name]
        print(f"Saved pose '{name}': {target}")
        if not self._confirm("Review the target and collision path.", "MOVE"):
            print("Cancelled.")
            return
        try:
            self.c.move_joints_deg(target)
            print("Saved pose target sent.")
        except Exception as exc:
            print(f"ERROR: {exc}")

    def do_poses(self, arg: str) -> None:
        """poses
        List saved joint poses.
        """
        poses = load_poses()
        if not poses:
            print("No saved poses.")
            return
        for name, pose in poses.items():
            print(f"{name:<20} {pose}")

    def do_quit(self, arg: str) -> bool:
        """quit
        Disconnect the program. This does not automatically disable/release the arm.
        """
        return True

    def do_exit(self, arg: str) -> bool:
        """exit
        Same as quit.
        """
        return self.do_quit(arg)

    def do_EOF(self, arg: str) -> bool:
        print()
        return self.do_quit(arg)


def main() -> int:
    parser = argparse.ArgumentParser(description="PiPER X Linux terminal controller")
    parser.add_argument("--can", default="can0", help="SocketCAN interface (default: can0)")
    parser.add_argument("--speed", type=int, default=15, help="Initial speed percent, 1..50")
    parser.add_argument(
        "--gripper-max-mm",
        type=float,
        default=70.0,
        help="Configured gripper max width, normally 70 or 100 mm",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run a hardware-free simulation for UI/command testing",
    )
    args = parser.parse_args()

    controller = PiperXController(
        can_port=args.can,
        speed_percent=args.speed,
        gripper_max_mm=args.gripper_max_mm,
        dry_run=args.dry_run,
    )
    try:
        fw = controller.connect()
        print(f"Connected: {fw}")
        shell = PiperShell(controller)
        shell.cmdloop()
    except KeyboardInterrupt:
        print("\nInterrupted.")
    except Exception as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        return 1
    finally:
        try:
            controller.disconnect()
        except Exception as exc:
            print(f"Warning during disconnect: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
