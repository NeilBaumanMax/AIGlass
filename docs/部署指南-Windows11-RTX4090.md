# Edith 部署指南 · Windows 11 + RTX 4090

当前电脑仅用于开发和联调。开发完成后，电脑后端迁移到另一台 **Windows 11 x64 + NVIDIA RTX 4090** 电脑，眼镜继续使用 Pico Zero Linux 板。

这份指南对应当前仓库代码，会随开发更新。**目前没有在目标 4090 电脑完成部署验收，也没有完成 IMX415 实拍验收。** 开发机的性能数字不能当作 4090 的性能承诺。已验证项目与待验收项目见[施工记录](施工记录.md)。

需要 nanoMuse 统一 AI 和操作手机时，先完成本指南的基础环境，再按 [nanoMuse 接入指南](nanoMuse接入.md) 构建桌面接入层、配置千问、登录并绑定手机。眼镜端继续使用现有 Linux 客户端。下面的直连千问流程保留用于分步验收。

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
| 显卡 | RTX 4090；安装支持 CUDA 12.6 的 NVIDIA Windows 驱动 |
| Python | **3.11 x64**；开发机验证版本为 3.11.9 |
| PyTorch | **2.6.0 + CUDA 12.6（cu126）** |
| 其余 Python 依赖 | 仓库 `requirements.txt` 中固定的已验证版本 |
| 命令行工具 | Git for Windows、PowerShell、Windows `tar` |
| 本地提示音 | Windows SAPI 中文 **Huihui** 语音 |
| 板子部署 | Android SDK Platform-Tools 中的 `adb.exe` |

当前完整音频链路依赖 Windows SpeexDSP DLL 和 SAPI；这不是 Ubuntu/WSL 的部署指南。代码仍使用 `audioop`，按 Python 3.11 安装，不直接换成 Python 3.13 或更高版本。

官方下载入口：[Git](https://git-scm.com/downloads/win)、[Python 3.11.9 x64 安装包页面](https://www.python.org/downloads/release/python-3119/)、[NVIDIA 驱动](https://www.nvidia.com/en-us/drivers/)、[PyTorch 对应版本命令](https://pytorch.org/get-started/previous-versions/#v260)、[ADB Platform-Tools](https://developer.android.com/tools/releases/platform-tools)。Python 3.11.9 是本项目验证基线，不是当前最新 Python。

安装后新开 PowerShell，确认：

```powershell
git --version
py -3.11 --version
tar --version
nvidia-smi
```

`nvidia-smi` 应显示 RTX 4090 和正常驱动。其显示的 CUDA 版本表示驱动支持能力，未必与 PyTorch 包版本相同；后面的 Python CUDA 检查才是本项目实际运行结果。本指南使用预编译 PyTorch wheel，不需要为了本项目额外编译 CUDA Toolkit。

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

预期包含 `2.6.0+cu126`、`12.6`、RTX 4090 和 `4.0`。如果失败，先解决驱动/PyTorch 环境，不能把 CPU 回退当作 GPU 部署通过。

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

脚本将当前代码中的“我在，请说”、模式切换、退出、视觉方向等提示语生成到 `.local/prompts/*.wav`。如果没有 Huihui，安装 Windows 中文语音组件后重新确认；也可以复制同一代码版本在开发机生成的整个 `.local/prompts` 目录，再运行预检。仅有模型而没有提示音时，设备可能识别成功却没有可播放的本地应答。

## 6. 配置千问北京地域

只在首次部署、尚无 `.env` 时复制模板：

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
notepad .env
```

填入你在百炼北京地域开通的 API Key：

```dotenv
DASHSCOPE_API_KEY=填写你自己的北京地域密钥
QWEN_MODEL=qwen3-omni-flash
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
```

密钥留在 4090 电脑本地，不放到板子、不提交 GitHub。还需要该模型访问权限、可用额度及互联网连接。后端重启后读取配置；已存在的同名进程环境变量优先于 `.env`。

普通提问发送语音和本地指令文字；明确说“看看当前画面”时发送文字和当前新鲜图像。未唤醒音频仅在电脑本地处理。[百炼 Qwen-Omni 接口说明](https://help.aliyun.com/zh/model-studio/qwen-omni)

## 7. 先验证电脑环境

```powershell
.\.venv\Scripts\python.exe scripts/check-env.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe scripts/check-vision.py
```

`check-env.py` 只读检查 Python、依赖、CUDA 运算、子模块版本、视觉权重、唤醒/ASR/AEC 加载、本地提示音及密钥是否已填；不输出密钥，不连接千问，不修改板子。最终应显示 `READY for device tests`。这不代表云端鉴权、额度和实机音频已经通过。

`check-vision.py` 实际加载模型，在室内/室外及三种尺寸上推理，检查方向输出、初始化测试图不外泄和断流清除。其输入是生成测试图，不是实景准确率测试，也不会替换正式服务的摄像头来源。

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

它在 `0.0.0.0:7860` 监听，首次生成新的 `.local/device-token`。新电脑使用刚创建的 `.venv`；启动脚本仅为兼容开发环境保留 `.runtime` 优先查找，不要迁移旧 `.runtime`。首次模型加载和 CUDA 预热期间，网页会显示加载中。

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

这是针对开发现场的兼容选项，不是所有网络都必须关闭 Wi-Fi 6。开发现场仅完成临时参数与 5 分钟实际音频观察；持久化工具已有自动测试，尚待实际重启验收。不要把这段记录当成 4090 电脑的验收结果。

## 10. 摄像头接入与完整验收

摄像头是 **IMX415-98 IR-CUT Camera**，通过 CSI 连接，不占 USB。断电安装并核对排线方向，再按照 [Pico Zero CSI 官方说明](https://wiki.luckfox.com/zh/Luckfox-Pico-Zero/CSI-Camera/)核对系统支持、驱动、IQ/ISP 配置、rkipc 服务和实际出流地址。

当前板子发现过 IMX415 驱动/IQ 文件，但摄像头尚未到手；仅有文件不能证明设备树绑定和真实出图成功。更换服务器不自动解决摄像头适配，摄像头固件步骤须在实物验收后补入本指南。

按顺序验收并记录目标机器的代码提交、GPU、驱动和耗时：

| 检查项 | 通过标准 |
| --- | --- |
| 环境 | `check-env.py` 通过，实际 GPU 为 RTX 4090 |
| 模型 | `check-vision.py` 两模式通过，网页视觉引擎 ready/CUDA |
| 联网 | 网页显示实际设备 IP、Linux、心跳；麦克风持续在线 |
| 唤醒 | 正常音量说“嗨，Edith”，听到“我在，请说” |
| 对话 | 提问后有喇叭回答，网页显示用户与 Edith 的真实对话 |
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
| 设备 HTTP 401 | 新服务器令牌与板端不一致，重新执行部署脚本 |
| 超时/麦克风离线 | 服务器 IP、热点/路由器、端口、防火墙、AP 隔离和板端日志 |
| 千问失败 | `.env`、北京地域和模型权限、额度、互联网连接；配置存在不等于鉴权成功 |
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
