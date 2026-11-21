# 小镜 · AIGlass

眼镜端使用 Luckfox Pico Zero RV1106G3、Buildroot Linux、IMX415-98 IR-CUT Camera、板载麦克风和外接喇叭。摄像头接 CSI，电脑通过局域网接收视频与音频。网页只显示运行状态。后台处理独立于浏览器。

## 启动电脑后端

```powershell
.\start.ps1 -Glasses 192.168.137.54
```

将地址替换为眼镜的 Wi-Fi 地址，打开 <http://127.0.0.1:7860> 查看画面、分割结果和事件。板子尚无摄像头时，视频离线是实际状态。开发测试可在命令行运行 `python app.py --test-video 文件路径`，页面会显示“后端测试录像”。

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
