# 小镜 · AIGlass

眼镜端使用 Luckfox Pico Zero RV1106G3、Buildroot Linux、IMX415-98 IR-CUT Camera、板载麦克风和外接喇叭。摄像头接 CSI，电脑通过局域网接收视频与音频。网页只显示运行状态。后台处理独立于浏览器。

## 启动电脑后端

```powershell
.\start.ps1 -Glasses 192.168.137.54
```

将地址替换为眼镜的 Wi-Fi 地址，打开 <http://127.0.0.1:7860> 查看画面、分割结果和事件。板子尚无摄像头时，视频离线是实际状态。开发测试可在命令行运行 `python app.py --test-video 文件路径`，页面会显示“后端测试录像”。

尚未安装摄像头时运行 `./start.ps1` 即可测试音频。唤醒词在电脑本地用 Vosk 识别，板子持续上传 16 kHz 单声道音频。唤醒后，说“切换室内模式”“切换室外模式”“看看当前画面”或直接提问；说“结束对话”退出，20 秒无交互也会退出。普通对话使用千问，只有明确要求看画面的指令才附带新鲜图像。

喇叭播放时暂停识别并保留 0.6 秒余音缓冲，这是当前 Demo 的半双工方案。请听完提示再说话。WalkGuide 提醒会中断普通回复；连续多帧确认后播报，持续相同状态不重复播报。目前规则只提示障碍、疑似台阶和路面不清，不提供米制距离。

## 配置语音和部署板端

在项目根目录 `.env` 中设置 `DASHSCOPE_API_KEY`，格式参考 `.env.example`。使用百炼北京地域的 `qwen3-omni-flash`，密钥只由电脑持有。`.env`、设备令牌和诊断录音均已排除于 Git。

```powershell
# 首次生成离线提示语，需 Windows 中文 Huihui 语音
./scripts/make-prompts.ps1
# 启动电脑后端后，通过 ADB 部署常驻音频客户端
./scripts/deploy-device.ps1 -Server http://192.168.137.1:7860
```

客户端使用设备原有 Python 3.11、arecord 和 aplay。`S98aiglass` 开机启动，断网后自动重新握手；诊断日志为 `/tmp/aiglass-client.log`，轮转上限约 256 KB。默认 ADC 为 SingadcL，只采左声道。USB 用于部署和供电，音频实际走 Wi-Fi。

Windows 首次需要允许热点网段访问 TCP 7860。在管理员 PowerShell 运行：

```powershell
New-NetFirewallRule -DisplayName 'AIGlass Pico demo' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 7860 -RemoteAddress 192.168.137.0/24 -Profile Any
```

网页没有录音、输入或控制入口；关闭网页不影响处理。当前单设备局域网 Demo 使用设备令牌认证上传和播放请求。

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
