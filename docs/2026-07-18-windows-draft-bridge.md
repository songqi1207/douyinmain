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

桥接器提供两种模式：

- **旧工作流直接模式（优先）**：Coze 仍返回米核服务器上的 `draft_id`，桥接器直接读取
  `https://miheai.com/plugin/draft/{draft_id}` 的完整草稿 JSON，下载素材、改写本地路径并写入剪映。
- **米核同步器兜底模式**：如果直接接口发生变化，桥接器从
  `https://cdn.miheai.com/tool/miheai.zip` 下载并校验官方便携同步器，再通过 Windows UI
  Automation 自动填写 `draft_id` 和点击创建按钮；控件不可访问时退化为复制 ID 后人工点击。
- **本地草稿模式**：Coze 返回完整 `draft_key`，由桥接器直接生成本地剪映草稿，完全不经过
  米核草稿服务器。

第三方米核程序不会被二次打包进项目 EXE 或 GitHub 仓库。桥接器固定校验官方压缩包和程序的
SHA256，官方文件变化时会拒绝运行，必须先更新桥接器中的校验值。

## 直接使用

生成文件：

```text
dist\DouyinDraftBridge.exe
```

1. 双击运行 EXE。
2. 程序通常会自动识别剪映草稿目录和 `JianyingPro.exe`；识别不到时手动选择。
3. 现有米核工作流：把 Coze 返回的 `draft_id` 粘贴到顶部，优先点击“直接下载到剪映”。桥接器
   会同时把米核服务器原始 JSON 保存为草稿目录下的 `mihe_server_draft.json`，便于备份和排错。
4. 直接模式失败时点击“原同步器兜底”。首次使用会提示下载未签名的第三方程序；确认后尝试
   自动填写和点击，自动化失败时再手工按 `Ctrl+V`。
5. 本地草稿工作流：把 Coze 返回的 `draft_key` JSON 粘贴到下方，点击“导入本地剪映草稿”。
6. 导入成功后打开剪映，在剪映内预览并导出视频。

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

只下载并验证米核官方同步器（不启动）：

```powershell
python desktop_bridge_main.py --no-gui --install-mihe-sync
```

不启动桌面程序，直接按米核服务器 `draft_id` 导入：

```powershell
python desktop_bridge_main.py --no-gui `
  --mihe-draft-id <Coze返回的UUID> `
  --draft-root "$env:LOCALAPPDATA\JianyingPro\User Data\Projects\com.lveditor.draft"
```

## 当前验证结果

`temp/god_render_proof/god_template_render_key.json` 已通过完整导入链路：校验、素材预取、
草稿生成、落盘结构校验均成功。生成草稿包含 16 条轨道、87 个片段，并写出
`draft_content.json`、`draft_meta_info.json`、`draft_info.json` 和素材目录。

米核公开工具网页的当前脚本已验证会请求 `/plugin/draft/{draft_id}`，并在客户端完成素材下载、
路径替换和草稿文件写入。本项目已用等价测试草稿验证这套直接导入算法；仓库中没有可用的真实
米核服务器草稿 ID，因此仍需在实际 Coze 运行结果上完成一次真 ID 闸门验证。

当前开发机没有安装剪映，因此这里只验证到剪映可识别的本地草稿文件结构。
第一次在实际剪映电脑上使用时，应打开该草稿检查字体、花字、组合和特效资源是否齐全。

## 边界

### 单独导出米核服务器原始 JSON

如果目标是研究米核在服务器上“每个轨道、片段、素材和特效字段怎么写”，不需要先打开剪映：

```powershell
python scripts\export_mihe_draft_json.py <真实draft_id>
```

默认输出到：

```text
temp\mihe_draft_exports\<draft_id>\
```

其中 `mihe_server_draft.json` 是服务器原始响应，未改写素材路径；
`mihe_draft_structure.json` 把轨道、片段、素材分类和引用关系整理成带 JSON Path 的索引，
例如 `$.tracks[0].segments[2] -> $.materials.videos[5]`。这些文件可能包含带时效的素材 URL，
只用于自己的草稿分析，不要提交 GitHub 或对外分享。

- 这个版本负责“生成本地剪映草稿”，不模拟点击剪映的“导出”按钮。
- 米核兼容模式仍依赖米核/剪映草稿插件服务器；服务器下线或删除数据后，仅凭 `draft_id` 无法恢复。
- 米核官方 Windows 程序当前没有数字签名，因此本项目不直接分发它，只从官方 HTTPS 地址下载并做固定哈希校验。
- 剪映私有素材 ID、已下架特效或账号专属字体可能在另一台电脑上不可用。
- 本地素材路径必须在运行桥接器的电脑上存在；更适合让 Coze 返回可下载的 HTTP/HTTPS 素材地址。
- 剪映升级后如果草稿格式发生变化，需要同步调整本地生成器。
