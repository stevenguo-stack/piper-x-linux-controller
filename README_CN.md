# PiPER X Linux 简易控制程序

这套程序基于 AgileX 官方 `pyAgxArm` Python SDK，为 **Ubuntu/Linux + PiPER X + 官方 USB-CAN 模块**做了一层更简单、偏安全的控制界面。

它包含：

- `piper_x_remote.py`：**推荐日常使用**的中文遥控器界面，提供前后左右上下、翻腕、夹爪和篮子动作教学。
- `piper_x_gui.py`：高级图形界面，可控制六关节、绝对关节目标和笛卡尔目标。
- `piper_x_cli.py`：终端交互控制，适合调试、保存姿态和写 Demo 流程。
- `piper_x_controller.py`：对官方 SDK 的封装。
- `setup_can.sh`：把 Linux SocketCAN 接口设置为 1 Mbps。
- `run_remote.sh`：启动遥控器界面。
- `install_desktop_launcher.sh`：把遥控器添加到 Ubuntu 应用菜单，日常使用不必打开终端。
- `install.sh`：自动创建 Python 虚拟环境并安装依赖。

程序故意没有开放 `move_js` 和 MIT 单关节控制，因为官方源码把它们标为高风险快速响应模式。普通控制只使用 `move_j`、`move_p`、`move_l` 和标准 AGX 夹爪接口。

---

## 1. 硬件连接

你们现在的整套关系应当是：

```text
TK25 原厂遥控器 ───────────────> TK25 底盘移动

TK25 主电池
  └─ 独立支路 ─ 24V稳压 / 10–12A供电能力 ─> PiPER X 电源

Ubuntu 笔记本
  └─ USB ─ 官方 USB-CAN 模块 ─ CAN线 ─────> PiPER X 控制
```

注意：

1. USB-CAN 线只负责通信，**不能给机械臂供电**。
2. PiPER X 厂家给出的电气要求是输入 **22–26V、稳压24V、供电能力不低于10A，建议10–12A**。
3. 你收到的线束信息是：机械臂端为 **2B 4-pin 航插**，供电侧为 **XT30，红正、黑负**。最终公母头和针脚定义仍以随货线束为准。
4. Linux 电脑与机械臂在这版方案中需要 USB-CAN 有线连接；TK25 本身仍独立使用原厂遥控器。
5. 官方文档目前明确建议使用机械臂随附的官方 CAN 模块。

---

## 2. 安装

适用于 Ubuntu 20.04 / 22.04 / 24.04。Ubuntu 22.04 默认 Python 3.10 可以使用。

```bash
cd piper_x_linux_controller
chmod +x *.sh
./install.sh
```

`install.sh` 会安装：

- Python 虚拟环境
- Tk 图形界面
- `can-utils`、`ethtool`、`iproute2`
- 官方 `pyAgxArm`
- `python-can`

为避免官方仓库之后更新导致接口突然变化，本包把 `pyAgxArm` 固定到了官方提交：

```text
2255d88e1fabdf20fcd1eccbc4312b4ce1cfd2d4
```

---

## 3. 先运行无硬件模拟

在机械臂到货前，可以先验证界面和操作逻辑：

```bash
./run_remote.sh --dry-run
```

高级界面或终端模式：

```bash
./run_gui.sh --dry-run
./run_cli.sh --dry-run
```

模拟模式不会向 CAN 总线发送任何指令。

---

## 4. 激活 CAN

接好官方 USB-CAN 模块后，先查看接口：

```bash
ip -brief link
```

通常接口叫 `can0`。然后运行：

```bash
./setup_can.sh can0
```

脚本会设置：

```text
SocketCAN interface: can0
CAN bitrate: 1,000,000 bit/s
restart-ms: 100
```

可选地查看机械臂 CAN 数据：

```bash
candump can0
```

如果持续出现 CAN 帧，说明 Linux 已经能收到机械臂数据。按 `Ctrl+C` 退出。

如果接口叫 `can1`，改成：

```bash
./setup_can.sh can1
```

---

## 5. 遥控器图形界面（推荐）

真实机械臂运行：

```bash
./run_remote.sh --can can0 --speed 10
```

如果安装的是100 mm行程夹爪：

```bash
./run_remote.sh --can can0 --speed 10 --gripper-max-mm 100
```

### 不用终端启动

安装完成后运行一次：

```bash
./install_desktop_launcher.sh can0 10
```

随后在 Ubuntu 应用菜单中搜索：

```text
NXTektal PiPER X 遥控器
```

以后可以直接点击图标打开，`Terminal=false`，不会弹出终端窗口。

### 第一次实机测试步骤

1. 把 PiPER X 用螺栓牢固固定在 TK25 的承力板上。
2. TK25 完全停车，避免误触底盘遥控器。
3. 机械臂不装篮子、不抓负载。
4. 确保运动范围内无人，实体急停按钮伸手可及。
5. 开启稳定24V供电并连接官方 USB-CAN。
6. 点击“连接”，确认状态反馈正常。
7. 点击“使能机械臂”。
8. 速度保持5–10%。
9. 位移步长先选2–5 mm，确认 +X、+Y、+Z 的真实方向。
10. 旋转步长先选0.5–1°，分别验证 Roll、Pitch、Yaw。
11. 最后再测试夹爪，不要一开始就夹篮子。

### 遥控界面功能

- **前 / 后 / 左 / 右 / 上 / 下**：根据实时末端位姿进行小步 Move-L。界面明确显示 ΔX、ΔY、ΔZ。
- **Roll / Pitch / Yaw**：小角度改变末端姿态。倒球使用哪个轴取决于夹爪和篮子横梁的安装方向。
- **夹爪**：打开、夹紧或移动到指定宽度，并设置夹持力。
- **使能、解除使能、故障复位、软件急停**：软件急停始终不能替代实体急停。
- **实时状态**：显示 XYZ、末端姿态、六关节角度、固件和通信状态。

