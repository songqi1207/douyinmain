# 本地 Coze 工具清单

## 说明

- OpenAPI 总入口: `http://127.0.0.1:5001/api/openapi/coze_workflow_tools.json`
- 测试入口: `http://127.0.0.1:5001/api/openapi/test.json`
- 单个工具统一入口: `http://127.0.0.1:5001/api/tools/<tool_name>`
- `speech_synthesis` 和 `jimeng_generate_image` 已经有本地路由，但当前是 placeholder 版本。
- 下表中的模板节点名直接来自模板 JSON。若某个节点标题在源模板里本身已损坏，这里会明确标注。

## 工具 URL

| 工具 | URL | 备注 |
|---|---|---|
| `get_audio_duration` | `http://127.0.0.1:5001/api/tools/get_audio_duration` | 本地实现可用 |
| `text_splitter` | `http://127.0.0.1:5001/api/tools/text_splitter` | 本地实现可用 |
| `timeline_merge` | `http://127.0.0.1:5001/api/tools/timeline_merge` | 本地实现可用 |
| `effect_infos` | `http://127.0.0.1:5001/api/tools/effect_infos` | 本地实现可用 |
| `create_draft` | `http://127.0.0.1:5001/api/tools/create_draft` | 本地实现可用 |
| `get_draft` | `http://127.0.0.1:5001/api/tools/get_draft` | 查询本地草稿信息，返回 Windows 可访问路径；兼容 `draft_id` / `draft_url` |
| `add_audios` | `http://127.0.0.1:5001/api/tools/add_audios` | 本地实现可用 |
| `add_images` | `http://127.0.0.1:5001/api/tools/add_images` | 本地实现可用 |
| `add_captions` | `http://127.0.0.1:5001/api/tools/add_captions` | 本地实现可用 |
| `add_keyframes` | `http://127.0.0.1:5001/api/tools/add_keyframes` | 本地实现可用 |
| `add_effects` | `http://127.0.0.1:5001/api/tools/add_effects` | 本地实现可用 |
| `align_text_to_audio` | `http://127.0.0.1:5001/api/tools/align_text_to_audio` | 本地实现可用 |
| `audio_infos` | `http://127.0.0.1:5001/api/tools/audio_infos` | 本地实现可用 |
| `audio_link_collector` | `http://127.0.0.1:5001/api/tools/audio_link_collector` | 本地实现可用 |
| `audio_timelines` | `http://127.0.0.1:5001/api/tools/audio_timelines` | 本地实现可用 |
| `caption_infos` | `http://127.0.0.1:5001/api/tools/caption_infos` | 本地实现可用 |
| `imgs_infos` | `http://127.0.0.1:5001/api/tools/imgs_infos` | 本地实现可用 |
| `keyframes_infos` | `http://127.0.0.1:5001/api/tools/keyframes_infos` | 本地实现可用 |
| `rolling_effect` | `http://127.0.0.1:5001/api/tools/rolling_effect` | 本地实现可用 |
| `wenan_timeline_range` | `http://127.0.0.1:5001/api/tools/wenan_timeline_range` | 本地实现可用 |
| `speech_synthesis` | `http://127.0.0.1:5001/api/tools/speech_synthesis` | 当前为本地 placeholder 配音，不是官方 Coze 语音合成 |
| `jimeng_generate_image` | `http://127.0.0.1:5001/api/tools/jimeng_generate_image` | 当前为本地 placeholder 生图，不是米核/即梦真实生图 |
| `create_draft_from_key` | `http://127.0.0.1:5001/api/tools/create_draft_from_key` | **key 数据包一次性生成整个草稿**（POST，替代逐节点调用 create_draft/add_*）。schema 见 `docs/draft_key_schema.md`，CLI 版 `python scripts/import_draft_key.py key.json` |

## 本地草稿 key 链路（摆脱剪映小助手/米核小助手）

- Coze 侧：`python -m workflows.god.local_key` 从 v7 母版生成 `神工作流模板_本地草稿-v1.json`——19 个剪映小助手插件节点被替换为「汇总草稿key」代码节点（300201），201390 运镜关键帧改为输出 `segment_ref` 形式，End 节点输出 key JSON 字符串。
- 本地侧：复制工作流运行结果里的 key → 存成文件 → `python scripts/import_draft_key.py key.json`，草稿直接写进本机剪映草稿目录（`JIANYING_DRAFT_ROOT` 可覆盖）。
- 素材（配音/生图）仍由 Coze 官方语音合成与米核生图产出，key 里只带 URL，导入器统一预取缓存。
- 剪映资源元数据（特效/字体/出入场动画 名字→resource_id）：`utils/data/jianying_meta.json`（源自 pyJianYingDraft 0.3.0）。

