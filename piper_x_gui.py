#!/usr/bin/env python3
"""Safety-oriented graphical remote for AgileX PiPER X on Linux."""
from __future__ import annotations

import argparse
import math
import queue
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from tkinter import BOTH, END, HORIZONTAL, LEFT, RIGHT, X, StringVar, Tk
from tkinter import messagebox, scrolledtext, ttk
from typing import Any, Callable, Optional

from piper_x_controller import ArmSnapshot, PiperXController
from piper_x_waypoints import (
    BasketSequenceRunner,
    SEQUENCE_REQUIREMENTS,
    WAYPOINT_LABELS,
    WaypointStore,
)


class PiperXGUI:
    POLL_MS = 400

    def __init__(
        self,
        root: Tk,
        controller: PiperXController,
        waypoint_path: str | Path,
    ) -> None:
        self.root = root
        self.c = controller
        self.store = WaypointStore(waypoint_path)
        self.executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="piper-x")
        self._closing = False
        self._poll_inflight = False
        self._busy = 0
        self._ui_lock = threading.Lock()
        self._log_queue: queue.Queue[str] = queue.Queue()

        self.root.title("PiPER X 遥控器 / Linux Controller")
        self.root.minsize(1100, 830)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.connection_text = StringVar(value="未连接 / Disconnected")
        self.arm_text = StringVar(value="动作锁定 / Motion locked")
        self.firmware_text = StringVar(value="—")
        self.speed_var = StringVar(value=str(self.c.speed_percent))
        self.jog_step_var = StringVar(value="1.0")
        self.cart_step_var = StringVar(value="5")
        self.wrist_step_var = StringVar(value="2")
        self.gripper_width_var = StringVar(value=f"{self.c.gripper_max_mm:.1f}")
        self.gripper_force_var = StringVar(value="3.0")
        self.sequence_close_width_var = StringVar(value="8.0")
        self.sequence_force_var = StringVar(value="3.0")
        self.sequence_settle_var = StringVar(value="1.0")
        self.current_joint_vars = [StringVar(value="—") for _ in range(6)]
        self.target_joint_vars = [StringVar(value="0.0") for _ in range(6)]
        self.pose_vars = [StringVar(value="0.0") for _ in range(6)]
        self.live_pose_text = StringVar(value="XYZ/RPY: —")
        self.waypoint_status_vars = {
            name: StringVar(value="未示教 / Not taught") for name in WAYPOINT_LABELS
        }

        self.motion_widgets: list[Any] = []
        self.feedback_widgets: list[Any] = []
        self.sequence_buttons: dict[str, ttk.Button] = {}
        self.waypoint_go_buttons: dict[str, ttk.Button] = {}

        self._build_ui()
        self._refresh_waypoint_status()
        self._set_controls()
        self.root.after(self.POLL_MS, self._schedule_poll)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.configure("Danger.TButton", font=("TkDefaultFont", 11, "bold"))
            style.configure("Primary.TButton", font=("TkDefaultFont", 10, "bold"))
        except Exception:
            pass

        outer = ttk.Frame(self.root, padding=10)
        outer.pack(fill=BOTH, expand=True)

        top = ttk.Frame(outer)
        top.pack(fill=X)
        self._build_connection(top)
        self._build_safety(top)

        self._build_speed(outer)

        tabs = ttk.Notebook(outer)
        tabs.pack(fill=BOTH, expand=True, pady=(10, 0))

        remote_tab = ttk.Frame(tabs, padding=10)
        joint_tab = ttk.Frame(tabs, padding=10)
        pose_tab = ttk.Frame(tabs, padding=10)
        gripper_tab = ttk.Frame(tabs, padding=10)
        status_tab = ttk.Frame(tabs, padding=10)
        tabs.add(remote_tab, text="遥控 Remote")
        tabs.add(joint_tab, text="关节点动 Joint")
        tabs.add(pose_tab, text="笛卡尔 Advanced")
        tabs.add(gripper_tab, text="夹爪 Gripper")
        tabs.add(status_tab, text="状态 / Log")

        self._build_remote(remote_tab)
        self._build_joints(joint_tab)
        self._build_pose(pose_tab)
        self._build_gripper(gripper_tab)
        self._build_status(status_tab)

    def _build_connection(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="连接 / Connection")
        frame.pack(side=LEFT, fill=BOTH, expand=True, padx=(0, 5))

        ttk.Label(frame, text="SocketCAN:").grid(
            row=0, column=0, sticky="w", padx=8, pady=6
        )
        self.can_var = StringVar(value=self.c.can_port)
        self.can_entry = ttk.Entry(frame, textvariable=self.can_var, width=14)
        self.can_entry.grid(row=0, column=1, sticky="w", padx=4, pady=6)
        mode = "模拟模式 / DRY RUN" if self.c.dry_run else "真实机械臂 / Real arm"
        ttk.Label(frame, text=mode).grid(row=0, column=2, sticky="w", padx=8)

        self.connect_btn = ttk.Button(frame, text="连接 Connect", command=self.connect)
        self.connect_btn.grid(row=1, column=0, padx=8, pady=6, sticky="ew")
        self.disconnect_btn = ttk.Button(
            frame, text="断开 Disconnect", command=self.disconnect
        )
        self.disconnect_btn.grid(row=1, column=1, padx=4, pady=6, sticky="ew")
        ttk.Label(frame, textvariable=self.connection_text).grid(
            row=1, column=2, sticky="w", padx=8
        )

        ttk.Label(frame, text="Firmware:").grid(
            row=2, column=0, sticky="w", padx=8, pady=(0, 6)
        )
        ttk.Label(frame, textvariable=self.firmware_text).grid(
            row=2, column=1, columnspan=2, sticky="w", padx=4, pady=(0, 6)
        )
        frame.columnconfigure(2, weight=1)

    def _build_safety(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="安全 / Safety")
        frame.pack(side=RIGHT, fill=BOTH, expand=True, padx=(5, 0))

        self.enable_btn = ttk.Button(frame, text="使能 Enable", command=self.enable)
        self.disable_btn = ttk.Button(frame, text="失能 Disable", command=self.disable)
        self.reset_btn = ttk.Button(frame, text="复位 Reset", command=self.reset)
        self.estop_btn = ttk.Button(
            frame,
            text="软件急停 / ELECTRONIC STOP",
            command=self.estop,
            style="Danger.TButton",
        )

        self.enable_btn.grid(row=0, column=0, padx=8, pady=8, sticky="ew")
        self.disable_btn.grid(row=0, column=1, padx=8, pady=8, sticky="ew")
        self.estop_btn.grid(row=1, column=0, padx=8, pady=8, sticky="ew")
        self.reset_btn.grid(row=1, column=1, padx=8, pady=8, sticky="ew")
        ttk.Label(
            frame,
            text="实体急停必须随手可按；软件急停只作为第二层保护。",
            wraplength=420,
        ).grid(row=2, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 4))
        ttk.Label(frame, textvariable=self.arm_text).grid(
            row=3, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 8)
        )
        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)

    def _build_speed(self, parent: ttk.Frame) -> None:
        speed = ttk.LabelFrame(parent, text="速度限制 / Speed limit")
        speed.pack(fill=X, pady=(10, 0))
        ttk.Label(speed, text="实机首次测试建议 5–10%：").pack(
            side=LEFT, padx=8, pady=8
        )
        self.speed_scale = ttk.Scale(
            speed,
            from_=1,
            to=50,
            orient=HORIZONTAL,
            command=lambda value: self.speed_var.set(str(int(float(value)))),
        )
        self.speed_scale.set(self.c.speed_percent)
        self.speed_scale.pack(side=LEFT, fill=X, expand=True, padx=8)
        ttk.Label(speed, textvariable=self.speed_var, width=4).pack(side=LEFT)
        self.speed_apply_btn = ttk.Button(
            speed, text="应用 Apply", command=self.apply_speed
        )
        self.speed_apply_btn.pack(side=LEFT, padx=8)

    def _build_remote(self, frame: ttk.Frame) -> None:
        ttk.Label(
            frame,
            text=(
                "每次点击只移动一个小步。XYZ方向使用机械臂底座坐标系；第一次必须空载、"
                "低速逐个确认方向。笛卡尔点动使用 Move-L，可能受逆运动学和奇异点影响。"
            ),
            wraplength=1030,
        ).pack(anchor="w", pady=(0, 8))

        top = ttk.Frame(frame)
        top.pack(fill=X)

        motion = ttk.LabelFrame(top, text="移动遥控 / Base-frame nudge")
        motion.pack(side=LEFT, fill=BOTH, expand=True, padx=(0, 5))

        controls = ttk.Frame(motion)
        controls.pack(fill=X, padx=8, pady=8)
        ttk.Label(controls, text="XYZ步长 (mm):").pack(side=LEFT)
        cart_step = ttk.Combobox(
            controls,
            textvariable=self.cart_step_var,
            values=("1", "2", "5", "10", "20"),
            width=7,
            state="readonly",
        )
        cart_step.pack(side=LEFT, padx=(4, 18))
        ttk.Label(controls, text="腕部步长 (deg):").pack(side=LEFT)
        wrist_step = ttk.Combobox(
            controls,
            textvariable=self.wrist_step_var,
            values=("0.5", "1", "2", "5"),
            width=7,
            state="readonly",
        )
        wrist_step.pack(side=LEFT, padx=4)
        self.motion_widgets.extend([cart_step, wrist_step])

        pad = ttk.Frame(motion)
        pad.pack(padx=8, pady=(0, 8))

        buttons = [
            ("前 / X+", 0, 1, lambda: self.cart_jog("x", +1)),
            ("后 / X−", 2, 1, lambda: self.cart_jog("x", -1)),
            ("左 / Y+", 1, 0, lambda: self.cart_jog("y", +1)),
            ("右 / Y−", 1, 2, lambda: self.cart_jog("y", -1)),
            ("上 / Z+", 0, 3, lambda: self.cart_jog("z", +1)),
            ("下 / Z−", 2, 3, lambda: self.cart_jog("z", -1)),
        ]
        for text, row, col, command in buttons:
            btn = ttk.Button(pad, text=text, command=command, width=14)
            btn.grid(row=row, column=col, padx=5, pady=5, sticky="nsew")
            self.motion_widgets.append(btn)

        wrist = ttk.LabelFrame(motion, text="腕部 / Wrist")
        wrist.pack(fill=X, padx=8, pady=(0, 8))
        wrist_buttons = [
            ("J6 左转 −", lambda: self.wrist_jog(6, -1)),
            ("J6 右转 +", lambda: self.wrist_jog(6, +1)),
            ("J5 俯 −", lambda: self.wrist_jog(5, -1)),
            ("J5 仰 +", lambda: self.wrist_jog(5, +1)),
        ]
        for text, command in wrist_buttons:
            btn = ttk.Button(wrist, text=text, command=command)
            btn.pack(side=LEFT, fill=X, expand=True, padx=5, pady=7)
            self.motion_widgets.append(btn)

        quick = ttk.LabelFrame(top, text="快捷操作 / Quick actions")
        quick.pack(side=RIGHT, fill=BOTH, expand=True, padx=(5, 0))
        ttk.Label(quick, textvariable=self.live_pose_text, wraplength=460).pack(
            anchor="w", padx=8, pady=(8, 4)
        )
        open_btn = ttk.Button(quick, text="打开夹爪 Open", command=self.open_gripper)
        close_btn = ttk.Button(quick, text="关闭夹爪 Close", command=self.close_gripper)
        home_btn = ttk.Button(
            quick, text="回安全位 Go Home", command=lambda: self.run_sequence("home")
        )
        open_btn.pack(fill=X, padx=8, pady=5)
        close_btn.pack(fill=X, padx=8, pady=5)
        home_btn.pack(fill=X, padx=8, pady=5)
        self.motion_widgets.extend([open_btn, close_btn])
        self.sequence_buttons["home"] = home_btn

        ttk.Label(
            quick,
            text="Home不是[0,0,0,0,0,0]；必须先示教当前安全收臂姿态。",
            wraplength=460,
        ).pack(anchor="w", padx=8, pady=(6, 8))

        teach = ttk.LabelFrame(frame, text="示教关键位置 / Teach joint-space waypoints")
        teach.pack(fill=X, pady=(10, 0))
        ttk.Label(
            teach,
            text=(
                "先用低速点动把机械臂移动到目标位置，再点击“保存当前”。自动流程不会使用"
                "预设坐标，只使用你在实机上保存的六关节角度。"
            ),
            wraplength=1010,
        ).grid(row=0, column=0, columnspan=5, sticky="w", padx=8, pady=8)

        for row, (name, label) in enumerate(WAYPOINT_LABELS.items(), start=1):
            ttk.Label(teach, text=label, width=34).grid(
                row=row, column=0, sticky="w", padx=8, pady=4
            )
            ttk.Label(teach, textvariable=self.waypoint_status_vars[name], width=25).grid(
                row=row, column=1, sticky="w", padx=6
            )
            save_btn = ttk.Button(
                teach,
                text="保存当前 Save",
                command=lambda key=name: self.save_waypoint(key),
            )
            save_btn.grid(row=row, column=2, padx=5, pady=4, sticky="ew")
            go_btn = ttk.Button(
                teach,
                text="移动到 Go",
                command=lambda key=name: self.go_waypoint(key),
            )
            go_btn.grid(row=row, column=3, padx=5, pady=4, sticky="ew")
            delete_btn = ttk.Button(
                teach,
                text="删除 Delete",
                command=lambda key=name: self.delete_waypoint(key),
            )
            delete_btn.grid(row=row, column=4, padx=5, pady=4, sticky="ew")
            self.feedback_widgets.extend([save_btn, delete_btn])
            self.waypoint_go_buttons[name] = go_btn
        teach.columnconfigure(0, weight=1)

        auto = ttk.LabelFrame(frame, text="篮子自动动作 / Taught demo sequences")
        auto.pack(fill=X, pady=(10, 0))
        settings = ttk.Frame(auto)
        settings.pack(fill=X, padx=8, pady=8)
        ttk.Label(settings, text="夹紧宽度(mm):").pack(side=LEFT)
        ttk.Entry(settings, textvariable=self.sequence_close_width_var, width=8).pack(
            side=LEFT, padx=(4, 12)
        )
        ttk.Label(settings, text="夹持力(N):").pack(side=LEFT)
        ttk.Entry(settings, textvariable=self.sequence_force_var, width=8).pack(
            side=LEFT, padx=(4, 12)
        )
        ttk.Label(settings, text="停留(s):").pack(side=LEFT)
        ttk.Entry(settings, textvariable=self.sequence_settle_var, width=8).pack(
            side=LEFT, padx=4
        )

        seq_buttons = ttk.Frame(auto)
        seq_buttons.pack(fill=X, padx=8, pady=(0, 8))
        for key, text in (
            ("grab", "一键抓篮子 / Grab"),
            ("dump", "一键倒球 / Dump"),
            ("place", "一键放回 / Place"),
            ("full", "完整流程 / Full demo"),
        ):
            btn = ttk.Button(
                seq_buttons,
                text=text,
                command=lambda sequence=key: self.run_sequence(sequence),
                style="Primary.TButton" if key == "full" else "TButton",
            )
            btn.pack(side=LEFT, fill=X, expand=True, padx=5, pady=5)
            self.sequence_buttons[key] = btn

        ttk.Label(
            auto,
            text=(
                "自动流程必须先逐段空载验证；程序按保存的关节姿态依次执行。运行中可随时按顶部"
                "软件急停，但实体急停仍是首选。"
            ),
            wraplength=1010,
        ).pack(anchor="w", padx=8, pady=(0, 8))

    def _build_joints(self, frame: ttk.Frame) -> None:
        ttk.Label(
            frame,
            text=(
                "普通Move-J点动。实机第一次使用：空载、5–10%速度、1°步长，逐个确认关节方向。"
            ),
            wraplength=1000,
        ).grid(row=0, column=0, columnspan=7, sticky="w", pady=(0, 10))

        ttk.Label(frame, text="步长 Step (deg):").grid(
            row=1, column=0, sticky="e", padx=4
        )
        step = ttk.Combobox(
            frame,
            textvariable=self.jog_step_var,
            values=("0.25", "0.5", "1.0", "2.0", "5.0"),
            width=8,
            state="readonly",
        )
        step.grid(row=1, column=1, sticky="w", pady=4)
        ttk.Label(frame, text="实时角度 / Live").grid(row=1, column=3, padx=6)
        ttk.Label(frame, text="绝对目标 / Target (deg)").grid(row=1, column=5, padx=6)
        self.motion_widgets.append(step)

        for i in range(6):
            row = i + 2
            ttk.Label(frame, text=f"J{i + 1}", width=5).grid(
                row=row, column=0, padx=4, pady=5
            )
            minus = ttk.Button(
                frame, text="−", width=5, command=lambda idx=i + 1: self.jog(idx, -1)
            )
            plus = ttk.Button(
                frame, text="+", width=5, command=lambda idx=i + 1: self.jog(idx, +1)
            )
            minus.grid(row=row, column=1, padx=4)
            plus.grid(row=row, column=2, padx=4)
            ttk.Label(frame, textvariable=self.current_joint_vars[i], width=14).grid(
                row=row, column=3, padx=6
            )
            ttk.Label(frame, text="deg").grid(row=row, column=4, sticky="w")
            entry = ttk.Entry(frame, textvariable=self.target_joint_vars[i], width=14)
            entry.grid(row=row, column=5, padx=6)
            self.motion_widgets.extend([minus, plus, entry])

        load = ttk.Button(
            frame, text="复制实时角度 / Copy live", command=self.load_live_joints
        )
        move = ttk.Button(
            frame, text="移动到绝对角度 / Move-J", command=self.move_absolute_joints
        )
        load.grid(row=8, column=1, columnspan=2, padx=4, pady=12, sticky="ew")
        move.grid(row=8, column=3, columnspan=3, padx=4, pady=12, sticky="ew")
        self.motion_widgets.extend([load, move])
        frame.columnconfigure(6, weight=1)

    def _build_pose(self, frame: ttk.Frame) -> None:
        ttk.Label(
            frame,
            text=(
                "高级功能：控制器逆运动学可能选择意料之外的关节构型。先完成关节点动验证。"
                "XYZ单位为米，Roll/Pitch/Yaw单位为度。"
            ),
            wraplength=1000,
        ).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 12))
        labels = ("X (m)", "Y (m)", "Z (m)", "Roll (deg)", "Pitch (deg)", "Yaw (deg)")
        for i, label in enumerate(labels):
            ttk.Label(frame, text=label).grid(
                row=i + 1, column=0, sticky="e", padx=8, pady=5
            )
            entry = ttk.Entry(frame, textvariable=self.pose_vars[i], width=18)
            entry.grid(row=i + 1, column=1, sticky="w", padx=8, pady=5)
            self.motion_widgets.append(entry)

        load = ttk.Button(frame, text="复制实时姿态", command=self.load_live_pose)
        move_p = ttk.Button(frame, text="Move-P", command=lambda: self.move_pose(False))
        move_l = ttk.Button(frame, text="Move-L", command=lambda: self.move_pose(True))
        load.grid(row=7, column=0, padx=8, pady=14, sticky="ew")
        move_p.grid(row=7, column=1, padx=8, pady=14, sticky="ew")
        move_l.grid(row=7, column=2, padx=8, pady=14, sticky="ew")
        self.motion_widgets.extend([load, move_p, move_l])
        frame.columnconfigure(3, weight=1)

    def _build_gripper(self, frame: ttk.Frame) -> None:
        ttk.Label(
            frame,
            text=(
                "标准AGX夹爪接口：开口宽度使用毫米，夹持力使用牛顿。确认安装的是70mm还是"
                "100mm行程夹爪。"
            ),
            wraplength=1000,
        ).pack(anchor="w", pady=(0, 15))

        width_frame = ttk.Frame(frame)
        width_frame.pack(fill=X, pady=8)
        ttk.Label(width_frame, text="宽度 Width (mm):", width=20).pack(side=LEFT)
        self.gripper_width_scale = ttk.Scale(
            width_frame,
            from_=0,
            to=self.c.gripper_max_mm,
            orient=HORIZONTAL,
            command=lambda value: self.gripper_width_var.set(f"{float(value):.1f}"),
        )
        self.gripper_width_scale.set(self.c.gripper_max_mm)
        self.gripper_width_scale.pack(side=LEFT, fill=X, expand=True, padx=8)
        width_entry = ttk.Entry(width_frame, textvariable=self.gripper_width_var, width=10)
        width_entry.pack(side=LEFT)

        force_frame = ttk.Frame(frame)
        force_frame.pack(fill=X, pady=8)
        ttk.Label(force_frame, text="夹持力 Force (N):", width=20).pack(side=LEFT)
        self.gripper_force_scale = ttk.Scale(
            force_frame,
            from_=0.1,
            to=20.0,
            orient=HORIZONTAL,
            command=lambda value: self.gripper_force_var.set(f"{float(value):.1f}"),
        )
        self.gripper_force_scale.set(3.0)
        self.gripper_force_scale.pack(side=LEFT, fill=X, expand=True, padx=8)
        force_entry = ttk.Entry(force_frame, textvariable=self.gripper_force_var, width=10)
        force_entry.pack(side=LEFT)

        buttons = ttk.Frame(frame)
        buttons.pack(fill=X, pady=20)
        open_btn = ttk.Button(buttons, text="打开 Open", command=self.open_gripper)
        move_btn = ttk.Button(buttons, text="移动到宽度 Move", command=self.move_gripper)
        close_btn = ttk.Button(buttons, text="关闭 Close", command=self.close_gripper)
        open_btn.pack(side=LEFT, padx=8)
        move_btn.pack(side=LEFT, padx=8)
        close_btn.pack(side=LEFT, padx=8)
        self.motion_widgets.extend(
            [
                self.gripper_width_scale,
                self.gripper_force_scale,
                width_entry,
                force_entry,
                open_btn,
                move_btn,
                close_btn,
            ]
        )

    def _build_status(self, frame: ttk.Frame) -> None:
        self.status_text = scrolledtext.ScrolledText(frame, height=15, wrap="word")
        self.status_text.pack(fill=BOTH, expand=True)
        self.status_text.configure(state="disabled")

        ttk.Separator(frame, orient=HORIZONTAL).pack(fill=X, pady=8)
        self.log_text = scrolledtext.ScrolledText(frame, height=10, wrap="word")
        self.log_text.pack(fill=BOTH, expand=True)
        self.log_text.configure(state="disabled")

    # ------------------------------------------------------------------
    # Background tasks and logging
    # ------------------------------------------------------------------
    def log(self, text: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert(END, f"[{stamp}] {text}\n")
        self.log_text.see(END)
        self.log_text.configure(state="disabled")

    def _thread_log(self, text: str) -> None:
        self._log_queue.put(text)

    def _drain_log_queue(self) -> None:
        while True:
            try:
                self.log(self._log_queue.get_nowait())
            except queue.Empty:
                break

    def _task(
        self,
        label: str,
        fn: Callable[[], Any],
        on_success: Optional[Callable[[Any], None]] = None,
        quiet: bool = False,
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
            self._drain_log_queue()
            if ok:
                try:
                    if on_success is not None:
                        on_success(value)
                    if not quiet:
                        self.log(f"{label}: 完成 / done")
                except Exception as exc:
                    self.log(f"{label}: ERROR — {exc}")
                    messagebox.showerror("PiPER X", str(exc), parent=self.root)
            else:
                self.log(f"{label}: ERROR — {value}")
                messagebox.showerror("PiPER X", str(value), parent=self.root)
            self._refresh_waypoint_status()
            self._set_controls()

        future.add_done_callback(lambda _: self.root.after(0, done))

    # ------------------------------------------------------------------
    # Connection and safety actions
    # ------------------------------------------------------------------
    def connect(self) -> None:
        self.c.can_port = self.can_var.get().strip() or "can0"
        self.connection_text.set("连接中 / Connecting …")

        def success(fw: dict[str, str]) -> None:
            self.connection_text.set("已连接 / Connected")
            self.firmware_text.set(
                f"{fw.get('software_version', '?')} / {fw.get('hardware_version', '?')}"
            )
            self.log("动作仍处于锁定状态；检查现场后再点击Enable。")

        self._task("连接 Connect", self.c.connect, success)

    def disconnect(self) -> None:
        if self.c.motion_armed and not messagebox.askyesno(
            "断开连接",
            "当前软件动作锁已打开。断开连接不会自动Disable机械臂，仍要继续吗？",
            parent=self.root,
        ):
            return

        def success(_: Any) -> None:
            self.connection_text.set("未连接 / Disconnected")
            self.arm_text.set("动作锁定 / Motion locked")

        self._task("断开 Disconnect", self.c.disconnect, success)

    def enable(self) -> None:
        if not messagebox.askyesno(
            "使能 PiPER X",
            "请确认：\n\n"
            "• TK25底盘已经停车\n"
            "• 机械臂牢固固定在承力板\n"
            "• 工作空间无人、无障碍物\n"
            "• 首次测试不抓负载\n"
            "• 实体急停随手可按\n\n"
            "是否使能六个关节？",
            parent=self.root,
        ):
            return

        def success(ok: bool) -> None:
            if not ok:
                raise RuntimeError("使能超时，请检查急停和机械臂状态。")
            self.arm_text.set("关节已使能 / Motion armed")

        self._task("使能关节", self.c.enable, success)

    def disable(self) -> None:
        if not messagebox.askyesno(
            "失能 PiPER X",
            "失能后可能失去保持力。先支撑机械臂和负载，是否继续？",
            parent=self.root,
        ):
            return

        def success(ok: bool) -> None:
            if not ok:
                raise RuntimeError("Disable超时。")
            self.arm_text.set("关节已失能 / Motion locked")

        self._task("失能关节", self.c.disable, success)

    def estop(self) -> None:
        self.arm_text.set("已请求软件急停")
        self._task("软件急停", self.c.emergency_stop)

    def reset(self) -> None:
        if not messagebox.askyesno(
            "复位控制器", "只有在故障原因排除后才能复位，是否继续？", parent=self.root
        ):
            return

        def success(_: Any) -> None:
            self.arm_text.set("已发送复位；动作仍锁定")

        self._task("复位控制器", self.c.reset, success)

    def apply_speed(self) -> None:
        try:
            value = int(float(self.speed_var.get()))
        except ValueError:
            messagebox.showerror("速度", "请输入1到50的整数。", parent=self.root)
            return
        self._task(f"设置速度 {value}%", lambda: self.c.set_speed_percent(value))

    # ------------------------------------------------------------------
    # Remote/jog actions
    # ------------------------------------------------------------------
    def cart_jog(self, axis: str, direction: int) -> None:
        try:
            step = float(self.cart_step_var.get())
            if step not in (1.0, 2.0, 5.0, 10.0, 20.0):
                raise ValueError
        except ValueError:
            messagebox.showerror("XYZ点动", "无效步长。", parent=self.root)
            return
        delta = direction * step
        self._task(
            f"{axis.upper()} {delta:+g} mm",
            lambda: self.c.jog_cartesian_mm(axis, delta, linear=True, wait=True),
        )

    def wrist_jog(self, joint: int, direction: int) -> None:
        try:
            step = float(self.wrist_step_var.get())
            if not 0.0 < step <= 5.0:
                raise ValueError
        except ValueError:
            messagebox.showerror("腕部点动", "步长必须在0到5度之间。", parent=self.root)
            return
        delta = direction * step
        self._task(
            f"J{joint} {delta:+g}°",
            lambda: self.c.jog_joint_deg(joint, delta, wait=True),
        )

    def jog(self, joint: int, direction: int) -> None:
        try:
            step = float(self.jog_step_var.get())
        except ValueError:
            messagebox.showerror("关节点动", "无效步长。", parent=self.root)
            return
        delta = direction * step
        self._task(
            f"Jog J{joint} {delta:+g}°",
            lambda: self.c.jog_joint_deg(joint, delta, wait=True),
        )

    def load_live_joints(self) -> None:
        try:
            snap = self.c.get_snapshot()
            if snap.joint_deg is None:
                raise RuntimeError("没有关节反馈。")
            for var, value in zip(self.target_joint_vars, snap.joint_deg):
                var.set(f"{value:.4f}")
            self.log("已复制实时关节角度。")
        except Exception as exc:
            messagebox.showerror("关节", str(exc), parent=self.root)

    def move_absolute_joints(self) -> None:
        try:
            target = [float(v.get()) for v in self.target_joint_vars]
        except ValueError:
            messagebox.showerror("关节", "六个目标都必须是数字。", parent=self.root)
            return
        if not messagebox.askyesno(
            "绝对Move-J",
            "需要检查完整路径，不只是终点。\n\n"
            f"目标角度：\n{target}\n\n发送动作？",
            parent=self.root,
        ):
            return
        self._task(
            "绝对 Move-J", lambda: self.c.move_joints_deg(target, wait=True)
        )

    def load_live_pose(self) -> None:
        try:
            snap = self.c.get_snapshot()
            if snap.flange_pose is None:
                raise RuntimeError("没有末端姿态反馈。")
            x, y, z, r, p, yaw = snap.flange_pose
            values = (x, y, z, math.degrees(r), math.degrees(p), math.degrees(yaw))
            for var, value in zip(self.pose_vars, values):
                var.set(f"{value:.6f}")
            self.log("已复制实时笛卡尔姿态。")
        except Exception as exc:
            messagebox.showerror("姿态", str(exc), parent=self.root)

    def move_pose(self, linear: bool) -> None:
        try:
            target = [float(v.get()) for v in self.pose_vars]
        except ValueError:
            messagebox.showerror("姿态", "六个姿态值都必须是数字。", parent=self.root)
            return
        mode = "Move-L" if linear else "Move-P"
        if not messagebox.askyesno(
            mode,
            "笛卡尔控制使用逆运动学，可能选择意外关节构型。\n\n"
            f"目标 [x y z roll pitch yaw]:\n{target}\n\n发送动作？",
            parent=self.root,
        ):
            return
        self._task(
            mode, lambda: self.c.move_pose_deg(target, linear=linear, wait=True)
        )

    # ------------------------------------------------------------------
    # Gripper actions
    # ------------------------------------------------------------------
    def _gripper_values(self) -> tuple[float, float]:
        try:
            return float(self.gripper_width_var.get()), float(self.gripper_force_var.get())
        except ValueError as exc:
            raise ValueError("夹爪宽度和力必须是数字。") from exc

    def move_gripper(self) -> None:
        try:
            width, force = self._gripper_values()
        except Exception as exc:
            messagebox.showerror("夹爪", str(exc), parent=self.root)
            return
        self._task(
            f"夹爪 {width:g} mm / {force:g} N",
            lambda: self.c.move_gripper_mm(width, force),
        )

    def open_gripper(self) -> None:
        try:
            _, force = self._gripper_values()
        except Exception as exc:
            messagebox.showerror("夹爪", str(exc), parent=self.root)
            return
        self.gripper_width_var.set(f"{self.c.gripper_max_mm:.1f}")
        self.gripper_width_scale.set(self.c.gripper_max_mm)
        self._task("打开夹爪", lambda: self.c.open_gripper(force))

    def close_gripper(self) -> None:
        try:
            _, force = self._gripper_values()
        except Exception as exc:
            messagebox.showerror("夹爪", str(exc), parent=self.root)
            return
        if not messagebox.askyesno(
            "关闭夹爪", "手指、线束和易碎物必须离开夹爪。关闭到0mm？", parent=self.root
        ):
            return
        self.gripper_width_var.set("0.0")
        self.gripper_width_scale.set(0.0)
        self._task("关闭夹爪", lambda: self.c.close_gripper(force))

    # ------------------------------------------------------------------
    # Taught waypoints and basket sequences
    # ------------------------------------------------------------------
    def _refresh_waypoint_status(self) -> None:
        try:
            poses = self.store.load_all()
        except Exception as exc:
            poses = {}
            self._thread_log(f"Waypoint file error: {exc}")
        for name in WAYPOINT_LABELS:
            if name in poses:
                values = poses[name]
                summary = ", ".join(f"{v:.1f}" for v in values)
                self.waypoint_status_vars[name].set(f"已保存 [{summary}]")
            else:
                self.waypoint_status_vars[name].set("未示教 / Not taught")

    def save_waypoint(self, name: str) -> None:
        label = WAYPOINT_LABELS.get(name, name)
        if not messagebox.askyesno(
            "保存示教位置",
            f"把机械臂当前六关节角度保存为：\n{label}\n\n以后自动流程会移动到这里，是否保存？",
            parent=self.root,
        ):
            return

        def work() -> list[float]:
            snap = self.c.get_snapshot()
            if snap.joint_deg is None:
                raise RuntimeError("没有实时关节角度反馈。")
            return self.store.save(name, snap.joint_deg)

        self._task(f"保存 {label}", work)

    def delete_waypoint(self, name: str) -> None:
        label = WAYPOINT_LABELS.get(name, name)
        if not self.store.has(name):
            return
        if not messagebox.askyesno(
            "删除示教位置", f"确认删除：{label}？", parent=self.root
        ):
            return
        try:
            self.store.delete(name)
            self.log(f"已删除 {label}")
            self._refresh_waypoint_status()
            self._set_controls()
        except Exception as exc:
            messagebox.showerror("示教位置", str(exc), parent=self.root)

    def go_waypoint(self, name: str) -> None:
        label = WAYPOINT_LABELS.get(name, name)
        try:
            target = self.store.get(name)
        except Exception as exc:
            messagebox.showerror("示教位置", str(exc), parent=self.root)
            return
        if not messagebox.askyesno(
            "移动到示教位置",
            f"目标：{label}\n角度：{target}\n\n必须确认整条路径无碰撞，是否移动？",
            parent=self.root,
        ):
            return
        self._task(
            f"移动到 {label}", lambda: self.c.move_joints_deg(target, wait=True)
        )

    def _sequence_settings(self) -> tuple[float, float, float]:
        try:
            close_width = float(self.sequence_close_width_var.get())
            force = float(self.sequence_force_var.get())
            settle = float(self.sequence_settle_var.get())
        except ValueError as exc:
            raise ValueError("自动流程的宽度、夹持力和停留时间必须是数字。") from exc
        return close_width, force, settle

    def run_sequence(self, name: str) -> None:
        labels = {
            "home": "回安全位 / Home",
            "grab": "抓篮子 / Grab basket",
            "dump": "倒球 / Dump balls",
            "place": "放回篮子 / Place basket",
            "full": "完整抓取—倒球—放回流程 / Full demo",
        }
        label = labels[name]
        try:
            close_width, force, settle = self._sequence_settings()
            missing = self.store.missing(SEQUENCE_REQUIREMENTS[name])
            if missing:
                text = ", ".join(WAYPOINT_LABELS.get(k, k) for k in missing)
                raise RuntimeError(f"请先示教这些位置：{text}")
        except Exception as exc:
            messagebox.showerror("自动流程", str(exc), parent=self.root)
            return

        warning = (
            f"准备执行：{label}\n\n"
            "• TK25必须停车\n"
            "• 已逐段低速验证所有示教路径\n"
            "• 篮子、横杆和夹爪重量未超出机械臂负载\n"
            "• 工作区无人，实体急停可触达\n\n"
            "是否执行？"
        )
        if not messagebox.askyesno("执行自动流程", warning, parent=self.root):
            return

        def work() -> None:
            runner = BasketSequenceRunner(
                self.c,
                self.store,
                close_width_mm=close_width,
                force_n=force,
                settle_seconds=settle,
                progress=self._thread_log,
            )
            if name == "home":
                runner.go_home()
            elif name == "grab":
                runner.grab_basket()
            elif name == "dump":
                runner.dump_balls()
            elif name == "place":
                runner.place_basket()
            elif name == "full":
                runner.full_demo()
            else:
                raise ValueError(name)

        self._task(label, work)

    # ------------------------------------------------------------------
    # State refresh
    # ------------------------------------------------------------------
    def _schedule_poll(self) -> None:
        if self._closing:
            return
        self._drain_log_queue()
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
                    self.log(f"Status poll error: {value}")
                self._set_controls()

            future.add_done_callback(lambda _: self.root.after(0, done))
        self.root.after(self.POLL_MS, self._schedule_poll)

    def _render_snapshot(self, snap: ArmSnapshot) -> None:
        self.connection_text.set(
            "已连接 / CAN OK"
            if snap.communication_ok
            else "已连接 / 无健康反馈"
        )
        if snap.firmware:
            self.firmware_text.set(
                f"{snap.firmware.get('software_version', '?')} / "
                f"{snap.firmware.get('hardware_version', '?')}"
            )
        if snap.joint_deg is not None:
            for var, value in zip(self.current_joint_vars, snap.joint_deg):
                var.set(f"{value: .3f}°")
        if snap.flange_pose is not None:
            x, y, z, r, p, yaw = snap.flange_pose
            self.live_pose_text.set(
                f"XYZ: {x:.3f}, {y:.3f}, {z:.3f} m | "
                f"RPY: {math.degrees(r):.1f}, {math.degrees(p):.1f}, "
                f"{math.degrees(yaw):.1f}°"
            )

        self.arm_text.set(
            "关节已使能 / Motion armed"
            if self.c.motion_armed
            else "动作锁定 / Motion locked"
        )

        lines = [
            f"Connected: {snap.connected}",
            f"Communication OK: {snap.communication_ok}",
            f"Firmware: {snap.firmware}",
            f"Joints (rad): {snap.joint_rad}",
            f"Joints (deg): {snap.joint_deg}",
            f"Flange pose [m, rad]: {snap.flange_pose}",
            f"Enabled joints: {snap.enabled_joints}",
            f"Arm status: {snap.arm_status}",
            f"Gripper width (mm): {snap.gripper_width_mm}",
            f"Gripper force (N): {snap.gripper_force_n}",
            f"Program motion lock: {self.c.motion_armed}",
            f"Speed: {self.c.speed_percent}%",
            f"Waypoint file: {self.store.path}",
        ]
        self.status_text.configure(state="normal")
        self.status_text.delete("1.0", END)
        self.status_text.insert("1.0", "\n".join(lines))
        self.status_text.configure(state="disabled")

    def _set_controls(self) -> None:
        connected = self.c.connected
        armed = connected and self.c.motion_armed
        busy = self._busy > 0

        self.connect_btn.configure(state="disabled" if connected or busy else "normal")
        self.disconnect_btn.configure(
            state="normal" if connected and not busy else "disabled"
        )
        self.can_entry.configure(state="disabled" if connected or busy else "normal")

        self.enable_btn.configure(
            state="normal" if connected and not armed and not busy else "disabled"
        )
        self.disable_btn.configure(
            state="normal" if connected and armed and not busy else "disabled"
        )
        self.reset_btn.configure(state="normal" if connected and not busy else "disabled")
        self.estop_btn.configure(state="normal" if connected else "disabled")
        self.speed_apply_btn.configure(
            state="normal" if connected and not busy else "disabled"
        )

        motion_state = "normal" if armed and not busy else "disabled"
        for widget in self.motion_widgets:
            try:
                widget.configure(state=motion_state)
            except Exception:
                pass

        feedback_state = "normal" if connected and not busy else "disabled"
        for widget in self.feedback_widgets:
            try:
                widget.configure(state=feedback_state)
            except Exception:
                pass

        for name, btn in self.waypoint_go_buttons.items():
            state = "normal" if armed and not busy and self.store.has(name) else "disabled"
            btn.configure(state=state)

        for sequence, btn in self.sequence_buttons.items():
            missing = self.store.missing(SEQUENCE_REQUIREMENTS[sequence])
            state = "normal" if armed and not busy and not missing else "disabled"
            btn.configure(state=state)

    def on_close(self) -> None:
        if self.c.motion_armed and not messagebox.askyesno(
            "退出",
            "当前软件动作锁已打开。退出只会断开通信，不会自动Disable，仍要退出吗？",
            parent=self.root,
        ):
            return
        self._closing = True
        try:
            self.c.disconnect()
        except Exception:
            pass
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.root.destroy()


def main() -> int:
    parser = argparse.ArgumentParser(description="PiPER X Linux graphical remote")
    parser.add_argument("--can", default="can0", help="SocketCAN interface")
    parser.add_argument("--speed", type=int, default=10, help="Initial speed 1..50%%")
    parser.add_argument(
        "--gripper-max-mm",
        type=float,
        default=70.0,
        help="Installed gripper stroke, normally 70 or 100 mm",
    )
    parser.add_argument(
        "--waypoints",
        default=str(Path(__file__).resolve().with_name("poses.json")),
        help="JSON file for taught joint-space waypoints",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Hardware-free UI simulation"
    )
    args = parser.parse_args()

    controller = PiperXController(
        can_port=args.can,
        speed_percent=args.speed,
        gripper_max_mm=args.gripper_max_mm,
        dry_run=args.dry_run,
    )
    root = Tk()
    PiperXGUI(root, controller, args.waypoints)
    root.mainloop()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        raise SystemExit(130)
