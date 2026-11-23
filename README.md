# Edith · AIGlass

**当前电脑仅用于开发和联调；开发完成后，部署到另一台 Windows 11 + RTX 4090 电脑。** 新电脑独立运行后端，眼镜连接新电脑所在局域网，运行时不依赖开发机。

## 在 RTX 4090 电脑上部署

请按 [Windows 11 + RTX 4090 完整部署指南](docs/部署指南-Windows11-RTX4090.md) 从头安装。指南包含 Git 子模块、Python 3.11 / CUDA PyTorch、视觉与唤醒模型、消回声库、提示音、ADB、千问配置、局域网、防火墙、板端地址与令牌迁移、启动、更新及验收。

新增 [nanoMuse 桌面端接入指南](docs/nanoMuse接入.md)：眼镜作为语音终端，电脑 nanoMuse 使用千问。已实测电脑取屏、打开记事本、输入测试文字，用户已确认能通过眼镜唤醒并听到记事本内容；手机操作按用户要求稍后联调。支持复用已有 nanoMuse 安装和账号。现有直连语音通过 `AI_BACKEND=qwen` 保留，完成配置后使用 `AI_BACKEND=nanomuse` 切换。

目标电脑尚未实机验收。现有程序仍是开发中的局域网 Demo，摄像头实拍与完整插话稳定性仍需验证。以下为功能概览和开发机使用说明，迁移时不照搬开发机的 IP、目录或凭据。

眼镜端使用 Luckfox Pico Zero RV1106G3、Buildroot Linux、IMX415-98 IR-CUT Camera、板载麦克风和外接喇叭。摄像头接 CSI，电脑通过局域网接收视频与音频。网页显示设备状态、视频、分割和对话，允许清空对话展示记录。后台处理独立于浏览器。IMX415 目前尚未到手，真实摄像头链路待验收。

## 启动电脑后端

```powershell
.\start.ps1 -Glasses 192.168.137.54
```

将地址替换为眼镜的 Wi-Fi 地址，打开 <http://127.0.0.1:7860> 查看画面、分割结果和事件。板子尚无摄像头时，视频离线是实际状态。开发测试可在命令行运行 `python app.py --test-video 文件路径`，页面会显示“后端测试录像”。

运行 `./start.ps1` 后，设备握手会自动配置其 Wi-Fi 地址作为 RTSP 来源，也可用 `-Glasses` 固定地址。唤醒词是“嗨，Edith”（伊迪丝）：电脑本地 sherpa-onnx 关键词模型与 Vosk 受限发音匹配共同检测完整短语，Vosk 也用于唤醒后的指令识别。发音匹配要求招呼词和名字一起出现；单说“嗨”、名字或“你的意思”不会触发。板子上传 16 kHz 双声道：左声道麦克风、右声道 DAC 播放参考。唤醒后可说“切换室内模式”“切换室外模式”“看看当前画面”或直接提问；说“结束对话”退出。支持连续对话，语音播放完成后 8 秒无新指令会播报“对话结束”。普通对话使用千问，只有明确要求看画面才附带新鲜图像。未唤醒时音频不发送千问。

电脑使用 SpeexDSP 消除喇叭回声，播放期间继续检测语音，支持插话停止当前回答并使迟到的云端回复失效。回声处理无法加载时退回轮流说话，网页明确显示异常。真人同时讲话的稳定性仍待完整验收。WalkGuide 连续多帧确认后播报，持续危险至少间隔 8 秒提醒、普通方向至少间隔 12 秒；遇到对话会按优先级处理，不提供米制距离。网页区域占比来自实际分割掩码，推理耗时不等于端到端延迟。