## draft_id / draft_url 兼容说明

- `create_draft` 现在同时返回 `draft_id` 和 `draft_url`。
- `add_audios`、`add_images`、`add_captions`、`add_keyframes`、`add_effects` 现在支持传 `draft_id`，也支持直接传 `draft_url`。
- `get_draft` 可用于把 `draft_id` 或 `draft_url` 解析成真实本地草稿路径，适合前端直接展示给 Windows 打开。

## 工具中文名对照（按模板实际使用）

中文名取自 OpenAPI（`/api/openapi/coze_workflow_tools.json`）里各工具的 `summary`，Coze 导入后作为工具描述显示；工具名本身取 `operationId`（英文），与模板插件节点的 `apiName` 直接对应。

以模板里真实的插件节点（`apiName`）为准统计：三个模板用到的工具并集正好是插件现有的全部 21 个工具，没有多余也没有缺失。

### 三个模板都用（7 个）

| 工具 (apiName) | 中文名 |
|---|---|
| `create_draft` | 创建本地剪映草稿 |
| `speech_synthesis` | 本地语音合成 |
| `jimeng_generate_image` | 本地占位生图 |
| `add_audios` | 向本地草稿追加音频片段 |
| `add_captions` | 向本地草稿追加字幕片段 |
| `add_images` | 向本地草稿追加图片片段 |
| `add_keyframes` | 向草稿片段追加关键帧 |

### 只有神话 v7 / 香烟 v1 用（4 个，两模板用的工具完全相同，各共 11 个）

| 工具 (apiName) | 中文名 |
|---|---|
| `align_text_to_audio` | 按音频时长对齐文本分句 |
| `get_audio_duration` | 获取音频时长 |
| `effect_infos` | 生成特效时间信息 |
| `add_effects` | 向本地草稿追加特效片段 |

### 只有书单 v1 用（10 个，书单共用 17 个）

| 工具 (apiName) | 中文名 |
|---|---|
| `text_splitter` | 中文智能分句 |
| `audio_link_collector` | 从批量输出中提取音频链接 |
| `audio_timelines` | 根据音频链接生成顺序时间线 |
| `timeline_merge` | 合并开场与正文时间线 |
| `wenan_timeline_range` | 合并文案与时间线范围 |
| `audio_infos` | 根据音频链接和时间线生成音频信息 |
| `caption_infos` | 根据文本和时间线生成字幕信息 |
| `imgs_infos` | 根据图片链接和时间线生成图片信息 |
| `keyframes_infos` | 根据片段时间线生成关键帧信息 |
| `rolling_effect` | 根据时长和文本生成快闪时间线 |

备注：神话/香烟模板文件里也出现 `audio_infos`、`caption_infos`、`imgs_infos`、`keyframes_infos` 字样，但那是代码节点里的引用，不是插件节点，故不计入其使用列表。

## 模板节点映射

