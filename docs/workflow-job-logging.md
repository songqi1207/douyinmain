# 工作流任务日志排查

工作流后台日志统一使用 `workflow.jobs` 名称，并通过 `job_id` 串联任务全程。
日志只包含任务编号、工作流编号、阶段、HTTP 状态和耗时，不记录用户输入、
Coze Token、米核 Key 或 `draft_key` 内容。

## Docker Compose

生产配置使用 Redis 队列时，任务执行日志在 `worker` 容器：

```powershell
docker compose logs -f --tail=200 worker
```

只查看某个任务：

```powershell
docker compose logs --since=30m worker | Select-String "你的 job_id"
```

查看 Web 入队和接口日志：

```powershell
docker compose logs -f --tail=100 web
```

查看 RQ 队列和 worker 是否存活：

```powershell
docker compose exec worker rq info --url redis://redis:6379/0
```

## 本地运行

`WORKFLOW_QUEUE_MODE=inline` 时，日志直接显示在启动 Uvicorn 的终端中：

```powershell
python -m uvicorn fastapi_app:app --host 127.0.0.1 --port 8000
```

可通过环境变量调整级别，默认是 `INFO`：

```env
WORKFLOW_LOG_LEVEL=INFO
```

## 常见日志事件

- `job_enqueue`：任务已进入后台队列。
- `job_started`：worker 已开始执行。
- `job_path ... path=coze_published`：选择已发布的 Coze 工作流。
- `coze_request_started`：开始调用 Coze，并显示 `direct` 或 `system_proxy`。
- `coze_request_finished`：Coze 已响应，同时显示 HTTP 状态与耗时。
- `draft_key_saved`：已取得并校验 `draft_key`。
- `job_render_route`：进入设备或服务器剪映渲染。
- `device_render_claimed`：本机剪映助手已领取任务。
- `device_render_failed`：本机剪映导出失败，并显示助手回传的具体错误。
- `job_completed` / `job_failed`：任务最终结果。

如果只看到 `job_enqueue` 而没有 `job_started`，检查 Redis/RQ worker。
如果停在 `coze_request_started`，检查 Coze 网络和工作流运行时间。
如果已有 `draft_key_saved`，则问题位于剪映设备或服务器渲染阶段。

本机剪映助手会另外记录领取、草稿导入、剪映导出和结果上传阶段。可在主界面
底部点击“打开运行日志”（设备区也有“查看日志”入口），或直接打开：

```text
%APPDATA%\AIVideoCreator\logs\render-agent.log
```

日志按 2 MB 轮换并保留 3 份，不记录设备令牌或 `draft_key` 内容。
