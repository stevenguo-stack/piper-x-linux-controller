#!/usr/bin/env python3
"""Safety-oriented Linux controller wrapper for AgileX PiPER X.

This wrapper intentionally exposes only the ordinary trajectory interfaces
(move_j / move_p / move_l) and the standard gripper.  It does not expose the
high-risk MIT or move_js modes.
"""
from __future__ import annotations

import math
import platform
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence


@dataclass
class ArmSnapshot:
    connected: bool
    communication_ok: bool
    firmware: Optional[Dict[str, str]]
    joint_rad: Optional[List[float]]
    joint_deg: Optional[List[float]]
    flange_pose: Optional[List[float]]
    arm_status: Optional[Dict[str, Any]]
    enabled_joints: Optional[List[bool]]
    gripper_width_mm: Optional[float]
    gripper_force_n: Optional[float]


class PiperXController:
    """Small, guarded wrapper around the official ``pyAgxArm`` SDK."""

    def __init__(
        self,
        can_port: str = "can0",
        speed_percent: int = 15,
        gripper_max_mm: float = 70.0,
        connect_timeout: float = 15.0,
        dry_run: bool = False,
    ) -> None:
        if not 1 <= speed_percent <= 50:
            raise ValueError("For this controller, speed_percent must be 1..50.")
        if not 1.0 <= gripper_max_mm <= 100.0:
            raise ValueError("gripper_max_mm must be 1..100 mm.")

        self.can_port = can_port
        self.speed_percent = int(speed_percent)
        self.gripper_max_mm = float(gripper_max_mm)
        self.connect_timeout = float(connect_timeout)
        self.dry_run = bool(dry_run)

        self.robot: Any = None
        self.gripper: Any = None
        self.robot_cfg: Optional[dict] = None
        self.firmware: Optional[Dict[str, str]] = None
        self.connected = False
        self.motion_armed = False
        self._lock = threading.RLock()

        # Dry-run state lets the UI and CLI be tested without hardware.
        self._sim_joint_rad = [0.0] * 6
        self._sim_flange_pose = [0.25, 0.0, 0.25, 0.0, math.pi / 2.0, 0.0]
        self._sim_gripper_mm = self.gripper_max_mm
        self._sim_gripper_force_n = 1.0
        self._sim_estopped = False

    # ------------------------------------------------------------------
    # Connection and lifecycle
    # ------------------------------------------------------------------
    @staticmethod
    def _load_sdk() -> Dict[str, Any]:
        try:
            from pyAgxArm import (  # type: ignore
                AgxArmFactory,
                ArmModel,
                create_agx_arm_config,
                resolve_firmware_profile,
            )
        except ImportError as exc:
            raise RuntimeError(
                "pyAgxArm is not installed. Run ./install.sh first."
            ) from exc
        return {
            "AgxArmFactory": AgxArmFactory,
            "ArmModel": ArmModel,
            "create_agx_arm_config": create_agx_arm_config,
            "resolve_firmware_profile": resolve_firmware_profile,
        }

    def connect(self) -> Dict[str, str]:
        with self._lock:
            if self.connected:
                return self.firmware or {}

            if self.dry_run:
                self.connected = True
                self.firmware = {
                    "software_version": "DRY-RUN",
                    "hardware_version": "SIMULATED",
                }
                return self.firmware

            if platform.system() != "Linux":
                raise RuntimeError(
                    "This package is configured for Linux SocketCAN. "
                    "Use Ubuntu/Linux or adapt the CAN backend explicitly."
                )

            sdk = self._load_sdk()
            AgxArmFactory = sdk["AgxArmFactory"]
            ArmModel = sdk["ArmModel"]
            create_cfg = sdk["create_agx_arm_config"]
            resolve_profile = sdk["resolve_firmware_profile"]

            # Probe with the default profile, read firmware, then reconnect with
            # the profile that matches the controller firmware. This follows the
            # official detect_piper_series.py workflow.
            probe_cfg = create_cfg(
                robot=ArmModel.PIPER_X,
                interface="socketcan",
                channel=self.can_port,
                bitrate=1_000_000,
            )
            probe = AgxArmFactory.create_arm(probe_cfg)
            try:
                probe.connect()
                deadline = time.monotonic() + self.connect_timeout
                firmware: Optional[Dict[str, str]] = None
                while time.monotonic() < deadline:
                    firmware = probe.get_firmware(timeout=1.0)
                    if firmware is not None:
                        break
                    time.sleep(0.25)
                if firmware is None:
                    raise TimeoutError(
                        f"Timed out waiting for PiPER X firmware on {self.can_port}. "
                        "Check 24 V power, the official USB-CAN adapter, CAN wiring, "
                        "and that the interface is UP at 1 Mbps."
                    )
                software_version = firmware["software_version"]
                firmware_profile = resolve_profile(
                    ArmModel.PIPER_X, software_version
                )
            finally:
                try:
                    probe.disconnect()
                except Exception:
                    pass

            self.robot_cfg = create_cfg(
                robot=ArmModel.PIPER_X,
                firmeware_version=firmware_profile,
                interface="socketcan",
                channel=self.can_port,
                bitrate=1_000_000,
            )
            self.robot = AgxArmFactory.create_arm(self.robot_cfg)
            self.robot.connect()
            self.gripper = self.robot.init_effector(
                self.robot.OPTIONS.EFFECTOR.AGX_GRIPPER
            )

            deadline = time.monotonic() + self.connect_timeout
            while time.monotonic() < deadline:
                if self.robot.get_joint_angles() is not None:
                    break
                time.sleep(0.05)
            else:
                try:
                    self.robot.disconnect()
                finally:
                    self.robot = None
                    self.gripper = None
                raise TimeoutError(
                    "Firmware was detected, but joint feedback did not arrive. "
                    "Check CAN connection and emergency-stop state."
                )

            # The arm is mounted upright on top of the chassis.
            self.robot.set_installation_pos(
                self.robot.OPTIONS.INSTALLATION_POS.HORIZONTAL
            )
            self.robot.set_speed_percent(self.speed_percent)

            self.firmware = firmware
            self.connected = True
            self.motion_armed = False
            return firmware

    def disconnect(self) -> None:
        """Disconnect communication without automatically releasing the brakes."""
        with self._lock:
            if self.dry_run:
                self.connected = False
                self.motion_armed = False
                return
            if self.robot is not None:
                try:
                    self.robot.disconnect()
                finally:
                    self.robot = None
                    self.gripper = None
                    self.connected = False
                    self.motion_armed = False

    def _require_connected(self) -> None:
        if not self.connected:
            raise RuntimeError("PiPER X is not connected.")

    def _require_motion_armed(self) -> None:
        self._require_connected()
        if not self.motion_armed:
            raise RuntimeError(
                "Motion is locked. Run/press Enable after checking the work area."
            )

    def _require_arm_ready_for_motion(self) -> None:
        """Refuse motion when live feedback reports an error or disabled joint."""
        self._require_motion_armed()
        if self.dry_run:
            if self._sim_estopped:
                self.motion_armed = False
                raise RuntimeError("The simulated arm is emergency-stopped.")
            return

        status = self.robot.get_arm_status()
        if status is not None:
            arm_status = getattr(status.msg, "arm_status", None)
            if arm_status not in (None, 0):
                self.motion_armed = False
                raise RuntimeError(
                    f"Arm status is not normal (arm_status={arm_status}); motion blocked."
                )

        try:
            enabled = list(self.robot.get_joints_enable_status_list())
        except Exception:
            enabled = []
        if enabled and not all(enabled):
            self.motion_armed = False
            raise RuntimeError(
                f"Not all joints are enabled ({enabled}); motion blocked."
            )

    # ------------------------------------------------------------------
    # Safety controls
    # ------------------------------------------------------------------
    def enable(self, timeout: float = 8.0) -> bool:
        self._require_connected()
        if self.dry_run:
            with self._lock:
                self.motion_armed = True
                self._sim_estopped = False
            return True

        # Lock only around each SDK call rather than across the whole timeout.
        # This leaves short opportunities for an electronic-stop request from
        # another UI thread; the physical E-stop is still the primary stop.
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                self._require_connected()
                enabled = bool(self.robot.enable())
            if enabled:
                with self._lock:
                    self.motion_armed = True
                return True
            time.sleep(0.05)
        with self._lock:
            self.motion_armed = False
        return False

    def disable(self, timeout: float = 5.0) -> bool:
        self._require_connected()
        if self.dry_run:
            with self._lock:
                self.motion_armed = False
            return True

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                self._require_connected()
                disabled = bool(self.robot.disable())
            if disabled:
                with self._lock:
                    self.motion_armed = False
                return True
            time.sleep(0.05)
        return False

    def emergency_stop(self) -> None:
        with self._lock:
            self._require_connected()
            if self.dry_run:
                self._sim_estopped = True
                self.motion_armed = False
                return
            self.robot.electronic_emergency_stop()
            self.motion_armed = False

    def reset(self) -> None:
        with self._lock:
            self._require_connected()
            if self.dry_run:
                self._sim_estopped = False
                self.motion_armed = False
                return
            self.robot.reset()
            self.motion_armed = False

    def set_speed_percent(self, percent: int) -> None:
        if not isinstance(percent, int) or not 1 <= percent <= 50:
            raise ValueError("Speed must be an integer from 1 to 50 percent.")
        with self._lock:
            self._require_connected()
            self.speed_percent = percent
            if not self.dry_run:
                self.robot.set_speed_percent(percent)

    # ------------------------------------------------------------------
    # Motion
    # ------------------------------------------------------------------
    def _joint_limits_rad(self) -> Optional[List[Sequence[float]]]:
        if not self.robot_cfg:
            return None
        limits = self.robot_cfg.get("joint_limits")
        if not isinstance(limits, dict):
            return None
        result: List[Sequence[float]] = []
        for i in range(1, 7):
            pair = limits.get(f"joint{i}")
            if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                return None
            result.append(pair)
        return result

    def _validate_joint_targets(self, joints_rad: Sequence[float]) -> None:
        if len(joints_rad) != 6:
            raise ValueError("Exactly six joint angles are required.")
        if not all(math.isfinite(float(x)) for x in joints_rad):
            raise ValueError("Joint angles must be finite numbers.")
        limits = self._joint_limits_rad()
        if limits is None:
            return
        for idx, (value, pair) in enumerate(zip(joints_rad, limits), start=1):
            lo, hi = float(pair[0]), float(pair[1])
            if not lo <= float(value) <= hi:
                raise ValueError(
                    f"J{idx} target {math.degrees(float(value)):.2f}° is outside "
                    f"the SDK limit [{math.degrees(lo):.2f}°, {math.degrees(hi):.2f}°]."
                )

    def move_joints_deg(
        self,
        joints_deg: Sequence[float],
        wait: bool = False,
        timeout: float = 15.0,
    ) -> None:
        joints_rad = [math.radians(float(v)) for v in joints_deg]
        self._validate_joint_targets(joints_rad)
        with self._lock:
            self._require_arm_ready_for_motion()
            if self.dry_run:
                self._sim_joint_rad = joints_rad
                return
            self.robot.move_j(joints_rad)
        if wait and not self.wait_motion_done(timeout=timeout):
            raise TimeoutError(f"PiPER X did not report motion complete within {timeout:.1f}s.")

    def jog_joint_deg(
        self,
        joint_index: int,
        delta_deg: float,
        wait: bool = False,
    ) -> List[float]:
        if joint_index not in range(1, 7):
            raise ValueError("joint_index must be 1..6.")
        if not -5.0 <= float(delta_deg) <= 5.0 or float(delta_deg) == 0.0:
            raise ValueError("Each jog step must be nonzero and within ±5 degrees.")
        snapshot = self.get_snapshot()
        if snapshot.joint_deg is None:
            raise RuntimeError("No joint feedback is available yet.")
        target = list(snapshot.joint_deg)
        target[joint_index - 1] += float(delta_deg)
        self.move_joints_deg(target, wait=wait)
        return target

    @staticmethod
    def _pose_deg_to_sdk(pose: Sequence[float]) -> List[float]:
        if len(pose) != 6:
            raise ValueError("Pose requires x y z roll pitch yaw.")
        values = [float(v) for v in pose]
        if not all(math.isfinite(v) for v in values):
            raise ValueError("Pose values must be finite numbers.")
        x, y, z, roll_deg, pitch_deg, yaw_deg = values
        return [
            x,
            y,
            z,
            math.radians(roll_deg),
            math.radians(pitch_deg),
            math.radians(yaw_deg),
        ]

    def move_pose_deg(
        self,
        pose: Sequence[float],
        linear: bool = False,
        wait: bool = False,
        timeout: float = 15.0,
    ) -> None:
        sdk_pose = self._pose_deg_to_sdk(pose)
        with self._lock:
            self._require_arm_ready_for_motion()
            if self.dry_run:
                self._sim_flange_pose = sdk_pose
                return
            if linear:
                self.robot.move_l(sdk_pose)
            else:
                self.robot.move_p(sdk_pose)
        if wait and not self.wait_motion_done(timeout=timeout):
            raise TimeoutError(f"PiPER X did not report motion complete within {timeout:.1f}s.")

    def jog_cartesian_mm(
        self,
        axis: str,
        delta_mm: float,
        *,
        linear: bool = True,
        wait: bool = False,
        timeout: float = 15.0,
    ) -> List[float]:
        """Nudge the flange in the arm base coordinate frame.

        ``axis`` is one of ``x``, ``y`` or ``z``.  Each request is deliberately
        limited to 20 mm so a GUI button cannot command a large accidental move.
        The current flange orientation is preserved.
        """
        axis = axis.lower().strip()
        if axis not in {"x", "y", "z"}:
            raise ValueError("axis must be x, y, or z.")
        delta_mm = float(delta_mm)
        if not math.isfinite(delta_mm) or delta_mm == 0.0:
            raise ValueError("Cartesian jog must be a finite nonzero distance.")
        if abs(delta_mm) > 20.0:
            raise ValueError("Each Cartesian jog is limited to ±20 mm.")

        snapshot = self.get_snapshot()
        if snapshot.flange_pose is None:
            raise RuntimeError("No flange pose feedback is available yet.")
        x, y, z, roll, pitch, yaw = [float(v) for v in snapshot.flange_pose]
        target = [
            x,
            y,
            z,
            math.degrees(roll),
            math.degrees(pitch),
            math.degrees(yaw),
        ]
        target[{"x": 0, "y": 1, "z": 2}[axis]] += delta_mm / 1000.0
        self.move_pose_deg(target, linear=linear, wait=wait, timeout=timeout)
        return target

    def wait_motion_done(self, timeout: float = 15.0) -> bool:
        self._require_connected()
        if self.dry_run:
            time.sleep(0.1)
            return True
        time.sleep(0.25)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                status = self.robot.get_arm_status()
            if status is not None and getattr(status.msg, "motion_status", None) == 0:
                return True
            time.sleep(0.05)
        return False

    # ------------------------------------------------------------------
    # Gripper
    # ------------------------------------------------------------------
    def move_gripper_mm(self, width_mm: float, force_n: float = 1.0) -> None:
        width_mm = float(width_mm)
        force_n = float(force_n)
        if not 0.0 <= width_mm <= self.gripper_max_mm:
            raise ValueError(
                f"Gripper width must be 0..{self.gripper_max_mm:g} mm."
            )
        if not 0.1 <= force_n <= 20.0:
            raise ValueError("Gripper force must be 0.1..20 N in this UI.")
        with self._lock:
            self._require_arm_ready_for_motion()
            if self.dry_run:
                self._sim_gripper_mm = width_mm
                self._sim_gripper_force_n = force_n
                return
            if self.gripper is None:
                raise RuntimeError("The standard AGX gripper is not initialized.")
            self.gripper.move_gripper_m(
                value=width_mm / 1000.0,
                force=force_n,
            )

    def open_gripper(self, force_n: float = 1.0) -> None:
        self.move_gripper_mm(self.gripper_max_mm, force_n)

    def close_gripper(self, force_n: float = 1.0) -> None:
        self.move_gripper_mm(0.0, force_n)

    # ------------------------------------------------------------------
    # State reading
    # ------------------------------------------------------------------
    def get_snapshot(self) -> ArmSnapshot:
        with self._lock:
            if not self.connected:
                return ArmSnapshot(
                    connected=False,
                    communication_ok=False,
                    firmware=self.firmware,
                    joint_rad=None,
                    joint_deg=None,
                    flange_pose=None,
                    arm_status=None,
                    enabled_joints=None,
                    gripper_width_mm=None,
                    gripper_force_n=None,
                )

            if self.dry_run:
                arm_status = {
                    "arm_status": 1 if self._sim_estopped else 0,
                    "motion_status": 0,
                    "ctrl_mode": 1,
                    "mode_feedback": 1,
                }
                return ArmSnapshot(
                    connected=True,
                    communication_ok=True,
                    firmware=self.firmware,
                    joint_rad=list(self._sim_joint_rad),
                    joint_deg=[math.degrees(v) for v in self._sim_joint_rad],
                    flange_pose=list(self._sim_flange_pose),
                    arm_status=arm_status,
                    enabled_joints=[self.motion_armed] * 6,
                    gripper_width_mm=self._sim_gripper_mm,
                    gripper_force_n=self._sim_gripper_force_n,
                )

            joint_msg = self.robot.get_joint_angles()
            joint_rad = list(joint_msg.msg) if joint_msg is not None else None
            joint_deg = (
                [math.degrees(float(v)) for v in joint_rad]
                if joint_rad is not None
                else None
            )

            flange_msg = self.robot.get_flange_pose()
            flange_pose = list(flange_msg.msg) if flange_msg is not None else None

            status_msg = self.robot.get_arm_status()
            arm_status: Optional[Dict[str, Any]] = None
            if status_msg is not None:
                msg = status_msg.msg
                arm_status = {
                    "ctrl_mode": getattr(msg, "ctrl_mode", None),
                    "arm_status": getattr(msg, "arm_status", None),
                    "mode_feedback": getattr(msg, "mode_feedback", None),
                    "teach_status": getattr(msg, "teach_status", None),
                    "motion_status": getattr(msg, "motion_status", None),
                    "trajectory_num": getattr(msg, "trajectory_num", None),
                    "err_status": repr(getattr(msg, "err_status", None)),
                }

            try:
                enabled_joints = list(self.robot.get_joints_enable_status_list())
            except Exception:
                enabled_joints = None

            # Keep the software motion lock conservative if live feedback shows
            # an arm error or a disabled joint.
            if (
                arm_status is not None
                and arm_status.get("arm_status") not in (None, 0)
            ) or (enabled_joints is not None and not all(enabled_joints)):
                self.motion_armed = False

            gripper_width_mm: Optional[float] = None
            gripper_force_n: Optional[float] = None
            if self.gripper is not None:
                try:
                    gs = self.gripper.get_gripper_status()
                    if gs is not None:
                        # In width mode, value is documented in meters.
                        gripper_width_mm = float(gs.msg.value) * 1000.0
                        gripper_force_n = float(gs.msg.force)
                except Exception:
                    pass

            try:
                communication_ok = bool(self.robot.is_ok())
            except Exception:
                communication_ok = False

            return ArmSnapshot(
                connected=True,
                communication_ok=communication_ok,
                firmware=self.firmware,
                joint_rad=joint_rad,
                joint_deg=joint_deg,
                flange_pose=flange_pose,
                arm_status=arm_status,
                enabled_joints=enabled_joints,
                gripper_width_mm=gripper_width_mm,
                gripper_force_n=gripper_force_n,
            )