| 工具 | 模板 | 节点中文名 |
|---|---|---|
| `get_audio_duration` | 烟工作流模板_香烟鉴赏-v1.json | get_audio_duration_1 (132650) / get_audio_duration_2 (1545593) |
|  | 神工作流模板_修改版-开场静态修正-v7.json | get_audio_duration_1 (132650) / get_audio_duration_2 (1545593) |
| `text_splitter` | 书单工作流模板_荐书-v1.json | 口播稿智能分隔 (152468) |
| `timeline_merge` | 书单工作流模板_荐书-v1.json | 合并开场&选题时间线 (196731) / 合并开场&正文时间线 (146102) |
| `effect_infos` | 烟工作流模板_香烟鉴赏-v1.json | 特效数据生成器 (199001) |
|  | 神工作流模板_修改版-开场静态修正-v7.json | 特效数据生成器 (199001) |
| `create_draft` | 书单工作流模板_荐书-v1.json | 创建剪映草稿 (121215) |
|  | 烟工作流模板_香烟鉴赏-v1.json | 创建神话草稿 (119835) |
|  | 神工作流模板_修改版-开场静态修正-v7.json | 创建神话草稿 (119835) |
| `add_audios` | 书单工作流模板_荐书-v1.json | 添加开场人声 (161537) / 添加发条音效 (148232) / 添加开场选题人声 (120409) / 添加背景音乐 (121846) / 添加正文人声 (127166) |
|  | 烟工作流模板_香烟鉴赏-v1.json | 添加人物配音 (117759) / 添加背景音乐 (178582) / 添加轮盘音效 (178583) |
|  | 神工作流模板_修改版-开场静态修正-v7.json | 添加人物配音 (117759) / 添加背景音乐 (178582) / 添加轮盘音效 (178583) |
| `add_images` | 书单工作流模板_荐书-v1.json | 添加开场封面配图 (198946) / 添加开场主题配图 (144998) / 添加开场人物配图 (169833) / 添加正文配图 (191365) |
|  | 烟工作流模板_香烟鉴赏-v1.json | 添加主体图层 (192103) / 添加开场图层 (174538) / 添加底层背景 (174537) / 源模板节点名异常 (150753) / 添加主体前景层 (201368) / 添加重点句特写 (201371) |
|  | 神工作流模板_修改版-开场静态修正-v7.json | 添加主体图层 (192103) / 添加开场图层 (174538) / 添加底层背景 (174537) / 源模板节点名异常 (150753) / 添加主体前景层 (201368) / 添加重点句特写 (201371) |
| `add_captions` | 书单工作流模板_荐书-v1.json | 添加开场字幕 (124102) / 添加开场选题字幕 (1713008) / 添加正文 (143757) / 添加水印 (138594) |
|  | 烟工作流模板_香烟鉴赏-v1.json | 添加正文字幕 (121500) / 主题锁定字幕 (195903) / 横滑字幕轨道 (108685) / 添加顶部标签 (126860) / 横滑字幕轨道B (201377) / 横滑字幕轨道C (201378) / 添加右上提示 (226902) |
|  | 神工作流模板_修改版-开场静态修正-v7.json | 添加正文字幕 (121500) / 主题锁定字幕 (195903) / 横滑字幕轨道 (108685) / 添加顶部标签 (126860) / 横滑字幕轨道B (201377) / 横滑字幕轨道C (201378) / 添加右上提示 (226902) |
| `add_keyframes` | 书单工作流模板_荐书-v1.json | 添加x轴关键帧 (129095) / 添加y轴关键帧 (116900) / 添加正文配图关键帧 (300101) |
|  | 烟工作流模板_香烟鉴赏-v1.json | 添加横滑字幕关键帧 (201391) |
|  | 神工作流模板_修改版-开场静态修正-v7.json | 添加横滑字幕关键帧 (201391) |
| `add_effects` | 烟工作流模板_香烟鉴赏-v1.json | 添加开场特效 (177705) / 添加主体特效 (124207) |
|  | 神工作流模板_修改版-开场静态修正-v7.json | 添加开场特效 (177705) / 添加主体特效 (124207) |
| `align_text_to_audio` | 烟工作流模板_香烟鉴赏-v1.json | 字幕对齐 (152927) / 字幕复核对齐 (188944) |
|  | 神工作流模板_修改版-开场静态修正-v7.json | 字幕对齐 (152927) / 字幕复核对齐 (188944) |
| `audio_infos` | 书单工作流模板_荐书-v1.json | 根据时间线制作开场人声 (150527) / 根据时间线制作发条音效 (188768) / 根据时间线制作开场选题人声 (158961) / 根据时间线制作背景音乐 (183599) / 根据时间线制作正文人声 (182030) |
| `audio_link_collector` | 书单工作流模板_荐书-v1.json | 提取正文音频链接 (150200) / 提取开场语音链接 (152457) / 提取选题语音链接 (181955) |
| `audio_timelines` | 书单工作流模板_荐书-v1.json | 提取开场文案音频时间线 (175569) / 提取选题音频时间线 (190379) / audio_timelines (110949) |
| `caption_infos` | 书单工作流模板_荐书-v1.json | 根据时间线制作开场字幕 (123312) / 根据时间线制作预制选题字幕 (169841) / 根据时间线制作开场选题字幕 (116477) / 根据时间线制作正文字幕 (153682) / 根据时间线制作水印 (129599) |
| `imgs_infos` | 书单工作流模板_荐书-v1.json | 根据时间线制作开场主题配图 (112803) / 根据时间线制作开场封面配图 (136311) / 根据时间线制作开场人物配图 (129774) / 根据时间线制作正文配图 (169038) |
| `keyframes_infos` | 书单工作流模板_荐书-v1.json | 根据时间线制作人物x轴关键帧 (145916) / 根据时间线制作人物y轴关键帧 (172251) |
| `rolling_effect` | 书单工作流模板_荐书-v1.json | 开场快闪 (108338) |
| `wenan_timeline_range` | 书单工作流模板_荐书-v1.json | 文案合并时间线 (107972) |
| `speech_synthesis` | 书单工作流模板_荐书-v1.json | speech_synthesis (154758) / speech_synthesis_1 (1351770) / speech_synthesis_2 (1033952) |
|  | 烟工作流模板_香烟鉴赏-v1.json | 分镜配音 (102982) / 开场配音 (310628) / 标题配音 (1711088) |
|  | 神工作流模板_修改版-开场静态修正-v7.json | 分镜配音 (102982) / 开场配音 (310628) / 标题配音 (1711088) |
| `jimeng_generate_image` | 书单工作流模板_荐书-v1.json | 图片生成 (153667) / 图片生成2 (1942817) |
|  | 烟工作流模板_香烟鉴赏-v1.json | 分镜生图A (201365) / 神话生图 (117364) |
|  | 神工作流模板_修改版-开场静态修正-v7.json | 分镜生图A (201365) / 神话生图 (117364) |

