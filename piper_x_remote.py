#!/usr/bin/env python3
"""Touch-friendly remote controller for AgileX PiPER X on Ubuntu/Linux.

The remote UI is intentionally conservative:
- only ordinary Move-J / Move-L / gripper APIs are used;
- one click is limited to a small relative step;
- named basket poses must be taught from the real arm before task buttons work;
- task sequences stop between every waypoint and check motion completion;
- the software E-stop stays available while a background task is running.

The physical E-stop and an external power cut-off remain the primary safety devices.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from tkinter import (
    BOTH,
    END,
    HORIZONTAL,
    LEFT,
    RIGHT,
    X,
    Y,
    BooleanVar,
    DoubleVar,
    StringVar,
    Tk,
    messagebox,
)
from tkinter import scrolledtext, ttk
from typing import Any, Callable, Dict, Iterable, Optional

from piper_x_controller import ArmSnapshot, PiperXController


POSE_SLOTS = (
    ("safe", "安全收回位"),
    ("pickup_approach", "抓取前位置"),
    ("pickup", "抓取位置"),
    ("lift", "抬起位置"),
    ("dump_approach", "倒球前位置"),
    ("dump", "倒球位置"),
)


class BasketTaskStore:
    """Persist taught joint poses and gripper settings as JSON."""

    VERSION = 1

    def __init__(self, path: Path, gripper_max_mm: float) -> None:
        self.path = path.expanduser()
        self.gripper_max_mm = float(gripper_max_mm)
        self.data: Dict[str, Any] = self._default_data()
        self.load()

    def _default_data(self) -> Dict[str, Any]:
        return {
            "version": self.VERSION,
            "poses": {},
            "gripper": {
                "open_mm": self.gripper_max_mm,
                "grip_mm": 8.0,
                "force_n": 3.0,
                "settle_s": 0.8,
                "dump_hold_s": 1.5,
            },
        }

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("top level must be an object")
            if raw.get("version") != self.VERSION:
                raise ValueError(
                    f"unsupported task file version: {raw.get('version')!r}"
                )
            poses = raw.get("poses", {})
            gripper = raw.get("gripper", {})
            if not isinstance(poses, dict) or not isinstance(gripper, dict):
                raise ValueError("poses/gripper must be objects")
            merged = self._default_data()
            merged["poses"].update(poses)
            merged["gripper"].update(gripper)
            self.data = merged
        except Exception as exc:
            backup = self.path.with_suffix(self.path.suffix + ".invalid")
            try:
                backup.parent.mkdir(parents=True, exist_ok=True)
                self.path.replace(backup)
            except Exception:
                pass
            self.data = self._default_data()
            raise RuntimeError(
                f"任务配置文件损坏，已尝试移到 {backup}: {exc}"
            ) from exc

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp, self.path)

    def get_pose(self, key: str) -> Optional[list[float]]:
        pose = self.data.get("poses", {}).get(key)
        if not isinstance(pose, dict):
            return None
        joints = pose.get("joint_deg")
        if (
            not isinstance(joints, list)
            or len(joints) != 6
            or not all(isinstance(v, (int, float)) and math.isfinite(float(v)) for v in joints)
        ):
            return None
        return [float(v) for v in joints]

    def set_pose(self, key: str, snapshot: ArmSnapshot) -> None:
        if snapshot.joint_deg is None or len(snapshot.joint_deg) != 6:
            raise RuntimeError("当前没有完整的六关节反馈，无法记录位置。")
        flange = list(snapshot.flange_pose) if snapshot.flange_pose is not None else None
        self.data.setdefault("poses", {})[key] = {
            "joint_deg": [round(float(v), 6) for v in snapshot.joint_deg],
            "flange_pose_m_rad": flange,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
        self.save()

    def clear_pose(self, key: str) -> None:
        self.data.setdefault("poses", {}).pop(key, None)
        self.save()

    def set_gripper(self, **values: float) -> None:
        self.data.setdefault("gripper", {}).update(values)
        self.save()


class PiperXRemoteGUI:
    POLL_MS = 350

    def __init__(
        self,
        root: Tk,
        controller: PiperXController,
        task_store: BasketTaskStore,
    ) -> None:
        self.root = root
        self.c = controller
        self.store = task_store
        self.executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="piper-remote")
        self._closing = False
        self._busy = 0
        self._poll_inflight = False
        self._ui_lock = threading.Lock()
        self._sequence_cancel = threading.Event()
        self._last_snapshot: Optional[ArmSnapshot] = None

        self.root.title("NXTektal · PiPER X 遥控器")
        self.root.minsize(1120, 760)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.connection_text = StringVar(value="未连接")
        self.arm_text = StringVar(value="动作已锁定")
        self.firmware_text = StringVar(value="—")
        self.can_var = StringVar(value=self.c.can_port)
        self.speed_var = StringVar(value=str(self.c.speed_percent))
        self.move_step_mm_var = StringVar(value="10")
        self.rotate_step_deg_var = StringVar(value="2")
        self.gripper_width_var = StringVar(value=f"{self.c.gripper_max_mm:.1f}")
        self.gripper_force_var = StringVar(value="3.0")
        self.auto_confirm_var = BooleanVar(value=False)
        self.live_pose_text = StringVar(value="X —   Y —   Z —   R —   P —   Yaw —")
        self.live_joint_text = StringVar(value="J1— J2— J3— J4— J5— J6—")
        self.pose_status_vars = {key: StringVar(value="未记录") for key, _ in POSE_SLOTS}

        g = self.store.data["gripper"]
        self.task_open_mm_var = StringVar(value=f"{float(g['open_mm']):.1f}")
        self.task_grip_mm_var = StringVar(value=f"{float(g['grip_mm']):.1f}")
        self.task_force_n_var = StringVar(value=f"{float(g['force_n']):.1f}")
        self.task_settle_s_var = StringVar(value=f"{float(g['settle_s']):.1f}")
        self.task_dump_hold_s_var = StringVar(value=f"{float(g['dump_hold_s']):.1f}")

        self.motion_widgets: list[Any] = []
        self.sequence_widgets: list[Any] = []
        self.sequence_buttons: Dict[str, Any] = {}
        self._build_ui()
        self._refresh_pose_status()
        self._set_controls()
        self.root.after(self.POLL_MS, self._schedule_poll)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=10)
        outer.pack(fill=BOTH, expand=True)

        top = ttk.Frame(outer)
        top.pack(fill=X)
        self._build_connection(top)
        self._build_safety(top)

        status_strip = ttk.LabelFrame(outer, text="实时状态")
        status_strip.pack(fill=X, pady=(8, 0))
        ttk.Label(status_strip, textvariable=self.live_pose_text).pack(
            anchor="w", padx=10, pady=(6, 2)
        )
        ttk.Label(status_strip, textvariable=self.live_joint_text).pack(
            anchor="w", padx=10, pady=(2, 6)
        )

        tabs = ttk.Notebook(outer)
        tabs.pack(fill=BOTH, expand=True, pady=(8, 0))

        remote_tab = ttk.Frame(tabs, padding=10)
        task_tab = ttk.Frame(tabs, padding=10)
        log_tab = ttk.Frame(tabs, padding=10)
        tabs.add(remote_tab, text="遥控操作")
        tabs.add(task_tab, text="篮子动作教学")
        tabs.add(log_tab, text="状态与日志")

        self._build_remote(remote_tab)
        self._build_task(task_tab)
        self._build_log(log_tab)

    def _build_connection(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="连接")
        frame.pack(side=LEFT, fill=BOTH, expand=True, padx=(0, 5))

        ttk.Label(frame, text="CAN接口").grid(row=0, column=0, padx=8, pady=6)
        self.can_entry = ttk.Entry(frame, textvariable=self.can_var, width=12)
        self.can_entry.grid(row=0, column=1, padx=4, pady=6)
        mode = "模拟模式（不控制真机）" if self.c.dry_run else "真实机械臂"
        ttk.Label(frame, text=mode).grid(row=0, column=2, padx=8, pady=6, sticky="w")

        self.connect_btn = ttk.Button(frame, text="连接", command=self.connect)
        self.disconnect_btn = ttk.Button(frame, text="断开", command=self.disconnect)
        self.connect_btn.grid(row=1, column=0, padx=8, pady=6, sticky="ew")
        self.disconnect_btn.grid(row=1, column=1, padx=4, pady=6, sticky="ew")
        ttk.Label(frame, textvariable=self.connection_text).grid(
            row=1, column=2, padx=8, pady=6, sticky="w"
        )

        ttk.Label(frame, text="固件").grid(row=2, column=0, padx=8, pady=(0, 6))
        ttk.Label(frame, textvariable=self.firmware_text).grid(
            row=2, column=1, columnspan=2, padx=4, pady=(0, 6), sticky="w"
        )
        frame.columnconfigure(2, weight=1)

    def _build_safety(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="使能与安全")
        frame.pack(side=RIGHT, fill=BOTH, expand=True, padx=(5, 0))

        self.enable_btn = ttk.Button(frame, text="使能机械臂", command=self.enable)
        self.disable_btn = ttk.Button(frame, text="解除使能", command=self.disable)
        self.reset_btn = ttk.Button(frame, text="故障复位", command=self.reset)
        self.estop_btn = ttk.Button(frame, text="软件急停", command=self.estop)
        self.enable_btn.grid(row=0, column=0, padx=8, pady=7, sticky="ew")
        self.disable_btn.grid(row=0, column=1, padx=8, pady=7, sticky="ew")
        self.estop_btn.grid(row=1, column=0, padx=8, pady=7, sticky="ew")
        self.reset_btn.grid(row=1, column=1, padx=8, pady=7, sticky="ew")
        ttk.Label(
            frame,
            text="实体急停必须放在手边；底盘移动时机械臂应收回，机械臂动作时底盘必须停车。",
            wraplength=430,
        ).grid(row=2, column=0, columnspan=2, padx=8, pady=(0, 4), sticky="w")
        ttk.Label(frame, textvariable=self.arm_text).grid(
            row=3, column=0, columnspan=2, padx=8, pady=(0, 7), sticky="w"
        )
        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)

    def _build_remote(self, frame: ttk.Frame) -> None:
        controls = ttk.Frame(frame)
        controls.pack(fill=X)

        speed_box = ttk.LabelFrame(controls, text="速度")
        speed_box.pack(side=LEFT, fill=X, expand=True, padx=(0, 6))
        self.speed_scale = ttk.Scale(
            speed_box,
            from_=1,
            to=50,
            orient=HORIZONTAL,
            command=lambda value: self.speed_var.set(str(int(float(value)))),
        )
        self.speed_scale.set(self.c.speed_percent)
        self.speed_scale.pack(side=LEFT, fill=X, expand=True, padx=8, pady=8)
        ttk.Label(speed_box, textvariable=self.speed_var, width=4).pack(side=LEFT)
        self.speed_apply_btn = ttk.Button(speed_box, text="应用", command=self.apply_speed)
        self.speed_apply_btn.pack(side=LEFT, padx=8)

        step_box = ttk.LabelFrame(controls, text="每次移动")
        step_box.pack(side=LEFT, padx=6)
        ttk.Label(step_box, text="位移").grid(row=0, column=0, padx=(8, 3), pady=8)
        move_step = ttk.Combobox(
            step_box,
            textvariable=self.move_step_mm_var,
            values=("2", "5", "10", "20"),
            width=6,
            state="readonly",
        )
        move_step.grid(row=0, column=1, padx=3, pady=8)
        ttk.Label(step_box, text="mm").grid(row=0, column=2, padx=(0, 8), pady=8)
        ttk.Label(step_box, text="旋转").grid(row=0, column=3, padx=(8, 3), pady=8)
        rot_step = ttk.Combobox(
            step_box,
            textvariable=self.rotate_step_deg_var,
            values=("0.5", "1", "2", "5"),
            width=6,
            state="readonly",
        )
        rot_step.grid(row=0, column=4, padx=3, pady=8)
        ttk.Label(step_box, text="°").grid(row=0, column=5, padx=(0, 8), pady=8)

        body = ttk.Frame(frame)
        body.pack(fill=BOTH, expand=True, pady=(10, 0))

        xyz = ttk.LabelFrame(body, text="末端位置遥控（基座坐标系）")
        xyz.pack(side=LEFT, fill=BOTH, expand=True, padx=(0, 5))
        ttk.Label(
            xyz,
            text="默认约定：+X向前、+Y向左、+Z向上。第一次请以2–5 mm空载验证实际方向。",
            wraplength=480,
        ).grid(row=0, column=0, columnspan=5, padx=8, pady=(8, 12), sticky="w")

        buttons = [
            ("前  +X", 1, 2, (1, 0, 0)),
            ("后  −X", 3, 2, (-1, 0, 0)),
            ("左  +Y", 2, 1, (0, 1, 0)),
            ("右  −Y", 2, 3, (0, -1, 0)),
            ("上  +Z", 1, 4, (0, 0, 1)),
            ("下  −Z", 3, 4, (0, 0, -1)),
        ]
        for text, row, col, axis in buttons:
            btn = ttk.Button(
                xyz,
                text=text,
                command=lambda a=axis: self.cartesian_jog(*a),
                width=13,
            )
            btn.grid(row=row, column=col, padx=8, pady=8, ipadx=6, ipady=10)
            self.motion_widgets.append(btn)
        ttk.Label(xyz, text="以机械臂底座为参考").grid(
            row=2, column=2, padx=8, pady=8
        )
        for col in range(5):
            xyz.columnconfigure(col, weight=1)

        orient = ttk.LabelFrame(body, text="末端姿态 / 翻腕")
        orient.pack(side=RIGHT, fill=BOTH, expand=True, padx=(5, 0))
        ttk.Label(
            orient,
            text=(
                "Roll/Pitch/Yaw是末端姿态角。倒球通常主要使用Roll或Pitch，具体轴取决于夹爪和横梁方向。"
            ),
            wraplength=470,
        ).grid(row=0, column=0, columnspan=3, padx=8, pady=(8, 12), sticky="w")

        rotations = (
            ("Roll −", 1, 0, (0, -1)),
            ("Roll +", 1, 2, (0, 1)),
            ("Pitch −", 2, 0, (1, -1)),
            ("Pitch +", 2, 2, (1, 1)),
            ("Yaw −", 3, 0, (2, -1)),
            ("Yaw +", 3, 2, (2, 1)),
        )
        for text, row, col, args in rotations:
            btn = ttk.Button(
                orient,
                text=text,
                command=lambda a=args: self.orientation_jog(*a),
                width=13,
            )
            btn.grid(row=row, column=col, padx=8, pady=8, ipadx=6, ipady=8)
            self.motion_widgets.append(btn)
        ttk.Label(orient, text="小角度点动").grid(row=2, column=1, padx=8, pady=8)

        gripper = ttk.LabelFrame(orient, text="夹爪")
        gripper.grid(row=4, column=0, columnspan=3, padx=8, pady=(14, 8), sticky="ew")
        ttk.Label(gripper, text="宽度(mm)").grid(row=0, column=0, padx=5, pady=6)
        ttk.Entry(gripper, textvariable=self.gripper_width_var, width=8).grid(
            row=0, column=1, padx=5, pady=6
        )
        ttk.Label(gripper, text="力(N)").grid(row=0, column=2, padx=5, pady=6)
        ttk.Entry(gripper, textvariable=self.gripper_force_var, width=8).grid(
            row=0, column=3, padx=5, pady=6
        )
        open_btn = ttk.Button(gripper, text="打开", command=self.open_gripper)
        move_btn = ttk.Button(gripper, text="移动到宽度", command=self.move_gripper)
        close_btn = ttk.Button(gripper, text="夹紧", command=self.close_gripper)
        open_btn.grid(row=1, column=0, padx=5, pady=7, sticky="ew")
        move_btn.grid(row=1, column=1, columnspan=2, padx=5, pady=7, sticky="ew")
        close_btn.grid(row=1, column=3, padx=5, pady=7, sticky="ew")
        self.motion_widgets.extend([open_btn, move_btn, close_btn])
        for col in range(4):
            gripper.columnconfigure(col, weight=1)
        for col in range(3):
            orient.columnconfigure(col, weight=1)

    def _build_task(self, frame: ttk.Frame) -> None:
        ttk.Label(
            frame,
            text=(
                "先用遥控按钮把机械臂慢速移动到每个真实位置，然后记录当前六关节角度。"
                "程序不会预设任何抓取/倒球角度，避免机械臂到货后因安装方向不同发生碰撞。"
            ),
            wraplength=1040,
        ).pack(anchor="w", pady=(0, 10))

        pose_frame = ttk.LabelFrame(frame, text="教学位置")
        pose_frame.pack(fill=X)
        ttk.Label(pose_frame, text="位置").grid(row=0, column=0, padx=8, pady=6)
        ttk.Label(pose_frame, text="状态").grid(row=0, column=1, padx=8, pady=6)
        ttk.Label(pose_frame, text="操作").grid(row=0, column=2, columnspan=3, padx=8, pady=6)

        for row, (key, label) in enumerate(POSE_SLOTS, start=1):
            ttk.Label(pose_frame, text=label, width=16).grid(
                row=row, column=0, padx=8, pady=5, sticky="w"
            )
            ttk.Label(pose_frame, textvariable=self.pose_status_vars[key], width=42).grid(
                row=row, column=1, padx=8, pady=5, sticky="w"
            )
            record = ttk.Button(
                pose_frame,
                text="记录当前",
                command=lambda k=key, l=label: self.record_pose(k, l),
            )
            go = ttk.Button(
                pose_frame,
                text="前往",
                command=lambda k=key, l=label: self.go_pose(k, l),
            )
            clear = ttk.Button(
                pose_frame,
                text="清除",
                command=lambda k=key, l=label: self.clear_pose(k, l),
            )
            record.grid(row=row, column=2, padx=4, pady=5)
            go.grid(row=row, column=3, padx=4, pady=5)
            clear.grid(row=row, column=4, padx=4, pady=5)
            self.motion_widgets.extend([record, go])
        pose_frame.columnconfigure(1, weight=1)

        config = ttk.LabelFrame(frame, text="任务夹爪参数")
        config.pack(fill=X, pady=(10, 0))
        fields = (
            ("打开宽度(mm)", self.task_open_mm_var),
            ("夹紧宽度(mm)", self.task_grip_mm_var),
            ("夹持力(N)", self.task_force_n_var),
            ("夹紧等待(s)", self.task_settle_s_var),
            ("倒球停留(s)", self.task_dump_hold_s_var),
        )
        for col, (label, var) in enumerate(fields):
            ttk.Label(config, text=label).grid(row=0, column=col, padx=7, pady=(7, 2))
            ttk.Entry(config, textvariable=var, width=11).grid(
                row=1, column=col, padx=7, pady=(2, 7)
            )
            config.columnconfigure(col, weight=1)
        save_params = ttk.Button(config, text="保存参数", command=self.save_task_parameters)
        save_params.grid(row=0, column=len(fields), rowspan=2, padx=8, pady=8, sticky="ns")

        confirm = ttk.Checkbutton(
            frame,
            text="我已确认：TK25已停车、动作路径已逐段验证、篮子总重量未超过机械臂能力、实体急停可立即触达",
            variable=self.auto_confirm_var,
            command=self._set_controls,
        )
        confirm.pack(anchor="w", pady=(12, 5))

        actions = ttk.LabelFrame(frame, text="一键任务")
        actions.pack(fill=X, pady=(4, 0))
        grab = ttk.Button(actions, text="抓起篮子", command=lambda: self.run_sequence("grab"))
        dump = ttk.Button(actions, text="翻转倒球", command=lambda: self.run_sequence("dump"))
        place = ttk.Button(actions, text="放回篮子", command=lambda: self.run_sequence("place"))
        full = ttk.Button(actions, text="完整循环", command=lambda: self.run_sequence("full"))
        cancel = ttk.Button(actions, text="取消序列 / 软件急停", command=self.cancel_sequence)
        for col, btn in enumerate((grab, dump, place, full, cancel)):
            btn.grid(row=0, column=col, padx=8, pady=10, sticky="ew", ipadx=5, ipady=7)
            actions.columnconfigure(col, weight=1)
        self.sequence_widgets.extend([grab, dump, place, full])
        self.sequence_buttons = {
            "grab": grab,
            "dump": dump,
            "place": place,
            "full": full,
        }
        self.estop_sequence_btn = cancel

        ttk.Label(
            frame,
            text=(
                "抓起：打开→抓取前→抓取位→夹紧→抬起。  "
                "倒球：倒球前→倒球位→停留→倒球前。  "
                "放回：抬起→抓取位→打开→抓取前→安全位。"
            ),
            wraplength=1040,
        ).pack(anchor="w", pady=(8, 0))

    def _build_log(self, frame: ttk.Frame) -> None:
        self.status_text = scrolledtext.ScrolledText(frame, height=15, wrap="word")
        self.status_text.pack(fill=BOTH, expand=True)
        self.status_text.configure(state="disabled")
        ttk.Separator(frame, orient=HORIZONTAL).pack(fill=X, pady=8)
        self.log_text = scrolledtext.ScrolledText(frame, height=12, wrap="word")
        self.log_text.pack(fill=BOTH, expand=True)
        self.log_text.configure(state="disabled")

    # ------------------------------------------------------------------
    # Generic background work
    # ------------------------------------------------------------------
    def log(self, text: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert(END, f"[{stamp}] {text}\n")
        self.log_text.see(END)
        self.log_text.configure(state="disabled")

    def _task(
        self,
        label: str,
        fn: Callable[[], Any],
        on_success: Optional[Callable[[Any], None]] = None,
        *,
        quiet: bool = False,
        sequence: bool = False,
    ) -> None:
        with self._ui_lock:
            self._busy += 1
        if not quiet:
            self.log(f"{label} …")
        self._set_controls()

        def worker() -> tuple[bool, Any]:
            try:
                return True, fn()
            except Exception as exc:
                return False, exc

        future = self.executor.submit(worker)

        def done() -> None:
            if self._closing:
                return
            ok, value = future.result()
            with self._ui_lock:
                self._busy = max(0, self._busy - 1)
            if sequence:
                self._sequence_cancel.clear()
            if ok:
                try:
                    if on_success is not None:
                        on_success(value)
                    if not quiet:
                        self.log(f"{label}：完成")
                except Exception as exc:
                    self.log(f"{label}：界面更新错误 — {exc}")
                    messagebox.showerror("PiPER X", str(exc), parent=self.root)
            else:
                self.log(f"{label}：错误 — {value}")
                messagebox.showerror("PiPER X", str(value), parent=self.root)
            self._set_controls()

        future.add_done_callback(lambda _: self.root.after(0, done))

    def _require_not_busy(self) -> bool:
        if self._busy > 0:
            messagebox.showwarning("PiPER X", "当前还有动作正在执行。", parent=self.root)
            return False
        return True

    # ------------------------------------------------------------------
    # Connection / safety
    # ------------------------------------------------------------------
    def connect(self) -> None:
        if not self._require_not_busy():
            return
        self.c.can_port = self.can_var.get().strip() or "can0"

        def connected(fw: Dict[str, str]) -> None:
            self.connection_text.set("已连接")
            self.firmware_text.set(
                f"{fw.get('software_version', '?')} / {fw.get('hardware_version', '?')}"
            )

        self._task("连接机械臂", self.c.connect, connected)

    def disconnect(self) -> None:
        if self.c.motion_armed and not messagebox.askyesno(
            "断开连接",
            "当前机械臂已使能。断开通信不会自动卸载或断电，仍要断开吗？",
            parent=self.root,
        ):
            return
        self._task("断开连接", self.c.disconnect)

    def enable(self) -> None:
        if not messagebox.askyesno(
            "使能机械臂",
            "确认底盘完全停车、机械臂周围无人、实体急停可立即按下。\n\n现在使能六个关节？",
            parent=self.root,
        ):
            return

        def check(result: bool) -> None:
            if not result:
                raise RuntimeError("关节未能在超时内全部使能。")

        self._task("使能机械臂", self.c.enable, check)

    def disable(self) -> None:
        if not messagebox.askyesno(
            "解除使能",
            "解除使能后机械臂可能失去保持力。请先支撑机械臂和负载。继续？",
            parent=self.root,
        ):
            return
        self._task("解除使能", self.c.disable)

    def estop(self) -> None:
        self._sequence_cancel.set()
        try:
            self.c.emergency_stop()
            self.log("已发送软件急停；请根据需要同时按实体急停或切断机械臂电源。")
        except Exception as exc:
            self.log(f"软件急停失败：{exc}")
            messagebox.showerror("软件急停", str(exc), parent=self.root)
        self._set_controls()

    def reset(self) -> None:
        if not messagebox.askyesno(
            "故障复位",
            "仅在排除碰撞、限位、通信或急停原因后复位。复位后仍需重新使能。继续？",
            parent=self.root,
        ):
            return
        self._task("故障复位", self.c.reset)

    def cancel_sequence(self) -> None:
        self._sequence_cancel.set()
        self.estop()

    def apply_speed(self) -> None:
        try:
            speed = int(self.speed_var.get())
        except ValueError:
            messagebox.showerror("速度", "速度必须是1到50的整数。", parent=self.root)
            return
        self._task(f"设置速度 {speed}%", lambda: self.c.set_speed_percent(speed))

    # ------------------------------------------------------------------
    # Remote motion
    # ------------------------------------------------------------------
    def _live_pose_deg(self) -> list[float]:
        snap = self.c.get_snapshot()
        if snap.flange_pose is None:
            raise RuntimeError("没有收到末端位姿反馈。")
        x, y, z, roll, pitch, yaw = [float(v) for v in snap.flange_pose]
        return [x, y, z, math.degrees(roll), math.degrees(pitch), math.degrees(yaw)]

    def _move_pose_checked(self, pose_deg: Iterable[float], timeout: float = 15.0) -> None:
        self.c.move_pose_deg(list(pose_deg), linear=True, wait=False)
        if not self.c.wait_motion_done(timeout=timeout):
            raise TimeoutError("机械臂未在规定时间内到达目标位置。")

    def cartesian_jog(self, x_sign: int, y_sign: int, z_sign: int) -> None:
        try:
            step_mm = float(self.move_step_mm_var.get())
        except ValueError:
            messagebox.showerror("位移步长", "请输入有效的毫米数。", parent=self.root)
            return
        if not 0 < step_mm <= 20:
            messagebox.showerror("位移步长", "单次位移必须大于0且不超过20 mm。", parent=self.root)
            return
        step_m = step_mm / 1000.0

        def action() -> list[float]:
            pose = self._live_pose_deg()
            pose[0] += x_sign * step_m
            pose[1] += y_sign * step_m
            pose[2] += z_sign * step_m
            self._move_pose_checked(pose)
            return pose

        axis = f"ΔX={x_sign*step_mm:g}, ΔY={y_sign*step_mm:g}, ΔZ={z_sign*step_mm:g} mm"
        self._task(f"末端点动 {axis}", action)

    def orientation_jog(self, axis_index: int, sign: int) -> None:
        try:
            step_deg = float(self.rotate_step_deg_var.get())
        except ValueError:
            messagebox.showerror("旋转步长", "请输入有效角度。", parent=self.root)
            return
        if not 0 < step_deg <= 5:
            messagebox.showerror("旋转步长", "单次旋转必须大于0且不超过5°。", parent=self.root)
            return

        def action() -> list[float]:
            pose = self._live_pose_deg()
            pose[3 + axis_index] += sign * step_deg
            self._move_pose_checked(pose)
            return pose

        axis_name = ("Roll", "Pitch", "Yaw")[axis_index]
        self._task(f"{axis_name} {sign*step_deg:+g}°", action)

    def _gripper_values(self) -> tuple[float, float]:
        width = float(self.gripper_width_var.get())
        force = float(self.gripper_force_var.get())
        return width, force

    def move_gripper(self) -> None:
        try:
            width, force = self._gripper_values()
        except Exception:
            messagebox.showerror("夹爪", "宽度和夹持力必须是数字。", parent=self.root)
            return
        self._task(
            f"夹爪 {width:g} mm / {force:g} N",
            lambda: self.c.move_gripper_mm(width, force),
        )

    def open_gripper(self) -> None:
        try:
            _, force = self._gripper_values()
        except Exception:
            messagebox.showerror("夹爪", "夹持力必须是数字。", parent=self.root)
            return
        self.gripper_width_var.set(f"{self.c.gripper_max_mm:.1f}")
        self._task("打开夹爪", lambda: self.c.open_gripper(force))

    def close_gripper(self) -> None:
        try:
            _, force = self._gripper_values()
        except Exception:
            messagebox.showerror("夹爪", "夹持力必须是数字。", parent=self.root)
            return
        if not messagebox.askyesno(
            "夹紧",
            "确认手指、线缆和脆弱物体均已避开。夹爪移动到0 mm？",
            parent=self.root,
        ):
            return
        self.gripper_width_var.set("0.0")
        self._task("夹紧夹爪", lambda: self.c.close_gripper(force))

    # ------------------------------------------------------------------
    # Pose teaching / task sequences
    # ------------------------------------------------------------------
    def _refresh_pose_status(self) -> None:
        for key, _ in POSE_SLOTS:
            pose = self.store.get_pose(key)
            if pose is None:
                self.pose_status_vars[key].set("未记录")
            else:
                compact = ", ".join(f"{v:.1f}°" for v in pose)
                self.pose_status_vars[key].set(compact)
        self._set_controls()

    def record_pose(self, key: str, label: str) -> None:
        if not messagebox.askyesno(
            "记录教学位置",
            f"将当前真实六关节角度保存为“{label}”？\n\n请确认该位置和完整进出路径都安全。",
            parent=self.root,
        ):
            return
        try:
            snap = self.c.get_snapshot()
            self.store.set_pose(key, snap)
            self._refresh_pose_status()
            self.log(f"已记录：{label}")
        except Exception as exc:
            messagebox.showerror("记录位置", str(exc), parent=self.root)

    def clear_pose(self, key: str, label: str) -> None:
        if not messagebox.askyesno(
            "清除位置", f"清除“{label}”的记录？", parent=self.root
        ):
            return
        self.store.clear_pose(key)
        self._refresh_pose_status()
        self.log(f"已清除：{label}")

    def _move_joint_pose_checked(self, joints_deg: list[float], timeout: float = 20.0) -> None:
        self.c.move_joints_deg(joints_deg, wait=False)
        if not self.c.wait_motion_done(timeout=timeout):
            raise TimeoutError("机械臂未在规定时间内到达教学位置。")

    def go_pose(self, key: str, label: str) -> None:
        pose = self.store.get_pose(key)
        if pose is None:
            messagebox.showerror("教学位置", f"“{label}”尚未记录。", parent=self.root)
            return
        if not messagebox.askyesno(
            "前往教学位置",
            f"前往“{label}”？\n\n请再次确认整个运动路径没有碰撞。",
            parent=self.root,
        ):
            return
        self._task(label, lambda: self._move_joint_pose_checked(pose))

    def _task_parameters(self, persist: bool = False) -> Dict[str, float]:
        try:
            values = {
                "open_mm": float(self.task_open_mm_var.get()),
                "grip_mm": float(self.task_grip_mm_var.get()),
                "force_n": float(self.task_force_n_var.get()),
                "settle_s": float(self.task_settle_s_var.get()),
                "dump_hold_s": float(self.task_dump_hold_s_var.get()),
            }
        except ValueError as exc:
            raise ValueError("任务夹爪参数必须全部是数字。") from exc
        if not 0 <= values["open_mm"] <= self.c.gripper_max_mm:
            raise ValueError(f"打开宽度必须在0–{self.c.gripper_max_mm:g} mm之间。")
        if not 0 <= values["grip_mm"] <= self.c.gripper_max_mm:
            raise ValueError(f"夹紧宽度必须在0–{self.c.gripper_max_mm:g} mm之间。")
        if not 0.1 <= values["force_n"] <= 20:
            raise ValueError("夹持力必须在0.1–20 N之间。")
        if not 0 <= values["settle_s"] <= 10:
            raise ValueError("夹紧等待必须在0–10秒之间。")
        if not 0 <= values["dump_hold_s"] <= 15:
            raise ValueError("倒球停留必须在0–15秒之间。")
        if persist:
            self.store.set_gripper(**values)
        return values

    def save_task_parameters(self) -> None:
        try:
            self._task_parameters(persist=True)
            self.log("已保存任务夹爪参数。")
        except Exception as exc:
            messagebox.showerror("任务参数", str(exc), parent=self.root)

    def _require_pose_keys(self, keys: Iterable[str]) -> Dict[str, list[float]]:
        result: Dict[str, list[float]] = {}
        labels = dict(POSE_SLOTS)
        missing: list[str] = []
        for key in keys:
            pose = self.store.get_pose(key)
            if pose is None:
                missing.append(labels.get(key, key))
            else:
                result[key] = pose
        if missing:
            raise RuntimeError("请先记录这些位置：" + "、".join(missing))
        return result

    def _check_cancelled(self) -> None:
        if self._sequence_cancel.is_set():
            raise RuntimeError("任务序列已取消并触发软件急停。")

    def _stage_move(self, label: str, pose: list[float]) -> None:
        self._check_cancelled()
        self.root.after(0, lambda: self.log(f"序列步骤：{label}"))
        self._move_joint_pose_checked(pose)
        self._check_cancelled()

    def _stage_gripper(self, label: str, width: float, force: float, wait_s: float) -> None:
        self._check_cancelled()
        self.root.after(0, lambda: self.log(f"序列步骤：{label}"))
        self.c.move_gripper_mm(width, force)
        deadline = time.monotonic() + wait_s
        while time.monotonic() < deadline:
            self._check_cancelled()
            time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))

    def _sequence_grab(self, poses: Dict[str, list[float]], p: Dict[str, float]) -> None:
        self._stage_gripper("打开夹爪", p["open_mm"], p["force_n"], 0.4)
        self._stage_move("抓取前位置", poses["pickup_approach"])
        self._stage_move("抓取位置", poses["pickup"])
        self._stage_gripper("夹紧篮子", p["grip_mm"], p["force_n"], p["settle_s"])
        self._stage_move("抬起位置", poses["lift"])

    def _sequence_dump(self, poses: Dict[str, list[float]], p: Dict[str, float]) -> None:
        self._stage_move("倒球前位置", poses["dump_approach"])
        self._stage_move("翻转到倒球位置", poses["dump"])
        deadline = time.monotonic() + p["dump_hold_s"]
        while time.monotonic() < deadline:
            self._check_cancelled()
            time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
        self._stage_move("返回倒球前位置", poses["dump_approach"])

    def _sequence_place(self, poses: Dict[str, list[float]], p: Dict[str, float]) -> None:
        self._stage_move("抬起位置", poses["lift"])
        self._stage_move("放回抓取位置", poses["pickup"])
        self._stage_gripper("松开篮子", p["open_mm"], p["force_n"], 0.5)
        self._stage_move("退出抓取位置", poses["pickup_approach"])
        self._stage_move("安全收回位", poses["safe"])

    def run_sequence(self, name: str) -> None:
        if not self.auto_confirm_var.get():
            messagebox.showwarning(
                "任务未解锁",
                "请先勾选安全确认项。",
                parent=self.root,
            )
            return
        definitions = {
            "grab": ("抓起篮子", ("pickup_approach", "pickup", "lift")),
            "dump": ("翻转倒球", ("dump_approach", "dump")),
            "place": ("放回篮子", ("safe", "pickup_approach", "pickup", "lift")),
            "full": (
                "完整循环",
                ("safe", "pickup_approach", "pickup", "lift", "dump_approach", "dump"),
            ),
        }
        if name not in definitions:
            return
        label, keys = definitions[name]
        try:
            poses = self._require_pose_keys(keys)
            params = self._task_parameters(persist=True)
        except Exception as exc:
            messagebox.showerror("任务配置", str(exc), parent=self.root)
            return
        if not messagebox.askyesno(
            label,
            f"即将执行“{label}”。程序会连续经过已教学的位置。\n\n"
            "只有逐段验证过完整路径后才可执行。继续？",
            parent=self.root,
        ):
            return
        self._sequence_cancel.clear()

        def sequence() -> None:
            if name == "grab":
                self._sequence_grab(poses, params)
            elif name == "dump":
                self._sequence_dump(poses, params)
            elif name == "place":
                self._sequence_place(poses, params)
            else:
                self._stage_move("安全收回位", poses["safe"])
                self._sequence_grab(poses, params)
                self._sequence_dump(poses, params)
                self._sequence_place(poses, params)

        self._task(label, sequence, sequence=True)

    # ------------------------------------------------------------------
    # Poll / UI state
    # ------------------------------------------------------------------
    def _schedule_poll(self) -> None:
        if self._closing:
            return
        if self.c.connected and not self._poll_inflight:
            self._poll_inflight = True

            def worker() -> tuple[bool, Any]:
                try:
                    return True, self.c.get_snapshot()
                except Exception as exc:
                    return False, exc

            future = self.executor.submit(worker)

            def done() -> None:
                self._poll_inflight = False
                if self._closing:
                    return
                ok, value = future.result()
                if ok:
                    self._render_snapshot(value)
                else:
                    self.log(f"状态读取错误：{value}")
                self._set_controls()

            future.add_done_callback(lambda _: self.root.after(0, done))
        self.root.after(self.POLL_MS, self._schedule_poll)

    def _render_snapshot(self, snap: ArmSnapshot) -> None:
        self._last_snapshot = snap
        self.connection_text.set("已连接 / 通信正常" if snap.communication_ok else "已连接 / 反馈异常")
        if snap.firmware:
            self.firmware_text.set(
                f"{snap.firmware.get('software_version', '?')} / "
                f"{snap.firmware.get('hardware_version', '?')}"
            )
        if snap.flange_pose is not None:
            x, y, z, r, p, yaw = snap.flange_pose
            self.live_pose_text.set(
                f"X {x:.3f} m   Y {y:.3f} m   Z {z:.3f} m   "
                f"Roll {math.degrees(r):.1f}°   Pitch {math.degrees(p):.1f}°   Yaw {math.degrees(yaw):.1f}°"
            )
        if snap.joint_deg is not None:
            self.live_joint_text.set(
                "   ".join(f"J{i+1} {v:.1f}°" for i, v in enumerate(snap.joint_deg))
            )
        self.arm_text.set("关节已使能 — 可以动作" if self.c.motion_armed else "动作已锁定")

        lines = [
            f"Connected: {snap.connected}",
            f"Communication OK: {snap.communication_ok}",
            f"Firmware: {snap.firmware}",
            f"Joint deg: {snap.joint_deg}",
            f"Flange pose [m, rad]: {snap.flange_pose}",
            f"Enabled joints: {snap.enabled_joints}",
            f"Arm status: {snap.arm_status}",
            f"Gripper width (mm): {snap.gripper_width_mm}",
            f"Gripper force (N): {snap.gripper_force_n}",
            f"Program motion lock: {self.c.motion_armed}",
            f"Speed: {self.c.speed_percent}%",
            f"Task file: {self.store.path}",
        ]
        self.status_text.configure(state="normal")
        self.status_text.delete("1.0", END)
        self.status_text.insert("1.0", "\n".join(lines))
        self.status_text.configure(state="disabled")

    def _all_sequence_requirements_recorded(self) -> bool:
        return all(self.store.get_pose(key) is not None for key, _ in POSE_SLOTS)

    def _set_controls(self) -> None:
        connected = self.c.connected
        armed = connected and self.c.motion_armed
        busy = self._busy > 0

        self.connect_btn.configure(state="disabled" if connected or busy else "normal")
        self.disconnect_btn.configure(state="normal" if connected and not busy else "disabled")
        self.can_entry.configure(state="disabled" if connected or busy else "normal")
        self.enable_btn.configure(state="normal" if connected and not armed and not busy else "disabled")
        self.disable_btn.configure(state="normal" if connected and armed and not busy else "disabled")
        self.reset_btn.configure(state="normal" if connected and not busy else "disabled")
        self.estop_btn.configure(state="normal" if connected else "disabled")
        self.speed_apply_btn.configure(state="normal" if connected and not busy else "disabled")

        motion_state = "normal" if armed and not busy else "disabled"
        for widget in self.motion_widgets:
            try:
                widget.configure(state=motion_state)
            except Exception:
                pass

        sequence_requirements = {
            "grab": ("pickup_approach", "pickup", "lift"),
            "dump": ("dump_approach", "dump"),
            "place": ("safe", "pickup_approach", "pickup", "lift"),
            "full": tuple(key for key, _ in POSE_SLOTS),
        }
        sequence_base_ready = armed and not busy and self.auto_confirm_var.get()
        for name, widget in self.sequence_buttons.items():
            ready = sequence_base_ready and all(
                self.store.get_pose(key) is not None
                for key in sequence_requirements[name]
            )
            try:
                widget.configure(state="normal" if ready else "disabled")
            except Exception:
                pass
        self.estop_sequence_btn.configure(state="normal" if connected else "disabled")

    def on_close(self) -> None:
        if self.c.motion_armed and not messagebox.askyesno(
            "退出",
            "机械臂仍处于使能状态。退出程序只会断开通信，不会自动解除使能或断电。仍要退出？",
            parent=self.root,
        ):
            return
        self._closing = True
        self._sequence_cancel.set()
        try:
            self.c.disconnect()
        except Exception:
            pass
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.root.destroy()


def default_task_file() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "nxtektal-piper-x" / "basket_task.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="NXTektal PiPER X remote GUI")
    parser.add_argument("--can", default="can0", help="SocketCAN interface (default: can0)")
    parser.add_argument("--speed", type=int, default=10, help="Initial speed percentage, 1..50")
    parser.add_argument(
        "--gripper-max-mm",
        type=float,
        default=70.0,
        help="Installed AGX gripper maximum stroke, normally 70 or 100 mm",
    )
    parser.add_argument(
        "--task-file",
        type=Path,
        default=default_task_file(),
        help="JSON file used to save taught basket poses",
    )
    parser.add_argument("--dry-run", action="store_true", help="Run without hardware")
    args = parser.parse_args()

    controller = PiperXController(
        can_port=args.can,
        speed_percent=args.speed,
        gripper_max_mm=args.gripper_max_mm,
        dry_run=args.dry_run,
    )
    try:
        task_store = BasketTaskStore(args.task_file, args.gripper_max_mm)
    except Exception as exc:
        print(f"Warning: {exc}", file=sys.stderr)
        task_store = BasketTaskStore(args.task_file, args.gripper_max_mm)

    root = Tk()
    PiperXRemoteGUI(root, controller, task_store)
    root.mainloop()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        raise SystemExit(130)
