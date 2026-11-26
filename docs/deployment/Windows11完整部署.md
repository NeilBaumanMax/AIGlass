# 从 GitHub 部署完整 Edith 后端 · Windows 11

本指南面向第一次拿到仓库的人，从空目录开始，在自己的 **Windows 11 x64 + NVIDIA CUDA 显卡**电脑上安装完整后端。RTX 4090 是项目计划的目标机器；目前开发机验证使用 RTX 4060 Laptop。其他显卡按实际 CUDA 检查和推理测试验收，不承诺帧率。完整路径包括网页、视觉、唤醒/ASR、AEC、语音播放、nanoMuse 电脑工具与千问。

这份指南对应当前仓库代码，会随开发更新。**目前没有在目标 4090 电脑完成部署验收，也没有完成 IMX415 实拍验收。** 开发机的性能数字不能当作 4090 的性能承诺。已验证项目与待验收项目见[施工记录](../development/施工记录.md)。

完整 AI 使用 `AI_BACKEND=nanomuse`；第 6 节包含桌面端接入。模板默认的 `qwen` 用于基础对话联调，不具备电脑/手机执行工具。没有眼镜时可以完成电脑软件部署和模型检查；麦克风、喇叭、摄像头验收需要相应硬件，网页不提供输入替代。

## 快速安装路线

先按第 2 节准备 Python 3.11 x64、Git、NVIDIA 驱动与 Windows 中文 Huihui 语音，然后运行：

```powershell
git clone --recurse-submodules https://github.com/NeilBaumanMax/AIGlass.git
Set-Location AIGlass
Set-ExecutionPolicy -Scope Process RemoteSigned
.\scripts\setup-backend.ps1
notepad .env
```

脚本完成第 3–5 节的电脑环境与素材安装，不启动后端、不修改板子、不填写密钥、不自动登录 nanoMuse。然后继续 **第 6 节配置 AI → 第 7 节检查 → 第 8–9 节联网与启动 → 第 10 节验收**。如果只部署电脑后端，可以暂缓 ADB/板端步骤，网页会显示设备离线。

安装会下载 PyTorch、模型和工具，需保持互联网可用。失败后修复网络或组件再重试；脚本不会覆盖已有 `.env`。可用 `-Stage Environment` 只安装 Python 环境，用 `-Stage Assets` 只安装模型/提示音，用 `-Plan` 查看计划。Python 未注册到 `py` 时指定 `-PythonPath 'C:\实际路径\python.exe'`；必须是完整 Python 3.11 x64，不能使用嵌入版替代 venv 安装器。

第 3–5 节保留逐步安装命令便于排错；快速脚本成功后不用再重复下载。运行时新部署统一使用 `.venv`。

## 1. 部署后的设备关系

```text
Pico Zero · Buildroot Linux                    Windows 11 · RTX 4090
  IMX415 摄像头 ─── RTSP 视频（局域网） ──────→ WalkGuide / CUDA
  板载麦克风   ─── PCM + 播放参考（HTTP） ───→ 本地唤醒 / Vosk / 消回声
  腔体喇叭     ←── 语音、播放/取消指令 ─────── 本地提示音 / 千问语音
                                               │
                                               ├─ 浏览器只读控制台 + 清空对话展示
                                               └─ 百炼北京 API（需互联网）
```

麦克风上传与播放指令下行并行进行。设备端 API 使用令牌认证；控制台是单设备局域网 Demo，尚未提供多用户登录。部署在可信局域网内，不需要公网端口映射。

眼镜必须和 **4090 电脑** 网络互通；开发机可以关闭。可以让两者连接同一路由器，或由 4090 电脑开启 2.4 GHz 热点。Pico Zero 的无线只支持 2.4 GHz。USB 用于初次部署/调试和供电，运行时音视频走局域网；拔掉唯一电源会关机，脱离电脑 USB 需要独立供电。

## 2. 准备软件