默认坐标约定是：

```text
+X：向机械臂前方
+Y：向机械臂左侧
+Z：向上
```

但安装方向和控制器设置会影响你的直观感受，因此必须用2–5 mm空载点动实测，不要只看文字判断。

### 教学“抓篮子 → 倒球 → 放回”

程序不会写死任何机械臂角度。安装到 TK25 后，必须逐点记录六个真实安全位置：

1. **安全收回位**：机械臂收回，不影响 TK25 行驶。
2. **抓取前位置**：夹爪位于篮子横梁前方，尚未接触。
3. **抓取位置**：夹爪已对准并可以夹住横梁。
4. **抬起位置**：篮子离开支撑结构，仍保持稳定。
5. **倒球前位置**：篮子位于接收箱上方，尚未翻转。
6. **倒球位置**：篮子已经倾斜到足以倒出球的位置。

教学方法：

```text
用遥控小步移动到目标位置
→ 点击“记录当前”
→ 点击“前往”单独验证进出路径
→ 六个位置全部逐段验证
→ 勾选安全确认
→ 才能使用一键任务
```

一键任务逻辑：

```text
抓起篮子：打开 → 抓取前 → 抓取位 → 夹紧 → 抬起
翻转倒球：倒球前 → 倒球位 → 停留 → 倒球前
放回篮子：抬起 → 抓取位 → 打开 → 抓取前 → 安全位
完整循环：安全位 → 抓起 → 倒球 → 放回 → 安全位
```

教学位置默认保存在：

```text
~/.config/nxtektal-piper-x/basket_task.json
```

所以重新解压或更新程序后，已经教学的位置仍会保留。

### 高级图形界面

需要直接输入六关节或绝对笛卡尔目标时运行：

```bash
./run_gui.sh --can can0 --speed 10
```

高级界面适合调试，但日常 Demo 更建议使用 `run_remote.sh`。

---

## 6. 终端控制

运行：

```bash
./run_cli.sh --can can0 --speed 10
```

常用命令：

```text
status                         查看状态
enable                         使能关节，需要输入 ENABLE 确认
disable                        禁用关节，需要输入 DISABLE 确认
stop                           软件电子急停
reset                          复位控制器
speed 10                       设置速度为10%
jog 2 -1                      让J2相对移动-1°
joints 0 30 -60 0 30 0        六关节绝对角度，单位度
pose 0.25 0 0.30 0 90 0       点到点笛卡尔运动
line 0.25 0 0.35 0 90 0       直线笛卡尔运动
grip 35 3                     夹爪到35mm、夹持力3N
open 1                         打开夹爪
close 2                        关闭夹爪
save pickup                    保存当前关节姿态
go pickup                      移动到已保存姿态
poses                          列出已保存姿态
quit                           退出
```

---

## 7. 常见故障

### 应用菜单图标打不开

先在终端确认程序本身能运行：

```bash
./run_remote.sh --dry-run
```

然后重新安装图标：

```bash
./install_desktop_launcher.sh can0 10
```

### 找不到 `can0`

```bash
ip -brief link
lsusb
```

确认 USB-CAN 已连接、Linux 驱动已加载。如果显示为 `can1`，用 `can1` 运行脚本。

### 连接超时

依次检查：

- 机械臂是否有稳定24V供电。
- 实体急停是否释放。
- CAN-H / CAN-L 是否接反或松动。
- 是否使用官方 USB-CAN 模块。
- `ip -details link show can0` 是否显示 `state UP`、`bitrate 1000000`。
- `candump can0` 是否能收到数据。

### 能读状态但不能运动

- 点击/输入过 `Enable` 后再试。
- 查看六个关节是否全部 enabled。
- 查看 `arm_status` 是否为 0（Normal）。
- 排除限位、碰撞、通信和急停错误，再执行 Reset 和 Enable。

### 夹爪宽度不对

确认夹爪实际最大行程是 70 mm 还是 100 mm，并通过 `--gripper-max-mm` 指定。

---

## 8. 安全边界

- 软件按钮不能替代实体急停和断电开关。
- TK25 行驶时应让机械臂收回并保持稳定；机械臂抓取时底盘应完全停车。
- 第一次实机调试不要装篮子或负载。
- 不要站在机械臂运动范围内，也不要把手放进夹爪。
- 禁用关节前先支撑机械臂和负载。
- 篮子任务必须在真实安装后逐点教学；不要使用他人设备记录的角度文件。
- 一键动作前必须逐段验证完整路径，且篮子、横梁、夹爪与球的总重量不得超过 PiPER X 的实际能力。
- 本包没有开放 MIT / `move_js` 快速模式。
- 程序已经通过 Python 语法检查和无硬件模拟测试，但由于当前环境没有真实 PiPER X 和 USB-CAN，尚未完成实机验证。第一次上机应由厂家工程师或熟悉机械臂安全的人在旁协助。

---

## 9. 官方依据

本包使用以下 AgileX 官方资料：

- `agilexrobotics/pyAgxArm`：官方 Python SDK。
- `pyAgxArm/demos/piper_x/test1.py`：官方 PiPER X 示例。
- `docs/can_user.md`：Linux SocketCAN 与 1 Mbps CAN 设置。
- `docs/piper/piper_api.md`：Move-J、Move-P、Move-L、状态读取和急停接口。
- `docs/effector/agx_gripper/agx_gripper_api.md`：夹爪宽度/力控制接口。

官方 SDK 使用 LGPL-3.0-only；本项目自己的包装代码使用 MIT License，详见 `THIRD_PARTY_NOTICES.md` 和 `LICENSE`。
