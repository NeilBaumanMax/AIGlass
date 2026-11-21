# Edith · AIGlass

眼镜端使用 Luckfox Pico Zero RV1106G3、Buildroot Linux、IMX415-98 IR-CUT Camera、板载麦克风和外接喇叭。摄像头接 CSI，电脑通过局域网接收视频与音频。网页显示设备状态、视频、分割和对话，允许清空对话展示记录。后台处理独立于浏览器。IMX415 目前尚未到手，真实摄像头链路待验收。

## 启动电脑后端

```powershell
.\start.ps1 -Glasses 192.168.137.54
```

将地址替换为眼镜的 Wi-Fi 地址，打开 <http://127.0.0.1:7860> 查看画面、分割结果和事件。板子尚无摄像头时，视频离线是实际状态。开发测试可在命令行运行 `python app.py --test-video 文件路径`，页面会显示“后端测试录像”。

运行 `./start.ps1` 后，设备握手会自动配置其 Wi-Fi 地址作为 RTSP 来源，也可用 `-Glasses` 固定地址。唤醒词是“嗨，Edith”（伊迪丝），电脑本地 sherpa-onnx 音素关键词模型负责唤醒，Vosk 负责唤醒后的指令识别。板子上传 16 kHz 双声道：左声道麦克风、右声道 DAC 播放参考。唤醒后可说“切换室内模式”“切换室外模式”“看看当前画面”或直接提问；说“结束对话”退出。支持连续对话，语音播放完成后 8 秒无新指令会播报“对话结束”。普通对话使用千问，只有明确要求看画面才附带新鲜图像。未唤醒时音频不发送千问。

电脑使用 SpeexDSP 消除喇叭回声，播放期间继续检测语音，支持插话停止当前回答并使迟到的云端回复失效。回声处理无法加载时退回轮流说话，网页明确显示异常。真人同时讲话的稳定性仍待完整验收。WalkGuide 提醒优先，连续多帧确认后播报，持续相同状态不重复播报。目前只提示障碍、疑似台阶和路面不清，不提供米制距离。网页区域占比来自实际分割掩码，推理耗时不等于端到端延迟。

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

针对 Windows 热点存在“已关联但 ARP 解析失败”的情况，部署脚本会核对本机服务网卡的 MAC；仅当板子关联的热点 BSSID 与它一致时，固定该服务地址的邻居记录。热点变化时移除本程序的旧记录。连续 3 次网络失败且确认为关联/ARP 故障时，自动请求重新关联，间隔至少 30 秒；HTTP 会话错误、认证错误或后端停止但邻居正常时不会重置 Wi-Fi。

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
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python vendor/walkguide/setup_models.py
```

下载 [Vosk 中文小模型](https://alphacephei.com/vosk/models/vosk-model-small-cn-0.22.zip)，解压到 `models/vosk-model-small-cn-0.22/`。目录中应包含 `am`、`conf`、`graph` 和 `ivector`。WalkGuide 通过 Git 子模块固定版本，权重遵循上游许可。[模型说明](https://github.com/18941602006/walkguide-vision#模型和数据)

## 施工与验证

完整目标和进度在 [施工目标](docs/施工目标.md) 与 [施工记录](docs/施工记录.md)。本地测试使用 `python -m unittest discover -s tests -v`。

板子通过 ADB 配置 Wi-Fi 后，可经热点与电脑通信。默认出厂系统已包含 Python、arecord、aplay。开机无线脚本位于 `device/S41aiglass-wifi`，网络凭据存储于设备的 `/etc/wpa_supplicant.conf`。当前选用板载天线。[官方网络说明](https://wiki.luckfox.com/zh/Luckfox-Pico-Zero/WiFi-BT/)

摄像头到手后，断电安装并核对排线触点方向，按官方教程确认 `rtsp://眼镜IP/live/0` 出图。[摄像头教程](https://wiki.luckfox.com/zh/Luckfox-Pico-Zero/CSI-Camera/)

当前板子已有 Buildroot Linux 5.10.160、IMX415 驱动模块及 IQ/ISP 配置文件；本轮没有重新刷摄像头固件，也尚未验证驱动与实际传感器绑定。到手后仍需核对设备树、驱动加载、rkipc 和真实 RTSP 出图。网页不使用参考图的走廊、人像或伪造测距。

界面图标来自 [Tabler Icons](https://github.com/tabler/tabler-icons)，MIT 许可随图标保留；背景为生成的装饰图，不是摄像头素材。唤醒使用 [sherpa-onnx 中英文音素 KWS 模型](https://k2-fsa.github.io/sherpa/onnx/kws/pretrained_models/index.html)，模型下载留在忽略目录；SpeexDSP 来自 MSYS2 官方包，安装脚本校验 SHA-256。
