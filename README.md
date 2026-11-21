# 小镜 · AIGlass

眼镜端使用 Luckfox Pico Zero RV1106G3、IMX415-98 IR-CUT Camera、板载麦克风和外接喇叭。摄像头通过 22 针 CSI 排线连接。个人电脑通过局域网拉取眼镜的视频。当前联调版的麦克风和声音播放使用电脑浏览器，眼镜端音频尚待接入。

## 在当前电脑启动

在项目目录运行以下命令，然后打开 <http://127.0.0.1:7860>。启动脚本优先使用已配置的本地 Python 运行环境。

```powershell
.\start.ps1
```

选「本地视频」并选择文件，或选「电脑摄像头」，点击「开始分析」。室内和室外采用不同的 WalkGuide 视频模型。页面并列显示本次取帧的原图和分割结果，显示推理耗时并记录持续多帧的中央障碍、室内疑似台阶或路面不清。暂停、页面关闭或浏览器休眠会中断这套电脑端预览和提醒。提示阈值为原型参数，尚未做佩戴实测。

打开「电脑麦克风」后说“你好，小镜”，待页面显示“已唤醒”，再说“切换室外模式”或“看看当前画面”。唤醒和指令转写使用本机 Vosk。对话在 20 秒空闲后结束，也支持说“结束对话”。键盘输入可直接测试相同的指令。系统播报使用浏览器可用的本地中文语音，视觉提醒可以打断正在播放的千问回答。

## 配置百炼北京地域

在启动服务的 PowerShell 里设置 `DASHSCOPE_API_KEY`，或使用 Windows 的用户环境变量并重启服务。密钥仅从服务进程环境读取。百炼文本和语音回复默认使用 `qwen3-omni-flash`，可以用 `QWEN_MODEL` 指定兼容的 Omni 模型。若账号需要使用业务空间专属地址，将北京空间的 OpenAI 兼容地址（以 `/compatible-mode/v1` 结尾）设为 `DASHSCOPE_BASE_URL`。

普通问答只发送转写后的文字和本次对话历史。明确发出看图指令或按「看当前画面」时才附上当前 JPEG。持续的视频分析使用本机 RTX 显卡（没有 CUDA 时回退到 CPU）。[千问 Omni 文档](https://help.aliyun.com/zh/model-studio/qwen-omni)

## 首次接入眼镜视频

1. 断电后安装 IMX415，并按 Zero 的接线图核对排线触点方向。通过 Type-C 把 **Zero 型号**的 Buildroot 镜像烧入 eMMC，按官方摄像头教程重启。SD 卡可用于扩展存储。[烧录步骤](https://wiki.luckfox.com/zh/Luckfox-Pico-RV1106/Getting-Started/eMMC-Models/) · [摄像头接线和拉流](https://wiki.luckfox.com/zh/Luckfox-Pico-Zero/CSI-Camera/)
2. 在板子的 Linux 终端编辑 `/etc/wpa_supplicant.conf`，填入自己的 2.4 GHz 网络。在官方教程中选择实际使用的板载或外接天线配置。启动无线连接后用 `udhcpc -i wlan0` 获取租约，用 `ip -4 addr show wlan0` 查看地址。电脑与眼镜在同一局域网即可，电脑也可用网线接路由器。先在电脑 VLC 中打开 `rtsp://眼镜IP/live/0` 确认彩色画面。[Zero 无线联网与开机启动](https://wiki.luckfox.com/zh/Luckfox-Pico-Zero/WiFi-BT/)
3. 用下面的命令重启后端，将示例地址换成眼镜的地址。网页选择「眼镜摄像头」并开始分析。连接状态来自实际解码的视频帧，接收端断开后会重连。

```powershell
.\start.ps1 -Glasses 192.168.1.50
```

## 在新电脑准备依赖

```powershell
git submodule update --init --recursive
py -3.11 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python vendor/walkguide/setup_models.py
```

如需 GPU，先为当前 NVIDIA 驱动安装 CUDA 版 PyTorch，再安装其余依赖。下载并解压 [Vosk 中文小模型](https://alphacephei.com/vosk/models/vosk-model-small-cn-0.22.zip) 到 `models/vosk-model-small-cn-0.22/`，目录下应直接包含 `am`、`conf`、`graph` 和 `ivector`。无麦克风时可用网页键盘测试。

WalkGuide 通过 Git 子模块固定版本，权重遵循上游许可。[WalkGuide 模型及许可说明](https://github.com/18941602006/walkguide-vision#模型和数据)