## 输入输出样例

### `get_audio_duration`

输入示例:

```json
{
  "mp3_url": "https://example.com/demo.mp3"
}
```

输出示例:

```json
{
  "success": true,
  "duration": 12.34,
  "message": "ok"
}
```

### `text_splitter`

输入示例:

```json
{
  "text": "第一句。第二句！第三句？"
}
```

输出示例:

```json
{
  "success": true,
  "segments": [
    "第一句，第二句，第三句"
  ],
  "message": "ok",
  "error": ""
}
```

### `timeline_merge`

输入示例:

```json
{
  "pre_timeline": [
    {
      "start": 0,
      "end": 1000000
    }
  ],
  "main_timeline": [
    {
      "start": 0,
      "end": 2000000
    }
  ],
  "gap_us": 0
}
```

输出示例:

```json
{
  "timelines": [
    {
      "start": 1000000,
      "end": 3000000
    }
  ],
  "all_timeline": [
    {
      "start": 0,
      "end": 1000000
    },
    {
      "start": 1000000,
      "end": 3000000
    }
  ],
  "last_end_us": 3000000,
  "error": ""
}
```

### `effect_infos`

输入示例:

```json
{
  "effects": [
    "shake",
    "flash"
  ],
  "timelines": [
    {
      "start": 0,
      "end": 1000000
    },
    {
      "start": 1000000,
      "end": 2000000
    }
  ]
}
```

输出示例:

```json
{
  "infos": "[{\"effect\": \"shake\", \"start\": 0, \"end\": 1000000}, {\"effect\": \"flash\", \"start\": 1000000, \"end\": 2000000}]",
  "count": 2,
  "error": ""
}
```

### `create_draft`

输入示例:

```json
{
  "width": 1080,
  "height": 1920,
  "name": "demo_draft"
}
```

输出示例:

```json
{
  "draft_id": "DEMO-DRAFT-ID",
  "draft_dir": "C:/.../DEMO-DRAFT-ID",
  "width": 1080,
  "height": 1920,
  "ratio": "9:16",
  "message": "ok"
}
```

### `add_audios`

输入示例:

```json
{
  "draft_id": "DEMO-DRAFT-ID",
  "audio_infos": [
    {
      "audio_url": "https://example.com/a.wav",
      "start": 0,
      "end": 1200000,
      "volume": 0.7
    }
  ]
}
```

输出示例:

```json
{
  "draft_id": "DEMO-DRAFT-ID",
  "audio_ids": [
    "AUDIO-MAT-ID"
  ],
  "segment_ids": [
    "AUDIO-SEG-ID"
  ],
  "segment_infos": [
    {
      "id": "AUDIO-SEG-ID",
      "start": 0,
      "end": 1200000
    }
  ],
  "track_id": "AUDIO-TRACK-ID",
  "message": "ok"
}
```

