# Windows 剪映草稿桥接器

## 它替代什么

原链路：

```text
前端 JSON → Coze → 米核草稿 ID → 米核 Windows EXE → 本地剪映草稿
```

替代链路：

```text
前端 JSON → God 本地草稿版 Coze 工作流 → draft_key JSON
          → DouyinDraftBridge.exe → 本地剪映草稿 → 剪映打开与导出
```

桥接器不再依赖米核草稿 ID 或米核桌面程序。Coze 的结束节点必须返回完整的
`draft_key`，而不是只返回 `draft_id`。

## 直接使用

生成文件：

```text
dist\DouyinDraftBridge.exe
```

1. 双击运行 EXE。
2. 程序通常会自动识别剪映草稿目录和 `JianyingPro.exe`；识别不到时手动选择。
3. 将 Coze 结束节点返回的 `draft_key` JSON 粘贴进去，或选择保存下来的 JSON 文件。
4. 点击“导入本地剪映草稿”。
5. 导入成功后点击“打开剪映”，在剪映内预览并导出视频。

剪映 Windows 常见草稿目录：

```text
%LOCALAPPDATA%\JianyingPro\User Data\Projects\com.lveditor.draft
```

程序接受以下输入形式：

- 直接的 `draft_key` 对象；
- `{"draft_key": {...}}`；
- Coze 常见的 `output`、`result`、`data`、`body` 嵌套返回值；
- 被 JSON 字符串再次包裹的上述内容。

## 开发与打包

用源码导入神模板验证文件：

```powershell
python desktop_bridge_main.py --no-gui `
  --key temp\god_render_proof\god_template_render_key.json `
  --draft-root temp\jianying_drafts
```

重新生成 EXE：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File scripts\build_windows_draft_bridge.ps1
```

## 当前验证结果

`temp/god_render_proof/god_template_render_key.json` 已通过完整导入链路：校验、素材预取、
草稿生成、落盘结构校验均成功。生成草稿包含 16 条轨道、87 个片段，并写出
`draft_content.json`、`draft_meta_info.json`、`draft_info.json` 和素材目录。

当前开发机没有安装剪映，因此这里只验证到剪映可识别的本地草稿文件结构和 EXE 启动。
第一次在实际剪映电脑上使用时，应打开该草稿检查字体、花字、组合和特效资源是否齐全。

## 边界

- 这个版本负责“生成本地剪映草稿”，不模拟点击剪映的“导出”按钮。
- 剪映私有素材 ID、已下架特效或账号专属字体可能在另一台电脑上不可用。
- 本地素材路径必须在运行桥接器的电脑上存在；更适合让 Coze 返回可下载的 HTTP/HTTPS 素材地址。
- 剪映升级后如果草稿格式发生变化，需要同步调整本地生成器。
