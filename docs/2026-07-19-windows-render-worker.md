# 无人值守 Windows 剪映渲染机

## 结论

渲染机由两个部分组成：

1. 隐藏运行的 HTTP Worker，负责接收 `draft_key`、生成剪映草稿、鉴权、单任务排队和返回视频地址；
2. 已登录 Windows 桌面中的剪映，负责打开该草稿并原生导出最终 MP4。

主链路不使用 FFmpeg，也不要求用户浏览器连接本机桥接器。旧的米核 `draft_id`
输入仍然兼容，但新链路直接发送 `draft_key`。

不要把剪映自动化注册成 LocalSystem Windows 服务。Windows 服务位于非交互 Session 0，
不能可靠操作用户桌面。仓库安装脚本注册的是“用户登录时、使用 Interactive Token”运行的
计划任务。

## 目标机器准备

- 建议使用独立的 Windows 11 用户，例如 `render`，不要使用日常办公账号；
- 显示分辨率固定为 `1920x1080`，缩放固定为 `100%`；
- 安装剪映专业版，登录账号并确认模板所需会员特效具有导出权限；
- 打开剪映全局设置，确认草稿目录；
- 禁止机器自动睡眠，但不要永久关闭 Windows 安全更新；更新前先暂停任务并做一次回归测试；
- 一台机器同一时刻只渲染一个视频。

如果要求断电重启后自动恢复，可使用 Microsoft Sysinternals Autologon 配置专用账号自动登录。
它会把密码保存为 LSA Secret，但本机管理员仍可取回密码，因此渲染机必须是隔离的专用机器。

## 安装 Worker

在渲染机 PowerShell 中：

```powershell
git clone https://github.com/songqi1207/douyinmain.git C:\code\douyinmain
cd C:\code\douyinmain
powershell -ExecutionPolicy Bypass -File scripts\install_windows_render_worker.ps1
notepad .env.render-worker
```

至少填写：

```dotenv
WINDOWS_RENDER_API_TOKEN=一段足够长的随机字符串
WINDOWS_RENDER_PUBLIC_BASE_URL=http://渲染机局域网IP:8765
WINDOWS_RENDER_DRAFT_ROOT=剪映实际草稿目录
WINDOWS_RENDER_JIANYING_EXE=JianyingPro.exe实际路径
WINDOWS_RENDER_OUTPUT_DIR=C:\DouyinRenderWorker\output
WINDOWS_RENDER_EXPORT_DRIVER=uiautomation
```

不要把 `.env.render-worker` 上传 GitHub。

手动启动验证：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_windows_render_worker.ps1
```

健康检查：

```powershell
$headers = @{ Authorization = "Bearer 你的WINDOWS_RENDER_API_TOKEN" }
Invoke-RestMethod http://127.0.0.1:8765/health -Headers $headers
```

## 校准当前剪映版本

打开剪映并停留在草稿列表页，然后执行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\inspect_jianying_ui.ps1
```

脚本会在以下目录生成控件树 JSON 和窗口截图：

```text
%LOCALAPPDATA%\DouyinRenderWorker\diagnostics
```

仓库内置的 `scripts/run_jianying_export_automation.ps1` 会按控件名称寻找草稿卡片、
作品名称、保存位置和导出按钮。剪映升级后如果控件名称变化，用上述诊断文件调整脚本。
剪映 6.x 可尝试安装脚本的 `-InstallLegacyExporter` 参数和
`pyjianyingdraft` 驱动；当前 10.x 默认使用 `uiautomation`。

## 接入主站

主站 `.env`：

```dotenv
WORKFLOW_RENDER_API_URL=http://渲染机局域网IP:8765/render
WORKFLOW_RENDER_API_TOKEN=与渲染机相同的Token
WORKFLOW_RENDER_TIMEOUT_SECONDS=2400
```

主站 `workflow_jobs._render_drafts` 会直接发送：

```json
{
  "job_id": "业务任务ID",
  "workflow_code": "OWN03",
  "draft_key": {
    "kind": "jianying_draft_key",
    "draft": {},
    "calls": []
  }
}
```

Worker 生成草稿、启动剪映并完成原生导出后返回带签名的 `video_url`。主站无需暴露
草稿 JSON、剪映或 Windows 文件路径。

## 运行限制

- 渲染账号必须保持已登录且桌面未锁定；
- 不要在导出时操作鼠标键盘；
- RDP 断开、锁屏、剪映升级、弹窗、会员权限和素材下载失败都可能中断自动化；
- 生产环境应增加失败截图、进程重启、任务重试和通知；
- 外网访问时不要直接暴露 8765 端口，应放在 VPN、反向代理或受限防火墙之后。