### `add_images`

输入示例:

```json
{
  "draft_id": "DEMO-DRAFT-ID",
  "image_infos": [
    {
      "image_url": "https://example.com/1.png",
      "start": 0,
      "end": 3000000
    }
  ]
}
```

输出示例:

```json
{
  "draft_id": "DEMO-DRAFT-ID",
  "segment_ids": [
    "IMG-SEG-ID"
  ],
  "segment_infos": [
    {
      "id": "IMG-SEG-ID",
      "start": 0,
      "end": 3000000
    }
  ],
  "track_id": "VIDEO-TRACK-ID",
  "message": "ok"
}
```

### `add_captions`

输入示例:

```json
{
  "draft_id": "DEMO-DRAFT-ID",
  "captions": [
    {
      "text": "字幕测试",
      "start": 0,
      "end": 2000000
    }
  ],
  "font_size": 18,
  "text_color": "#FFFFFF"
}
```

输出示例:

```json
{
  "draft_id": "DEMO-DRAFT-ID",
  "segment_ids": [
    "TEXT-SEG-ID"
  ],
  "segment_infos": [
    {
      "id": "TEXT-SEG-ID",
      "start": 0,
      "end": 2000000
    }
  ],
  "track_id": "TEXT-TRACK-ID",
  "message": "ok"
}
```

### `add_keyframes`

输入示例:

```json
{
  "draft_id": "DEMO-DRAFT-ID",
  "keyframes": [
    {
      "segment_id": "IMG-SEG-ID",
      "offset": 0,
      "property": "KFTypePositionX",
      "value": 0.0
    },
    {
      "segment_id": "IMG-SEG-ID",
      "offset": 3000000,
      "property": "KFTypePositionX",
      "value": 0.2
    }
  ]
}
```

输出示例:

```json
{
  "draft_id": "DEMO-DRAFT-ID",
  "applied": 2,
  "message": "ok"
}
```

### `add_effects`

输入示例:

```json
{
  "draft_id": "DEMO-DRAFT-ID",
  "effect_infos": [
    {
      "effect": "shake",
      "start": 0,
      "end": 1000000
    }
  ]
}
```

输出示例:

```json
{
  "draft_id": "DEMO-DRAFT-ID",
  "effect_ids": [
    "EFFECT-MAT-ID"
  ],
  "segment_ids": [
    "EFFECT-SEG-ID"
  ],
  "track_id": "EFFECT-TRACK-ID",
  "message": "ok"
}
```

### `align_text_to_audio`

输入示例:

```json
{
  "text": "第一句字幕。第二句字幕。第三句字幕。",
  "audio_url": "http://127.0.0.1:5001/api/generated/audio/demo.wav",
  "max_chars_per_line": 6
}
```

输出示例:

```json
{
  "texts": [
    "第一句字幕",
    "第二句字幕",
    "第三句字幕"
  ],
  "timelines": [
    {
      "start": 0,
      "end": 400000
    },
    {
      "start": 400000,
      "end": 800000
    },
    {
      "start": 800000,
      "end": 1200000
    }
  ],
  "data": {
    "audio_url": "http://127.0.0.1:5001/api/generated/audio/demo.wav",
    "duration": 1.2
  }
}
```

### `audio_infos`

输入示例:

```json
{
  "mp3_urls": [
    "https://example.com/a.wav"
  ],
  "timelines": [
    {
      "start": 0,
      "end": 1200000
    }
  ],
  "volume": 0.7
}
```

输出示例:

```json
{
  "infos": "[{\"audio_url\": \"https://example.com/a.wav\", \"start\": 0, \"end\": 1200000, \"duration\": 1200000, \"volume\": 0.7}]",
  "count": 1,
  "error": ""
}
```

### `audio_link_collector`

输入示例:

```json
{
  "outputList": [
    {
      "code": 0,
      "data": {
        "link": "https://example.com/a.wav"
      }
    }
  ]
}
```

输出示例:

```json
{
  "links": [
    "https://example.com/a.wav"
  ]
}
```

### `audio_timelines`

输入示例:

```json
{
  "links": [
    "https://example.com/a.wav",
    "https://example.com/b.wav"
  ]
}
```

输出示例:

