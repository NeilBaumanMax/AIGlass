# nanoMuse 桌面端 Edith 接入层

上游：<https://github.com/nano-muse/nanoMuse>，固定提交 `09850259cab00d27af83786f00faa09b5d8494bf`（1.0.9）。

此目录的 TypeScript 接入层与 `scripts/prepare-nanomuse.py` 生成的上游修改按 GPL-3.0-or-later 提供，随附上游 LICENSE。原作者及贡献者的版权、品牌和其他许可证保留在原项目中。没有将上游完整源码复制进 AIGlass。

接入层编入真正的 `harness/dsh-nanomuse` 桌面插件，复用 `TaskRunner`、`PersistentTaskEndpoint` 和 `PersistentTurns`，因此 AI 工具、会话、模型设置和手机委派属于 nanoMuse。它不启动独立的 Python nanoMuse Agent。

仅当设置 `EDITH_BRIDGE_TOKEN_FILE` 时监听 `127.0.0.1:18765`。每个请求必须使用独立 bearer token；拒绝浏览器 Origin，无 CORS。不要向局域网开放此端口。

接口：`GET /v1/status`，`POST /v1/task`，`GET /v1/task?conversation=UUID&turn_id=UUID`，`POST /v1/stop`，`POST /v1/approve`。任务、取消、确认都关联同一个 conversation/turn UUID；只返回自己的待确认请求，确认使用 `approval_id` 与布尔值 `allow`。同一个 turn 重复提交返回原状态，不再次执行。眼镜客户端每 0.2 秒查询任务，超过 30 秒没有查询或账号切换时请求停止。进程重启后未完成任务标记 interrupted。

完整部署和验证见 [nanoMuse 接入指南](../../docs/nanoMuse接入.md)。
