# draft_key → 火山引擎 VOD 云剪辑

## 配置

真实密钥只放在 `.env`，不要提交到 Git：

```dotenv
VOLCENGINE_ACCESS_KEY=
VOLCENGINE_SECRET_KEY=
VOD_SPACE_NAME=douyin-render-dev
VOD_REGION=cn-north-1
```

## 命令行

只转换并检查参数（仍会上传未缓存的素材）：

```powershell
python scripts/render_draft_key_vod.py --key path/to/draft_key.json --output-json temp/vod-dry-run.json
```

提交任务并等待结果：

```powershell
python scripts/render_draft_key_vod.py --key path/to/draft_key.json --submit --wait --output-json temp/vod-result.json
```

## HTTP API

提交：

```http
POST /api/v1/vod/renders
Content-Type: application/json

{
  "key": { "kind": "jianying_draft_key", "calls": [] },
  "include_text": true,
  "include_effects": true
}
```

响应中的 `req_id` 用于查询：

```http
GET /api/v1/vod/renders/{req_id}
```

成功时返回 `status=success`、`progress=100`、`output_vid` 和媒资元数据。

## 兼容边界

- 素材上传后会缓存 `Mid` 与完整 `tos://bucket/path`，重复渲染不重复上传相同文件。
- 剪映专属效果不会伪装成同名火山效果；转换结果的 `effect_replacements` 会列出替换关系。
- 当前转换器将不受 VOD 公共参数支持的剪映关键帧折叠成片段最终静态姿态。
- 获取 `OutputVid` 不依赖播放域名；通过 `GetPlayInfo` 获取公网播放链接前，空间必须配置可用的点播播放域名。
