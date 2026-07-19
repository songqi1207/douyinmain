# 四类业务前端与下载结果

## 已下载

下载目录：`downloads/reference_workflows/`（本地约 285 MB，已加入 `.gitignore`，避免把第三方附件误提交到代码仓库）。

| 类别 | 工作流数 | 附件数 | 备注 |
|---|---:|---:|---|
| 电商 | 16 | 44 | 含代码文本、剪映草稿、部分案例视频 |
| 养生 | 9 | 27 | 含 G90，按健康减肥内容保留 |
| 减肥 | 2 | 6 | 含 G159、G90；G90 与养生分类重复 |
| 起号 | 0 | 0 | 对方站点没有明确的“起号”标签或同名工作流 |

下载脚本：`scripts/download_reference_workflows.py`。它从环境变量读取账号，不把账号写入文件。

## 前端

- 页面：`/business`
- 页面形态：参考会员站的资源库卡片，而不是把所有输入框一次性铺在首页
- 分类：起号、电商、养生、减肥
- 卡片：预览视频、标题、标签、浏览/收藏/下载统计、点击查看
- 详情弹层：预览内容、工作流说明、主题/商品信息输入、提交任务
- 接口：`GET /api/business/categories`、`GET /api/business/workflows`、`POST /api/business/workflows/{code}/run`
- 预览：`GET /api/business/preview/{category}/{code}`，只返回本地附件中的视频/图片，不把飞书 token 暴露给浏览器

当前 `run` 接口已经完成统一任务入口和任务编号，但返回 `waiting_provider`。原因是下载的 TXT 是 Coze 剪贴板模板，不是本地可直接执行的 Python；真正运行还需要配置 Coze 工作流调用凭证、文件公网地址和异步结果回调。这样做可以先固定用户体验，后续只替换 provider，不把第三方密钥放到浏览器。
