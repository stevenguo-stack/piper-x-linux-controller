#!/usr/bin/env python3
"""Persistent taught joint-space waypoints and guarded demo sequences."""
from __future__ import annotations

import json
import math
import os
import tempfile
import time
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Mapping, Sequence

from piper_x_controller import PiperXController


WAYPOINT_LABELS: Mapping[str, str] = {
    "home": "Home / 收臂安全位",
    "pre_grab": "Pre-grab / 抓取前等待位",
    "grab": "Grab / 夹住篮子的位置",
    "lift": "Lift / 提起后的安全位",
    "pre_dump": "Pre-dump / 倒球前等待位",
    "dump": "Dump / 篮子翻转倒球位",
}

SEQUENCE_REQUIREMENTS: Mapping[str, Sequence[str]] = {
    "home": ("home",),
    "grab": ("pre_grab", "grab", "lift"),
    "dump": ("lift", "pre_dump", "dump"),
    "place": ("lift", "grab", "pre_grab", "home"),
    "full": ("home", "pre_grab", "grab", "lift", "pre_dump", "dump"),
}


class WaypointStore:
    """Read/write named six-joint poses in a small JSON file."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()

    @staticmethod
    def _validate_pose(pose: Sequence[float]) -> List[float]:
        if len(pose) != 6:
            raise ValueError("A waypoint must contain exactly six joint angles.")
        values = [float(v) for v in pose]
        if not all(math.isfinite(v) for v in values):
            raise ValueError("Waypoint joint angles must all be finite numbers.")
        return values

    def load_all(self) -> Dict[str, List[float]]:
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Waypoint file is not valid JSON: {self.path}") from exc
        if not isinstance(raw, dict):
            raise RuntimeError(f"Waypoint file must contain a JSON object: {self.path}")
        result: Dict[str, List[float]] = {}
        for name, pose in raw.items():
            if isinstance(name, str) and isinstance(pose, list):
                result[name] = self._validate_pose(pose)
        return result

    def get(self, name: str) -> List[float]:
        poses = self.load_all()
        if name not in poses:
            label = WAYPOINT_LABELS.get(name, name)
            raise KeyError(f"Waypoint not taught: {label}")
        return list(poses[name])

    def has(self, name: str) -> bool:
        try:
            return name in self.load_all()
        except RuntimeError:
            return False

    def missing(self, names: Iterable[str]) -> List[str]:
        poses = self.load_all()
        return [name for name in names if name not in poses]

    def save(self, name: str, pose_deg: Sequence[float]) -> List[float]:
        values = [round(v, 6) for v in self._validate_pose(pose_deg)]
        poses = self.load_all()
        poses[name] = values
        self.path.parent.mkdir(parents=True, exist_ok=True)

        # Atomic replace prevents a half-written JSON file after power loss.
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=str(self.path.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(poses, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self.path)
        except Exception:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
            raise
        return values

    def delete(self, name: str) -> None:
        poses = self.load_all()
        poses.pop(name, None)
        self.path.write_text(
            json.dumps(poses, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


class BasketSequenceRunner:
    """Run taught joint-space basket motions using ordinary Move-J commands.

    No coordinates are hard-coded.  The operator must teach every required pose
    on the actual TK25/PiPER X installation and prove each path at low speed.
    """

    def __init__(
        self,
        controller: PiperXController,
        store: WaypointStore,
        *,
        close_width_mm: float = 8.0,
        force_n: float = 3.0,
        settle_seconds: float = 0.8,
        motion_timeout: float = 20.0,
        progress: Callable[[str], None] | None = None,
    ) -> None:
        self.controller = controller
        self.store = store
        self.close_width_mm = float(close_width_mm)
        self.force_n = float(force_n)
        self.settle_seconds = float(settle_seconds)
        self.motion_timeout = float(motion_timeout)
        self.progress = progress or (lambda _text: None)
        if not 0.0 <= self.close_width_mm <= controller.gripper_max_mm:
            raise ValueError("Close width is outside the configured gripper stroke.")
        if not 0.1 <= self.force_n <= 20.0:
            raise ValueError("Gripper force must be 0.1..20 N.")
        if not 0.0 <= self.settle_seconds <= 10.0:
            raise ValueError("Settle time must be 0..10 seconds.")

    def _check_ready(self) -> None:
        if not self.controller.connected:
            raise RuntimeError("PiPER X is not connected.")
        if not self.controller.motion_armed:
            raise RuntimeError("Motion is locked. Enable the joints first.")

    def _move(self, name: str) -> None:
        self._check_ready()
        self.progress(f"Move to {WAYPOINT_LABELS.get(name, name)}")
        self.controller.move_joints_deg(
            self.store.get(name), wait=True, timeout=self.motion_timeout
        )

    def _sleep(self, seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self._check_ready()
            time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))

    def validate(self, sequence_name: str) -> None:
        required = SEQUENCE_REQUIREMENTS.get(sequence_name)
        if required is None:
            raise ValueError(f"Unknown sequence: {sequence_name}")
        missing = self.store.missing(required)
        if missing:
            labels = ", ".join(WAYPOINT_LABELS.get(name, name) for name in missing)
            raise RuntimeError(f"Teach these waypoints first: {labels}")

    def go_home(self) -> None:
        self.validate("home")
        self._move("home")

    def grab_basket(self) -> None:
        self.validate("grab")
        self._check_ready()
        self.progress("Open gripper")
        self.controller.open_gripper(self.force_n)
        self._sleep(0.4)
        self._move("pre_grab")
        self._move("grab")
        self.progress(
            f"Close gripper to {self.close_width_mm:g} mm at {self.force_n:g} N"
        )
        self.controller.move_gripper_mm(self.close_width_mm, self.force_n)
        self._sleep(self.settle_seconds)
        self._move("lift")

    def dump_balls(self) -> None:
        self.validate("dump")
        self._move("lift")
        self._move("pre_dump")
        self._move("dump")
        self.progress("Hold dump angle")
        self._sleep(self.settle_seconds)
        self._move("pre_dump")
        self._move("lift")

    def place_basket(self) -> None:
        self.validate("place")
        self._move("lift")
        self._move("grab")
        self.progress("Open gripper and release basket")
        self.controller.open_gripper(self.force_n)
        self._sleep(self.settle_seconds)
        self._move("pre_grab")
        self._move("home")

    def full_demo(self) -> None:
        self.validate("full")
        self.go_home()
        self.grab_basket()
        self.dump_balls()
        self.place_basket()
