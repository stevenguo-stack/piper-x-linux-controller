# PiPER X 控制程序：Windows 版

本版把现有中文遥控器、高级界面和终端控制接到了 **Windows 原生 `agx_cando` CAN 后端**。目标环境为 **Windows 10/11 x64 + Python 3.10、3.11 或 3.12 的 64 位版本**。可以先在 Windows 上打开模拟界面；实际连接 PiPER X 时，还需要与官方后端兼容的 USB-CAN 模块及对应 Windows 驱动。

不需要 WSL。Linux 的 `.sh` 启动脚本继续用于 Linux，Windows 使用本说明里的 `.bat` 文件。

## 1. 先打开界面，不用连接机械臂

1. **把整个压缩包解压**到自己有写入权限的文件夹。不要直接在压缩包里双击脚本；不要只复制某一个 `.bat` 文件。文件夹路径可以含空格和中文。
2. 从 [Python 官方 Windows 下载页面](https://www.python.org/downloads/windows/)安装 **Python 3.10、3.11 或 3.12，64 位**，包含 `pip`、`tcl/tk and IDLE` 和 Python Launcher。已有其中一个受支持版本就可以继续。
3. 双击 **`preview_windows.bat`**。

此入口始终运行 **DRY RUN / 模拟模式**，只需要 Python 和自带的 Tk，不安装 CAN SDK，不连接机械臂。你可以查看中文遥控器、按钮和模拟状态。它使用独立的模拟示教文件，不会把模拟位置保存进真实机械臂的默认示教文件。

预览入口不转发额外启动参数，因此不能通过这个入口切换成真实控制。模拟反馈只用于检查界面和操作流程，不能用于判断实际机械臂的运动方向、可达位置或避碰效果。

## 2. 安装真实控制需要的 Python 依赖

双击 **`install_windows.bat`**，等待窗口显示 `Installation complete`。

安装程序会：

- 在项目目录中创建独立的 **`.venv-windows`** Python 环境。
- 从固定版本的官方源码安装 `pyAgxArm` 和 `python-can-agx-cando`，以及它们声明的 Python 依赖。
- 检查依赖冲突和 Python/Tk/SDK/CAN 后端导入。

首次安装需要访问 GitHub 和 PyPI。安装不需要 Git，不使用 PowerShell 脚本，不自动修改驱动，也不会自动连接、使能或移动机械臂。安装窗口会保留结果；如果报错，可把完整错误截屏用于排查。

Windows 环境与 Linux 的 `.venv` 分开存放。如果把程序文件夹移动到另一位置或另一台电脑，应重新运行安装程序；虚拟环境本身不适合直接搬到其他路径。已有环境因路径变化或 Python 卸载而失效时，关闭程序，将 `.venv-windows` 改名，再重新安装即可。

## 3. 准备 USB-CAN 与机械臂

实际通信使用松灵官方 `python-can-agx-cando` 插件；随包的 Windows DLL 由该插件提供。**驱动是否适配，仍取决于你手上的 USB-CAN 模块及其 Windows 驱动。** 请按该模块随附的官方 Windows 说明安装匹配的驱动；不要根据 Linux 下叫 `can0`，就判断它一定能直接用于 Windows。

在 Windows 设备管理器中确认官方 USB-CAN 正常识别后，连接模块与 PiPER X，并按机械臂官方说明完成供电。Windows 无法识别设备时，按松灵随货驱动说明或通过官方支持匹配，不能假定所有模块都免驱。USB-CAN 连接只负责通信，机械臂仍需自己的电源。

本版使用 1,000,000 bit/s CAN。Windows 下不运行 `setup_can.sh`、`ip link` 或 `candump`。`--can 0` 是此 CAN 后端的设备索引参数，不是 `COM0`，也不是 Linux 的 `can0`。

## 4. 双击打开真实控制界面

推荐双击 **`run_remote_windows.bat`**，打开日常使用的中文遥控器。

| 文件 | 作用 | 默认行为 |
|---|---|---|
| `preview_windows.bat` | 无硬件预览中文遥控器 | 固定模拟模式，独立模拟示教文件 |
| `install_windows.bat` | 安装 Python 依赖 | 不访问 CAN 设备 |
| `check_windows.bat` | 检查环境与依赖导入 | 不访问 CAN 设备 |
| `run_remote_windows.bat` | 中文遥控器与篮子示教 | 等待你点击连接、使能与动作按钮 |
| `run_gui_windows.bat` | 高级六关节与末端控制界面 | 等待你点击连接、使能与动作按钮 |
| `run_cli_windows.bat` | 终端交互控制 | 启动时建立通信；运动仍需要交互使能与动作指令 |

三个真实控制入口默认采用：

| 参数 | 默认值 |
|---|---|
| CAN 后端 | `agx_cando` |
| CAN 设备索引 | `0` |
| 初始速度 | **5%** |
| 夹爪最大行程 | `70 mm`，应按实际夹爪修改 |

第一次连接后先确认通信和关节反馈。机械臂固定好、空载且周围留出运动空间后，再按界面步骤使能，从小步点动开始验证。软件停止按钮无法替代机械臂的实体急停。抓篮、倒球与放回仍需在实际安装位置逐点示教，并逐段验证路径。

### 修改设备索引、速度或夹爪行程

在项目目录打开 **命令提示符（CMD）**，例如安装的是 100 mm 行程夹爪：

```bat
run_remote_windows.bat --gripper-max-mm 100
```

指定其他设备索引：

```bat
run_remote_windows.bat --can 1 --speed 5 --gripper-max-mm 100
```

高级界面和终端入口接受相同的参数：

```bat
run_gui_windows.bat --can 0 --speed 5 --gripper-max-mm 100
run_cli_windows.bat --can 0 --speed 5 --gripper-max-mm 100
```

如果在 PowerShell 中输入，在脚本名前加 `.\`（实际命令写法如下）；运行 `.bat` 不需要更改 PowerShell 执行策略：

```powershell
.\run_remote_windows.bat --gripper-max-mm 100
```

这些参数仅设置程序初始值，启动本身不发送运动目标。真实动作还需要应用内的使能与操作。传入的速度、夹爪宽度等参数仍受控制程序本身的范围检查。

### 示教位置保存在哪里

Windows 默认保存目录为：

```text
%LOCALAPPDATA%\NXTektal\PiPER-X\
```

| 用途 | 默认文件 |
|---|---|
| 遥控器真实篮子示教 | `basket_task.json` |
| 遥控器模拟示教 | `basket_task_demo.json` |
| 高级界面/终端真实姿态 | `poses.json` |
| 高级界面/终端模拟姿态 | `poses_demo.json` |

更新程序或重装依赖不会删除这里的点位文件。遥控器也支持用 `--task-file` 指定自己的文件；指定含空格的路径时加双引号。首次迁移旧点位时，需要按实际机械臂安装位置重新核对，不要直接执行未经实机验证的动作序列。

## 5. 环境检查与常见问题

双击 **`check_windows.bat`** 可看到 Python 版本、Tk、官方 SDK 和 `agx_cando` 后端导入结果。此检查不打开 CAN 设备，不使能、不发送运动指令。即使全部显示 `[OK]`，也仍需实际确认驱动、设备识别、CAN 通信和机械臂反馈。

| 现象 | 处理方式 |
|---|---|
| `A supported Python installation was not found` | 安装 python.org 的 64 位 Python 3.10–3.12，包含 Python Launcher；未装 Launcher 时，需要将该 Python 加到 PATH。 |
| `Tcl/Tk is unavailable` | 用 Python 官方安装程序的 Modify/Repair 补装 `tcl/tk and IDLE`。 |
| 缺少 Windows 环境或 `pyAgxArm` / `agx_cando` | 重新运行 `install_windows.bat`，检查安装是否完整成功。 |
| 下载失败、超时或证书错误 | 检查电脑访问 GitHub、PyPI 的网络和系统时间，再重试安装；保留具体报错。 |
| 后端 DLL 导入失败 | 先修复 Python 依赖；保留完整报错，按该适配器的官方说明检查 Windows 依赖与驱动，不要从不明来源下载同名 DLL。 |
| 后端能导入，但真实连接超时 | 检查实际 USB-CAN 模块是否匹配官方 Windows 插件、官方驱动、设备索引、机械臂供电和 CAN 接线；导入成功不表示设备已可通信。 |
| 界面显示模拟数据 | 当前运行的是 `preview_windows.bat` 或显式加了 `--dry-run`；实机使用 `run_remote_windows.bat`。 |

## 6. 版本与验证范围

本版固定使用以下官方提交，安装链接见 `windows_requirements.txt`：

- [AgileX pyAgxArm：`2255d88e1fabdf20fcd1eccbc4312b4ce1cfd2d4`](https://github.com/agilexrobotics/pyAgxArm/tree/2255d88e1fabdf20fcd1eccbc4312b4ce1cfd2d4)。
- [AgileX python-can-agx-cando：`fbd76e5c3e6b6d9b30eeb0610c5b595994d8ad94`](https://github.com/agilexrobotics/python-can-agx-cando/tree/fbd76e5c3e6b6d9b30eeb0610c5b595994d8ad94)。

开发环境为 Linux。此 Windows 交付包含源码和可双击入口，已做可在该环境完成的静态与参数分发检查；**尚未在实际 Windows 电脑上验证批处理启动、DLL 加载或 PiPER X 实机通信与运动**。运行模拟界面成功与真实机械臂测试成功是两个不同的验证阶段。