| 项目 | 本指南使用的基线 |
| --- | --- |
| 系统 | Windows 11，x64 |
| 显卡 | NVIDIA CUDA 显卡；驱动支持 CUDA 12.6；目标 RTX 4090 |
| Python | **3.11 x64**；开发机验证版本为 3.11.9 |
| PyTorch | **2.6.0 + CUDA 12.6（cu126）** |
| 其余 Python 依赖 | 仓库 `requirements.txt` 中固定的已验证版本 |
| 命令行工具 | Git for Windows、PowerShell、Windows `tar` |
| 本地提示音 | Windows SAPI 中文 **Huihui** 语音 |
| 板子部署 | Android SDK Platform-Tools 中的 `adb.exe` |
| nanoMuse 构建 | Node.js 24、pnpm 11.25.0、Git；桌面接入固定 1.0.9 |
| 模型账号 | 自己的百炼北京 API Key，支持所选千问聊天/视觉模型与 TTS；nanoMuse 登录账号 |

当前完整音频链路依赖 Windows SpeexDSP DLL 和 SAPI；这不是 Ubuntu/WSL 的部署指南。代码仍使用 `audioop`，按 Python 3.11 安装，不直接换成 Python 3.13 或更高版本。

官方下载入口：[Git](https://git-scm.com/downloads/win)、[Python 3.11.9 x64 安装包页面](https://www.python.org/downloads/release/python-3119/)、[NVIDIA 驱动](https://www.nvidia.com/en-us/drivers/)、[PyTorch 对应版本命令](https://pytorch.org/get-started/previous-versions/#v260)、[ADB Platform-Tools](https://developer.android.com/tools/releases/platform-tools)。Python 3.11.9 是本项目验证基线，不是当前最新 Python。

安装后新开 PowerShell，确认：

```powershell
git --version
py -3.11 --version
tar --version
nvidia-smi
```

`nvidia-smi` 应显示实际显卡和正常驱动。其显示的 CUDA 版本表示驱动支持能力，未必与 PyTorch 包版本相同；后面的 Python CUDA 检查才是本项目实际运行结果。本指南使用预编译 PyTorch wheel，不需要为了本项目额外编译 CUDA Toolkit。

以下命令默认在普通 PowerShell 执行；只有防火墙规则需要管理员权限。如果 PowerShell 禁止运行本仓库脚本，可在当前窗口设置 `Set-ExecutionPolicy -Scope Process RemoteSigned`。

## 3. 获取项目和建立独立环境

选择任意本地目录，不需要保留开发机的盘符或用户名：

```powershell
git clone --recurse-submodules https://github.com/NeilBaumanMax/AIGlass.git
Set-Location AIGlass
git submodule update --init --recursive
git rev-parse HEAD
git -C vendor/walkguide rev-parse HEAD

py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install torch==2.6.0 --index-url https://download.pytorch.org/whl/cu126
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip check
```

如果仓库为私有，需要先给该电脑的 Git 配置你的 GitHub 访问权限。下载 ZIP 不会自动包含子模块，优先使用上述 Git 克隆方式。

当前 WalkGuide 固定提交为 `1bd27dd1a90d5b169074588a3487611f40af4716`。迁移使用主仓库记录的子模块版本，**不要自行执行 `git submodule update --remote`**；将来升级视觉应连同适配代码、提示音和测试一起发布。

先装 cu126，再装项目依赖，避免意外装成 CPU 版 PyTorch。本项目使用 `opencv-python-headless`，不需要桌面 OpenCV 窗口，也不应同时安装 `opencv-python`。无需安装整个 CUDA 开发 SDK、torchvision 或 torchaudio 来运行目前的应用。

检查实际 GPU：

```powershell
.\.venv\Scripts\python.exe -c "import torch; print(torch.__version__, torch.version.cuda); assert torch.cuda.is_available(); print(torch.cuda.get_device_name(0)); print(torch.ones(4, device='cuda').sum().item())"
```

预期包含 `2.6.0+cu126`、`12.6`、实际显卡名称和 `4.0`。如果失败，先解决驱动/PyTorch 环境，不能把 CPU 回退当作 GPU 部署通过。

## 4. 安装视觉、唤醒模型和消回声库

在项目根目录执行：

```powershell
New-Item -ItemType Directory -Force .local, models, .tools | Out-Null
.\.venv\Scripts\python.exe vendor/walkguide/setup_models.py

Invoke-WebRequest -Uri 'https://alphacephei.com/vosk/models/vosk-model-small-cn-0.22.zip' -OutFile .local/vosk-cn.zip
Expand-Archive -Path .local/vosk-cn.zip -DestinationPath models -Force

.\scripts\install-wake.ps1
.\scripts\install-aec.ps1
```

`setup_models.py` 从 NVIDIA 的 Hugging Face 仓库下载室内 ADE20K 与室外 Cityscapes SegFormer-B2 权重。目录应为：

```text
vendor/walkguide/model-indoor/config.json + pytorch_model.bin
vendor/walkguide/model-outdoor/config.json + pytorch_model.bin
models/vosk-model-small-cn-0.22/am、conf、graph、ivector
models/sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20/...
.tools/speexdsp/mingw64/bin/libspeexdsp-1.dll
```

唤醒和 SpeexDSP 安装脚本会核对下载包 SHA-256。模型解压后不要多套一层同名文件夹。[Vosk 官方模型页](https://alphacephei.com/vosk/models)

这些目录没有随主仓库提交。可以重新下载，也可以从开发机复制对应目录及其许可文件，之后必须运行预检和真实模型检查。不要复制开发机的 `.runtime` 或 `.venv` 到新电脑代替安装。

下载失败时先确认目标电脑能访问 GitHub、Hugging Face、PyTorch 和 MSYS2 官方站点。若需要代理，使用目标电脑自己的配置；不要照搬开发机的代理端口。下载代理不应覆盖局域网通信。

## 5. 生成本地提示音

先确认 Windows 安装了中文简体语音，并且 64 位 SAPI 可枚举到 Huihui：

```powershell
$speaker = New-Object -ComObject SAPI.SpVoice
$speaker.GetVoices() | ForEach-Object { $_.GetDescription() }
.\scripts\make-prompts.ps1
```

脚本将当前代码中的“我在，请说”、模式切换、退出、视觉方向、断流与恢复等 19 条提示语生成到 `.local/prompts/*.wav`。如果没有 Huihui，安装 Windows 中文语音组件后重新确认；也可以复制同一代码版本在开发机生成的整个 `.local/prompts` 目录，再运行预检。仅有模型而没有提示音时，设备可能识别成功却没有可播放的本地应答。更新提示音后正常重启后端才能加载。

## 6. 配置完整 AI：nanoMuse + 千问北京地域

只在首次部署、尚无 `.env` 时复制模板：

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
notepad .env
```

填入你在百炼北京地域开通的 API Key：

```dotenv
DASHSCOPE_API_KEY=填写你自己的北京地域密钥
AI_BACKEND=nanomuse
NANOMUSE_BRIDGE_URL=http://127.0.0.1:18765
QWEN_TTS_MODEL=qwen3-tts-flash
QWEN_TTS_VOICE=Cherry
```

密钥留在 4090 电脑本地，不放到板子、不提交 GitHub。还需要该模型访问权限、可用额度及互联网连接。后端重启后读取配置；已存在的同名进程环境变量优先于 `.env`。

### 6.1 安装桌面运行组件与桥接

1. 从 [nanoMuse 1.0.9 官方 Release](https://github.com/nano-muse/nanoMuse/releases/tag/v1.0.9) 安装 Windows x64 桌面版。它提供本项目已验证的电脑控制运行组件。记下 `nanomuse-desktop.exe` 所在目录；未知新版本不能直接套用本版插件。
2. 安装 [Node.js](https://nodejs.org/en/download) 24，打开新 PowerShell，安装本项目使用的 pnpm，然后构建桥接。

```powershell
node --version
npm install --global pnpm@11.25.0
pnpm --version
.\scripts\setup-nanomuse.ps1
```

脚本下载固定版本源码到 `.tools/nanomuse`，构建并测试插件和桌面资源。需要代理时按自己的网络追加 `-Proxy http://127.0.0.1:实际端口`。配置、账号和源码均在本机，不随 Git 发布。

3. 从 nanoMuse 的菜单或托盘**正常退出**，然后安装桥接并重新打开。将示例目录替换为实际安装目录，不是快捷方式所在目录：

```powershell
$NanoMuseApp = 'C:\Apps\nanoMuse' # 其中必须存在 nanomuse-desktop.exe
.\scripts\install-nanomuse-bridge.ps1 -AppRoot $NanoMuseApp
.\scripts\start-nanomuse.ps1 -InstalledApp $NanoMuseApp
```

安装脚本先验证插件/依赖版本并备份，再更新桥接；不覆盖账号、历史和绑定。**日常也用这个启动脚本**；普通官方快捷方式不会启用眼镜接口。源码桌面可用于桥接开发，但只构建源码不代表电脑鼠标键盘运行组件已齐全，完整电脑操作部署使用上述官方安装路径。

### 6.2 登录、选择模型与检查

在 nanoMuse 桌面登录自己的账号，添加百炼北京密钥，明确选择支持图像输入和工具调用的千问模型。开发机验证使用 `qwen3.5-plus`；以自己的账号授权为准。上游默认百炼聊天模型可能是 DeepSeek，添加供应商后仍需选中千问。`.env` 中的 Key 用于 Edith 语音服务，**不会自动配置 nanoMuse 的模型凭据**，两处都需配置。

```powershell
.\.venv\Scripts\python.exe scripts/check-nanomuse.py
```

应显示 `desktop_bridge: online`、`protocol: 1`、`signed_in: true`。手机暂不使用时 `online_phones: 0` 正常。先在 nanoMuse 内验证“看看电脑屏幕”与“打开记事本”，取屏核实工具结果；接口在线不代表模型权限或动作成功。手机控制再安装官方手机端、登录同一账号、配置千问并完成其权限检查。

AI 任务和看图由 nanoMuse 处理，千问 TTS 朗读实际结果；本地唤醒和 WalkGuide 不依赖云端对话。完整协议、确认、升级/回退、已有账号处理见 [nanoMuse 接入](nanoMuse接入.md)。

### 6.3 可选：先验证基础对话

如果暂不安装 nanoMuse，将 `.env` 设为 `AI_BACKEND=qwen`，并保留 `QWEN_MODEL=qwen3-omni-flash`、`DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1`。该模式有视觉、唤醒、语音对话与主动看眼前画面，**没有电脑或手机工具**，不是完整 Agent 验收。

直连模式普通提问使用语音和本地指令文字，看图使用文字和当前图片，不同时上传图片和音频。未唤醒音频仅在电脑本地处理。[百炼 Qwen-Omni 接口说明](https://help.aliyun.com/zh/model-studio/qwen-omni)

## 7. 先验证电脑环境

```powershell
.\.venv\Scripts\python.exe scripts/check-env.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe scripts/check-vision.py
.\.venv\Scripts\python.exe scripts/check-guidance.py
.\.venv\Scripts\python.exe scripts/check-docs.py
```

`check-env.py` 只读检查 Python、依赖、CUDA 运算、子模块版本、视觉权重、唤醒/ASR/AEC、本地提示音、密钥是否已填和 AI 后端选择。选择 nanoMuse 时还读取本机接口并核对登录；不执行电脑/手机动作、不输出密钥、不连接千问或修改板子。最终应显示 `READY for device tests`。这不代表云端鉴权、额度、实际工具或实机音频已经通过。

`check-vision.py` 实际加载模型，在室内/室外及三种尺寸上推理，检查方向输出、初始化测试图不外泄和断流清除。其输入是生成测试图，不是实景准确率测试，也不会替换正式服务的摄像头来源。

摄像头未到货时，还可以运行 `.\.venv\Scripts\python.exe scripts/check-guidance.py` 检查识别结果如何转成语音。生成的 `.local/guidance-demo/report.json` 和 `preview.wav` 明确标记模拟场景，不连接在线眼镜。完整时序、优先级、过期结果处理及实景验收边界见 [视觉语音提醒](../architecture/视觉语音提醒.md)。

## 8. 让板子连接新电脑所在网络

### 8.1 安装 ADB 和检查原有 Linux

从 [Google 官方 Platform-Tools 页面](https://developer.android.com/tools/releases/platform-tools) 下载 Windows ZIP，解压到项目 `.tools`，最终路径必须为 `.tools/platform-tools/adb.exe`。通过支持数据传输的 USB 线连接板子后：

```powershell
.\.tools\platform-tools\adb.exe devices
.\.tools\platform-tools\adb.exe shell uname -a
.\.tools\platform-tools\adb.exe shell 'python3 --version; command -v arecord; command -v aplay; command -v iw; command -v wpa_cli'
```

使用同一块已经开发完成的板子，**换服务器不需要重新刷 Linux**。现有板子运行 Buildroot Linux 5.10.160，音频客户端在 `/userdata/aiglass`，自启动服务为 `/etc/init.d/S98aiglass`。新板子则先按 [Luckfox Pico Zero 官方文档](https://wiki.luckfox.com/zh/Luckfox-Pico-Zero/WiFi-BT/)准备匹配的系统和驱动；上述组件缺失时不能直接当作已配置板子部署。

ADB 找不到设备时，先检查数据线、Windows 设备管理器和对应板卡 USB 驱动。ADB 是部署通道，不是运行中的音视频传输通道。

### 8.2 选择网络并确定实际 IP

推荐同一路由器：4090 电脑可用网线，板子连接该路由器的 2.4 GHz Wi-Fi；也可以在 4090 电脑上开启 2.4 GHz 移动热点。两者必须允许相互访问，访客网络/AP 隔离可能阻止通信。

如果继续使用同名热点，须在新电脑上配置相同 SSID 和密码。若网络凭据变化，需要更新板子的 Wi-Fi 配置。先在交互式 ADB shell 中查看进程使用哪个文件：

```powershell
.\.tools\platform-tools\adb.exe shell
```

```sh
ps -ef | grep wpa_supplicant
iw dev wlan0 link
ip -4 addr show wlan0
ip route
```

本开发板的原厂 `rkwifi_server` 使用 `/data/wpa_supplicant.conf`；官方手动配置示例使用 `/etc/wpa_supplicant.conf`，项目备用启动脚本也引用后者。**以目标板的实际启动方式为准**，不要只改一个未被读取的文件，或另起第二套无线管理服务。凭据格式及板载天线 GPIO123 设置见 [官方网络说明](https://wiki.luckfox.com/zh/Luckfox-Pico-Zero/WiFi-BT/)。已有板子应保留已验证的天线与自启动设置。

例如确认进程确实使用 `/data/wpa_supplicant.conf` 后，在板子 shell 执行 `vi /data/wpa_supplicant.conf`，修改现有 `network={...}` 中的 `ssid` 和 `psk`，保留其他设置，再执行 `wpa_cli -i wlan0 reconfigure`。不要把示例路径当作所有固件的统一位置。

等待重新关联后确认 `iw ... link` 已连接、`wlan0` 取得 IP；也可重启板子确认自动连接。Wi-Fi 密码不写进仓库或施工记录。退出 shell 后，在电脑运行 `ipconfig`，找出与板子互通的本地 IPv4 地址。

后文示例中的 `192.168.137.1` 只是 Windows 热点常见电脑地址；**替换成 4090 电脑的实际地址**。不把开发机的 IP、MAC 或旧 `config.json` 原样复制过去。为稳定演示，可在路由器为电脑和板子保留 DHCP 地址。

### 8.3 防火墙

在 4090 电脑上以管理员身份打开 PowerShell，允许局域网设备访问后端 TCP 7860：

```powershell
New-NetFirewallRule -DisplayName 'Edith LAN demo' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 7860 -RemoteAddress LocalSubnet -Profile Any
```

若网络跨子网，将 `LocalSubnet` 换成板子所在的明确网段。无需关闭整个防火墙。电脑还须能访问板子的实际 RTSP 地址（通常端口 554），并能访问百炼 HTTPS 服务。

## 9. 启动后端并重新部署板端配置

在项目根目录的第一个 PowerShell 窗口启动：

```powershell
.\start.ps1
```

它在 `0.0.0.0:7860` 监听，首次生成新的 `.local/device-token`。启动脚本优先选择 `.venv`，仅在没有 `.venv` 时兼容开发机的 `.runtime`，不要迁移旧环境。首次模型加载和 CUDA 预热期间，网页会显示加载中。完整模式应先从第 6 节脚本启动 nanoMuse，再启动后端。

保持该窗口运行，在第二个 PowerShell 窗口进入相同项目根目录：

```powershell
$ServerIp = '192.168.137.1' # 替换为这台 4090 电脑的局域网 IPv4
.\scripts\deploy-device.ps1 -Server "http://${ServerIp}:7860"
```

有多台 ADB 设备时，增加 `-Serial`，其值取自 `adb devices`。部署脚本会复制客户端和启动服务，使用 **新电脑的设备令牌、服务器地址及核实过的 MAC** 重写板端配置，然后重启板端音频服务。无需在网页输入令牌。

打开 [本机控制台](http://127.0.0.1:7860)。设备握手后自动使用其 IP 作为 RTSP 来源，通常无需指定眼镜 IP。需要固定来源时才使用：

```powershell
.\start.ps1 -Glasses 192.168.1.54 # 替换为眼镜的实际 IP；先停掉原来的后端
```

同一端口只运行一个后端。更改 `-Port` 时，防火墙和板端 `-Server` 端口必须同步调整。浏览器关闭不影响后端处理；关闭运行终端、电脑休眠或关机则会停止服务。目前电脑端是手动启动，尚未安装 Windows 自启动服务。

### 可选：Windows 热点兼容模式

仅在复现“Wi-Fi 已关联但音频请求反复超时”时考虑：

```powershell
.\scripts\deploy-device.ps1 -Server "http://${ServerIp}:7860" -LegacyWifi
.\.tools\platform-tools\adb.exe reboot
```

这会先备份原厂模块加载脚本，再设置 AIC8800 `he_on=0`，下次启动使用 802.11n。恢复默认：

```powershell
.\.tools\platform-tools\adb.exe shell 'python3 /userdata/aiglass/wifi_compat.py default'
.\.tools\platform-tools\adb.exe reboot
```

这是针对开发现场的兼容选项，不是所有网络都必须关闭 Wi-Fi 6。2026-11-26 已在板子重启后确认 `he_on=N`，同时开启实际视频与双向音频，60 秒、1149 次状态采样未出现离线。此前临时参数曾通过 5 分钟音频观察；这些有限观察不代表长期稳定性或另一台 4090 电脑验收。

## 10. 摄像头接入与完整验收

摄像头是 **IMX415-98 IR-CUT Camera**，通过 CSI 连接，不占 USB。断电安装并核对排线方向，再按照 [Pico Zero CSI 官方说明](https://wiki.luckfox.com/zh/Luckfox-Pico-Zero/CSI-Camera/)核对系统支持、驱动、IQ/ISP 配置、rkipc 服务和实际出流地址。

2026-11-26，开发板现有 Buildroot Linux 5.10.160 已实际读到 IMX415 ID `0000e0`、绑定 MIPI/ISP 并输出真实彩色 RTSP。没有重新刷机。本次发现原厂启动入口未启动 rkipc，因此增加独立服务；其他系统镜像仍须按官方说明核对支持，不能只复制文件就声称适配完成。

板子已使用本指南的 Linux 与音频客户端、ADB 已连接时执行：

```powershell
.\scripts\deploy-camera.ps1
.\.tools\platform-tools\adb.exe shell '/etc/init.d/S97aiglass-camera status'
```

脚本从板载 `/oem/usr/share/rkipc-imx415-500w.ini` 生成独立的 `/userdata/aiglass/camera.ini`，保留原厂传感器、IQ、曝光和 IR-CUT 设置。视频设为 H.264、1280×720、15 fps、约 1.5 Mbps，关闭 rkipc 的音频、其他编码通道和录像，麦克风/喇叭继续由 Edith 音频客户端负责。后端从板子握手 IP 自动选择 `rtsp://板子IP/live/0`；实际处理预览缩放至不超过 960×960，原图和分割保持同帧。

`S97aiglass-camera` 开机启动，并显式设置厂商库路径，避免启动阶段找不到 `librockit.so`。已验证重启后 RTSP 554 监听、音频和画面恢复。配置更新时若已有服务运行，安装脚本不会擅自杀掉其他 rkipc；确认是本项目实例后按需执行：

```powershell
.\.tools\platform-tools\adb.exe shell '/etc/init.d/S97aiglass-camera restart'
.\.tools\platform-tools\adb.exe shell 'tail -n 60 /tmp/aiglass-camera.log'
```

停止视频用 `.../S97aiglass-camera stop`，音频服务独立运行。脚本仅会终止 PID、可执行文件和配置参数都匹配的本项目实例。部署前若已有 Edith 配置，会备份为 `camera.ini.bak`；要回退先停止视频，恢复该文件后再启动。原厂 INI 和 `/userdata/rkipc.ini` 不修改；如需禁用开机视频，可将 `/etc/init.d/S97aiglass-camera` 移出 init.d 并保存在 `/userdata/aiglass/`。

网页可见时最多每秒轮询约 10 次，后台标签页降低频率；这不是模型处理帧率保证。开发机最终 60 秒采样为采集约 14.9 fps、处理约 4.3 fps、推理中位数 234 ms；浏览器 15 秒实际更新 59 帧，无脚本错误。没有测量镜头到显示器的完整延迟。

按顺序验收并记录目标机器的代码提交、GPU、驱动和耗时：

| 检查项 | 通过标准 |
| --- | --- |
| 环境 | `check-env.py` 通过，实际 GPU 与目标配置一致；4090 迁移时必须显示 RTX 4090 |
| 模型 | `check-vision.py` 两模式通过，网页视觉引擎 ready/CUDA |
| 联网 | 网页显示实际设备 IP、Linux、心跳；麦克风持续在线 |
| 唤醒 | 正常音量说“嗨，Edith”，听到“我在，请说” |
| 对话 | 提问后有喇叭回答，网页显示用户与 Edith 的真实对话 |
| 电脑工具 | nanoMuse 取屏、打开空白记事本、输入测试文字，眼镜读出实际内容 |
| Agent 确认/取消 | 只批准当前任务；插话后核对任务终态，不凭模型回复判定取消成功 |
| 连续对话 | 播报结束后保持安静约 8 秒，听到“对话结束” |
| 插话 | AI 播报时说“停一下，切换室外模式”，播报停下且新指令被执行 |
| 模式 | 室内/室外语音切换与网页状态、分割结果同步 |
| 实拍 | 原图和分割对应同一帧，显示来自眼镜的画面；断流清除旧图和方向 |
| 主动看图 | 明确要求看画面时得到基于当前帧的回复；无画面时明确提示 |
| 视觉提醒 | 实景验证方向线、暂停/障碍/台阶提醒，不把像素方向当作测距 |
| 网页 | 无麦克风/文字输入入口；可清空展示对话，刷新后不恢复已清记录 |
| 独立运行 | 关闭浏览器仍能唤醒/对话；眼镜独立供电仍与 4090 电脑通信 |
| 恢复 | 断网后状态离线、恢复后重新握手；板子重启后自动连接 |
| 稳定性 | 同时开启真实视频和双向语音做持续观察，记录掉线和延迟 |

没有摄像头时可以验收音频、网页、软件推理，但“完整 Demo”和实景视觉项目保持待验收。

## 11. 日志、更新和迁移清单

电脑日志在启动终端输出；可在启动时使用 `Start-Transcript -Path .local/server-session.log` 保存终端记录。设备日志：

```powershell
.\.tools\platform-tools\adb.exe shell 'tail -n 60 /tmp/aiglass-client.log'
Invoke-RestMethod http://127.0.0.1:7860/api/status
```

`/api/status` 包含对话记录，不要直接把输出作为公开故障附件。设备密钥配置文件也不需要打印。

| 现象 | 优先检查 |
| --- | --- |
| GPU 检查失败/显示 CPU | 驱动、Python x64、是否安装 cu126；运行环境是否是项目 `.venv` |
| 模型加载失败 | 子模块版本、两个模型目录完整性、下载是否中断 |
| 唤醒模型/AEC 报错 | KWS/Vosk 解压层级、SpeexDSP DLL、预检输出 |
| 识别了但无提示音 | `.local/prompts` 是否生成且与当前版本一致 |
| nanoMuse 执行中出现“对话结束”，或再次唤醒被当成问题 | 更新到带任务隔离/全阶段关键词检测的版本，生成提示音并正常重启后端；确认执行/TTS/播放期间 `idle_remaining` 为 null，播放完成后才从 8 开始 |
| 设备 HTTP 401 | 新服务器令牌与板端不一致，重新执行部署脚本 |
| 超时/麦克风离线 | 服务器 IP、热点/路由器、端口、防火墙、AP 隔离和板端日志 |
| 千问失败 | `.env`、北京地域和模型权限、额度、互联网连接；配置存在不等于鉴权成功 |
| nanoMuse 接口离线 | 是否通过带 `-InstalledApp` 的脚本启动、是否已装匹配插件、令牌文件是否存在 |
| 能聊天但不能操作电脑 | 是否 `AI_BACKEND=nanomuse`、模型支持工具/图像、官方桌面的电脑控制组件是否完整 |
| 无摄像头画面 | 先验证实际 RTSP 出流，再检查电脑源地址；不要用测试图冒充实拍 |

| 内容 | 迁移方式 |
| --- | --- |
| 应用、前端、板端脚本、文档 | 从 GitHub 克隆，记录部署 commit |
| WalkGuide 源码 | 跟随主仓库子模块固定版本 |
| `.venv` / `.runtime` / `.bootstrap` | 不复制；在新电脑重新建立环境 |
| 视觉、Vosk、KWS 模型 | 官方下载，或复制已验证目录并检查加载 |
| `.tools` | 按上述步骤安装 ADB 和 SpeexDSP |
| `.local/prompts` | 本机生成，或复制同版本提示音 |
| `.env` | 新电脑本地配置；不发布到 GitHub |
| `.local/device-token` / 板端 `config.json` | 新后端生成令牌，重新部署板端配置 |
| `.local/events.sqlite3` | 可选；需要历史时停掉两边后端后单独复制 |
| 诊断录音、截图、临时日志 | 默认不迁移，不提交仓库 |
| Wi-Fi 凭据、防火墙、IP/MAC | 按目标网络重新核对；开发机配置不作为默认值 |

更新时先停止电脑后端，保留本地 `.env` 等配置，再执行：

```powershell
git pull --ff-only
git submodule update --init --recursive
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\scripts\make-prompts.ps1
.\.venv\Scripts\python.exe scripts/check-env.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe scripts/check-vision.py
.\start.ps1
```

若更新说明改变了 PyTorch/CUDA 或模型版本，先按对应版本说明重新安装。板端代码变化时，在后端启动后重新执行部署脚本。回退时使用之前记录的应用 commit 和其子模块版本，再匹配依赖、提示音及板端客户端，不只单独回退一个 Python 文件。
