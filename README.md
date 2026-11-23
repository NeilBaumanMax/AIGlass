# Edith · AI 眼镜

Luckfox Pico Zero Linux 眼镜 + 电脑 WalkGuide 视觉 + nanoMuse/千问 AI。眼镜通过局域网传输摄像头与双向音频；电脑负责视觉、唤醒、识别、AI 与播报。网页显示真实设备状态、原图/分割、语音提醒和对话，支持清空展示记录。

**从 GitHub 克隆后部署，请完整执行 [Windows 11 后端部署指南](docs/deployment/Windows11完整部署.md)。** 适用 Windows 11 x64 + NVIDIA CUDA 显卡，包含 RTX 4090；安装使用 Python 3.11。当前没有提供完整 Linux/macOS/WSL 部署方案。

## 新电脑开始

先安装 Git、Python 3.11 x64、匹配的 NVIDIA 驱动、Windows 中文 Huihui 语音，然后在 PowerShell 执行：

```powershell
git clone --recurse-submodules https://github.com/NeilBaumanMax/AIGlass.git
Set-Location AIGlass
Set-ExecutionPolicy -Scope Process RemoteSigned
.\scripts\setup-backend.ps1
```

安装脚本创建 `.venv`、安装固定 Python 依赖、下载视觉/语音模型、安装回声处理库并生成本地提示音。首次生成 `.env`，已有配置不会覆盖。网络失败可按 `-Stage Environment` 或 `-Stage Assets` 重试；`-Plan` 只显示计划。

接着按完整指南完成以下步骤，不能仅凭网页打开就算部署完成：

1. 在 `.env` 填入自己的百炼北京 API Key。
2. 安装并配置 [nanoMuse 桌面接入](docs/deployment/nanoMuse接入.md)，登录、选择千问并启用本机接口，再设置 `AI_BACKEND=nanomuse`。只需要基础对话时可以保留 `qwen`，该模式没有电脑/手机执行工具。
3. 运行 `.\.venv\Scripts\python.exe scripts/check-env.py`，执行指南中的软件检查。
4. 运行 `.\start.ps1`，打开 [控制台](http://127.0.0.1:7860)。部署板端时按目标网络设置防火墙、服务器地址及设备令牌。

安装和运行均不依赖开发机的目录、IP、密钥或账号。不要从其他电脑复制 `.venv` / `.runtime`；在新电脑重建环境。[Python 虚拟环境说明](https://docs.python.org/3.11/library/venv.html)

## 使用与当前进度

- 唤醒词：“嗨，Edith”。唤醒后可以连续对话，播报结束后 8 秒无新指令退出。
- 说“切换室内/室外模式”切换视觉；“看看当前画面”请求 AI 看眼前；“看看电脑屏幕”调用 nanoMuse 取屏。
- WalkGuide 持续运行，视觉提醒无需唤醒；新危险优先，普通方向避让对话，过期结果撤回。[提醒逻辑](docs/architecture/视觉语音提醒.md)
- 已实测眼镜唤醒、nanoMuse 电脑取屏/打开记事本/输入，以及眼镜朗读。手机已验证只读联系人核对、眼镜指令委派和断线失败结果播报；实际微信发送未通过，人名转写漏字待修。IMX415-98 IR-CUT 尚未到手，真实 CSI/RTSP/实景提醒、完整插话稳定性和另一台 4090 部署仍待验收。
- 新代码是否已经加载、模拟与实测的区别，见 [当前状态](docs/development/当前状态.md)。没有摄像头时网页保持等待，不使用示例照片充当实拍。

## 目录与开发

```text
backend/       电脑后端 Python 包
device/        Pico Linux 客户端与服务脚本
static/        网页样式、脚本、图标和背景
templates/     网页模板
integrations/  nanoMuse 桌面桥接
scripts/       安装、启动、部署与检查工具
tests/         自动测试
vendor/        固定版本 WalkGuide 子模块
docs/          部署、施工、架构与验收文档
app.py         兼容启动入口；标准入口为 python -m backend
start.ps1      选择项目 Python 环境并启动后端
```

模型、环境、密钥和诊断数据不会提交：`models/`、`.venv/`、`.tools/`、`.local/`、`.env`。目录职责见 [开发约定](docs/development/开发约定.md)，后续任务见 [下一步开发](docs/development/下一步开发.md)，全部文档见 [文档索引](docs/README.md)。

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe scripts/check-docs.py
.\.venv\Scripts\python.exe scripts/check-vision.py
.\.venv\Scripts\python.exe scripts/check-guidance.py
```

视觉检查使用生成图；提醒检查使用脚本化识别和模拟播放回执，输出 `.local/guidance-demo/report.json` 与明确标注模拟的 `preview.wav`，均不替换在线设备的真实画面。

## 上游与许可

视觉固定 [WalkGuide `1bd27dd`](https://github.com/18941602006/walkguide-vision/commit/1bd27dd1a90d5b169074588a3487611f40af4716)，直接使用其 SegFormer-B2 与方向规划；nanoMuse 接入固定 [1.0.9 源码](https://github.com/nano-muse/nanoMuse/tree/09850259cab00d27af83786f00faa09b5d8494bf)，桥接许可见 [集成说明](integrations/nanomuse/README.md)。模型及第三方组件遵循各自许可。

图标为 Tabler Icons，MIT 许可随 `static/icons/LICENSE` 保留；装饰背景不是摄像头素材。关键词模型来自 sherpa-onnx，ASR 使用 Vosk，回声处理使用 SpeexDSP；下载来源与版本见部署指南。