```json
{
  "timelines": [
    {
      "start": 0,
      "end": 1200000
    },
    {
      "start": 1200000,
      "end": 2400000
    }
  ],
  "all_timelines": [
    {
      "start": 0,
      "end": 1200000
    },
    {
      "start": 1200000,
      "end": 2400000
    }
  ]
}
```

### `caption_infos`

输入示例:

```json
{
  "texts": [
    "第一句",
    "第二句"
  ],
  "timelines": [
    {
      "start": 0,
      "end": 1000000
    },
    {
      "start": 1000000,
      "end": 2000000
    }
  ],
  "font_size": 18
}
```

输出示例:

```json
{
  "infos": "[{\"text\": \"第一句\", \"start\": 0, \"end\": 1000000, \"font_size\": 18}, {\"text\": \"第二句\", \"start\": 1000000, \"end\": 2000000, \"font_size\": 18}]",
  "count": 2,
  "error": ""
}
```

### `imgs_infos`

输入示例:

```json
{
  "imgs": [
    "https://example.com/1.png",
    "https://example.com/2.png"
  ],
  "timelines": [
    {
      "start": 0,
      "end": 1000000
    },
    {
      "start": 1000000,
      "end": 2000000
    }
  ]
}
```

输出示例:

```json
{
  "infos": "[{\"image_url\": \"https://example.com/1.png\", \"start\": 0, \"end\": 1000000}, {\"image_url\": \"https://example.com/2.png\", \"start\": 1000000, \"end\": 2000000}]",
  "count": 2,
  "error": ""
}
```

### `keyframes_infos`

输入示例:

```json
{
  "ctype": "KFTypePositionX",
  "offsets": "0|100",
  "values": "120|-120",
  "width": 1080,
  "segment_infos": [
    {
      "id": "IMG-SEG-ID",
      "start": 0,
      "end": 2000000
    }
  ]
}
```

输出示例:

```json
{
  "keyframes_infos": "[{\"offset\": 0, \"property\": \"KFTypePositionX\", \"segment_id\": \"IMG-SEG-ID\", \"value\": 0.1111111111111111}, {\"offset\": 2000000, \"property\": \"KFTypePositionX\", \"segment_id\": \"IMG-SEG-ID\", \"value\": -0.1111111111111111}]",
  "count": 2,
  "error": ""
}
```

### `rolling_effect`

输入示例:

```json
{
  "duration_list": [
    1000000,
    2000000
  ],
  "str_list": [
    "主题1",
    "主题2"
  ]
}
```

输出示例:

```json
{
  "subject_arr": [
    "主题1",
    "主题2"
  ],
  "timelines": [
    {
      "start": 0,
      "end": 1000000
    },
    {
      "start": 1000000,
      "end": 3000000
    }
  ],
  "all_timeline": [
    {
      "start": 0,
      "end": 1000000
    },
    {
      "start": 1000000,
      "end": 3000000
    }
  ],
  "error": ""
}
```

### `wenan_timeline_range`

输入示例:

```json
{
  "timelines": [
    {
      "start": 0,
      "end": 1000000
    }
  ],
  "wenan": [
    "第一句文案"
  ]
}
```

输出示例:

```json
{
  "wenanTimeline": [
    {
      "content": "第一句文案",
      "start": 0,
      "end": 1000000
    }
  ],
  "error": ""
}
```

### `speech_synthesis`

备注: 当前为本地 placeholder 配音实现，会返回可访问的音频 URL，但不是 Coze 官方语音合成。

输入示例:

```json
{
  "text": "本地语音测试",
  "voice_id": "7620288417930297386",
  "speed_ratio": 1.0
}
```

输出示例:

```json
{
  "code": 0,
  "data": {
    "duration": 1.2,
    "link": "http://127.0.0.1:5001/api/generated/audio/demo.wav"
  },
  "log_id": "DEMO-LOG-ID",
  "msg": "ok (local placeholder audio)"
}
```

### `jimeng_generate_image`

备注: 当前为本地 placeholder 生图实现，会返回可访问的图片 URL，但不是米核/即梦真实生图。

输入示例:

```json
{
  "prompt": "敦煌壁画风格神话画面，16:9 横屏",
  "ratio": "16:9",
  "model": "jimeng-3.0"
}
```

输出示例:

```json
{
  "message": "ok (local placeholder image, not Mihe/Jimeng real generation)",
  "task_id": "DEMO-TASK-ID",
  "url": "http://127.0.0.1:5001/api/generated/image/demo.png"
}
```