视觉已升级至 [WalkGuide `1bd27dd`](https://github.com/18941602006/walkguide-vision/commit/1bd27dd1a90d5b169074588a3487611f40af4716)（2026-11-22 北京时间核对的 main 最新版）。室内/室外分割均直接调用上游新增的方向规划与渲染：白色方向线、向前/偏左/偏右、通道不足时暂停确认及红色终点。网页显示当前帧的方向判断和部署版本，断流时清除旧判断。喇叭在连续多帧一致后播报变化；普通方向不打断对话，暂停、障碍和台阶提醒优先。方向只依据图像像素，没有定位、目的地、真实身体宽度或 ToF 距离，不作为实际通行保证。

[视觉语音提醒说明](docs/视觉语音提醒.md) 记录完整策略：视觉无需唤醒，使用本地提示音；新危险可中断 AI，普通方向在对话结束后重查；采集结果超过 1.5 秒停止用于提醒，摄像头未连接、断流及恢复有独立提示。网页“视觉语音提醒”卡片显示确认状态、等待对话、缺失提示音及最近发出的提醒。摄像头尚未到手，当前完成软件和离线模拟验收，实景提醒仍待验证。

## 配置语音和部署板端

在项目根目录 `.env` 中设置 `DASHSCOPE_API_KEY`，格式参考 `.env.example`。使用百炼北京地域的 `qwen3-omni-flash`，密钥只由电脑持有。`.env`、设备令牌和诊断录音均已排除于 Git。

```powershell
# 首次安装本地唤醒模型与 Windows 回声处理库
./scripts/install-wake.ps1
./scripts/install-aec.ps1
# 首次生成离线提示语，需 Windows 中文 Huihui 语音
./scripts/make-prompts.ps1
# 启动电脑后端后，通过 ADB 部署常驻音频客户端
./scripts/deploy-device.ps1 -Server http://192.168.137.1:7860
```

客户端使用设备原有 Python 3.11、arecord 和 aplay。`S98aiglass` 开机启动，断网后自动重新握手；诊断日志为 `/tmp/aiglass-client.log`，轮转上限约 256 KB。ADC 为 SingadcL，ALC 左声道 12，数字回环 Mode2 提供参考声道。USB 用于部署和供电，音频实际走 Wi-Fi；拔掉唯一供电线会关机，脱离电脑 USB 需另接稳定电源。

针对 Windows 热点存在“已关联但 ARP 解析失败”的情况，部署脚本会核对本机服务网卡的 MAC；仅当板子关联的热点 BSSID 与它一致时，固定该服务地址的邻居记录。热点变化时移除本程序的旧记录。连续 3 次网络失败且确认为关联/ARP 故障，或该已核实热点虽有固定邻居但持续超时/不可达时，自动请求重新关联，间隔至少 30 秒；HTTP 会话错误、认证错误和连接被拒绝不会触发 Wi-Fi 重置。

本机热点在 802.11ax 下仍曾周期性超时；临时将板端 AIC8800 设置为 `he_on=0`、改用 802.11n 后，一次 5 分钟实际双向音频观察中未再掉线。可选 `./scripts/deploy-device.ps1 -Server http://192.168.137.1:7860 -LegacyWifi` 会备份并配置驱动加载脚本，供板子下次启动使用。恢复默认可在板子运行 `python3 /userdata/aiglass/wifi_compat.py default`，同样下次启动生效。当前只完成临时参数验证，自动审批阻止了持久化部署，板子重启后临时参数会失效；详见施工记录步骤 9。

Windows 首次需要允许热点网段访问 TCP 7860。在管理员 PowerShell 运行：

```powershell
New-NetFirewallRule -DisplayName 'AIGlass Pico demo' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 7860 -RemoteAddress 192.168.137.0/24 -Profile Any
```

网页没有录音、文字输入或眼镜控制入口；唯一写操作为清空对话展示记录，不影响当前语音会话。对话与事件保存在忽略的 `.local/events.sqlite3`，重启后保留。当前单设备局域网 Demo 使用设备令牌认证上传和播放请求。

Qwen3-Omni 每次只接受文字与一种其他模态组合。因此普通问题使用文字和语音，看画面请求使用本地识别的指令文字和当前图片，不同时传入图片和音频。[官方接口说明](https://help.aliyun.com/zh/model-studio/qwen-omni)

## 环境与模型

本机使用项目目录内的 Python 3.11 运行环境与 CUDA PyTorch。新电脑可用以下命令安装。

```powershell
git submodule update --init --recursive
py -3.11 -m venv .venv
.\.venv\Scripts\python -m pip install torch==2.6.0 --index-url https://download.pytorch.org/whl/cu126
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python vendor/walkguide/setup_models.py
```

下载 [Vosk 中文小模型](https://alphacephei.com/vosk/models/vosk-model-small-cn-0.22.zip)，解压到 `models/vosk-model-small-cn-0.22/`。目录中应包含 `am`、`conf`、`graph` 和 `ivector`。WalkGuide 通过 Git 子模块固定版本，权重遵循上游许可。[模型说明](https://github.com/18941602006/walkguide-vision#模型和数据)

## 施工与验证

完整目标和进度在 [施工目标](docs/施工目标.md) 与 [施工记录](docs/施工记录.md)。本地测试使用 `python -m unittest discover -s tests -v`。

新电脑配置完成后先运行 `python scripts/check-env.py`，核对 CUDA、依赖、模型、消回声库和提示音是否齐全。此检查不输出密钥、不调用千问，也不修改板子；云端与硬件仍按部署指南单独验收。

安装模型后运行 `python scripts/check-vision.py`，可离线检查真实模型的室内/室外、横屏/竖屏推理、方向输出及断流清除。输入为程序生成的测试图，只验证软件链路，不代表实景识别准确率；不会上传画面或替换正在运行的眼镜视频。`--snapshot .local/qa-frame.json` 可保存供隔离浏览器测试使用的结果。

没有摄像头也可以运行 `python scripts/check-guidance.py`：用脚本化识别结果走真实提醒策略和音频队列，模拟设备播放回执，输出 `.local/guidance-demo/report.json` 和 `preview.wav`。试听开头明确说明是模拟场景，句间间隔经过压缩，真实逻辑时序见报告。此检查无需 GPU、模型或 API Key，不连接在线服务、不向眼镜播放。先用 `./scripts/make-prompts.ps1` 生成当前版本的 19 条提示语。

诊断 WAV 可用 `python scripts/check-wake.py .local/录音.wav` 在本机回放检测，输出触发时间，不调用云端；输入应是 16 kHz PCM16 单声道或麦克风/参考双声道。真人录音须事先告知，采用喇叭倒计时确认开始，诊断文件仅保留在 Git 忽略目录。网页电平表示声音能量，单有 dB 跳动不等于关键词已识别。

板子通过 ADB 配置 Wi-Fi 后，可经热点与电脑通信。默认出厂系统已包含 Python、arecord、aplay。开机无线脚本位于 `device/S41aiglass-wifi`，网络凭据存储于设备的 `/etc/wpa_supplicant.conf`。当前选用板载天线。[官方网络说明](https://wiki.luckfox.com/zh/Luckfox-Pico-Zero/WiFi-BT/)

摄像头到手后，断电安装并核对排线触点方向，按官方教程确认 `rtsp://眼镜IP/live/0` 出图。[摄像头教程](https://wiki.luckfox.com/zh/Luckfox-Pico-Zero/CSI-Camera/)

当前板子已有 Buildroot Linux 5.10.160、IMX415 驱动模块及 IQ/ISP 配置文件；本轮没有重新刷摄像头固件，也尚未验证驱动与实际传感器绑定。到手后仍需核对设备树、驱动加载、rkipc 和真实 RTSP 出图。网页不使用参考图的走廊、人像或伪造测距。

界面图标来自 [Tabler Icons](https://github.com/tabler/tabler-icons)，MIT 许可随图标保留；背景为生成的装饰图，不是摄像头素材。唤醒使用 [sherpa-onnx 中英文音素 KWS 模型](https://k2-fsa.github.io/sherpa/onnx/kws/pretrained_models/index.html)，模型下载留在忽略目录；SpeexDSP 来自 MSYS2 官方包，安装脚本校验 SHA-256。
