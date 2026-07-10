# 草稿 key 数据包 Schema（v1.0）

「key」是 Coze 工作流的最终输出：一个 JSON 数据包，承载拼接一个剪映草稿所需的全部调用序列。
本地消费方式（三选一）：

```bash
# CLI（推荐，不用起服务）
python scripts/import_draft_key.py key.json [--force] [--dry-run] [--stdin]

# HTTP（Flask 服务 5001）
POST /api/tools/create_draft_from_key      # body 即 key 本体，或 {"key": {...}} / {"key_json": "..."}
                                           # query/body 支持 force=1 / dry_run=1
```

```python
from utils.draft_key_importer import import_draft_key
report = import_draft_key(key, force=False, dry_run=False)
```

## 顶层结构

```json
{
  "schema_version": "1.0",
  "kind": "jianying_draft_key",
  "meta": { "workflow": "神工作流模板_本地草稿", "run_id": "god_local_1720000000", "title": "玉帝" },
  "draft": { "width": 1920, "height": 1080, "name": "玉帝_神话解说" },
  "calls": [ ... ]
}
```

| 字段 | 说明 |
|---|---|
| `meta.run_id` | 幂等指纹。同 run_id 重复导入直接返回已导入草稿；缺失时用 key 全文 sha256 |
| `draft` | 直传 create_draft；`name` 缺省取 `meta.title` |
| `calls` | **数组顺序 = 执行顺序**。轨道分配、图层叠放（render_index）都按此顺序递增 |

## calls 条目

```json
{ "call_id": "main_captions", "tool": "add_captions", "params": { ... },
  "track_name": "可选，缺省自动生成", "render_index": "可选，缺省类型基数+同类调用序号" }
```

- `call_id`：key 内唯一，供 `segment_ref` 引用；缺省自动取 `call_{序号}`
- `tool` ∈ `add_audios` / `add_images` / `add_captions` / `add_keyframes` / `add_effects`
- 每次调用独立建一条轨道（自动名 `{type}_{NN}_{call_id}`）；显式指定相同 `track_name` 可合并到同轨
- 各工具的列表参数既接受数组也接受 JSON 字符串（Coze 代码节点输出字符串更省事）

### add_audios

```json
{ "params": { "audio_infos": [ { "audio_url": "https://...", "start": 0, "end": 42000000, "volume": 0.3 } ] } }
```

时间统一微秒（<10000 的数按秒自适应）。`end` 缺省时本地用 ffprobe 探测时长。

### add_images

```json
{ "params": { "image_infos": [ { "image_url": "https://...", "start": 0, "end": 5000000,
    "scale_x": 1.2, "scale_y": 1.2, "transform_x": 0, "transform_y": 22,
    "in_animation": "Kira游动", "in_animation_duration": 500000, "out_animation": "" } ], "alpha": 1 } }
```

- `in_animation`/`out_animation`：剪映动画名，从 `utils/data/jianying_meta.json` 的 video_intros/video_outros 表解析 resource_id；未命中记 warning 并忽略
- `transform_x/y`：剪映 UI 像素值（|值|>3 时自动按 x/画布宽、y/画布高 归一化；≤3 视为已归一化直接透传）

### add_captions

```json
{ "params": { "captions": [ { "text": "玉皇大帝", "start": 0, "end": 3000000 } ],
    "font": "江湖体", "font_size": 9, "text_color": "#FFE95A", "border_color": "#000000",
    "alignment": 1, "letter_spacing": 5, "line_spacing": 0, "alpha": 1,
    "scale_x": 1, "scale_y": 1, "transform_x": 0, "transform_y": -600 } }
```

- 调用级样式参数对本次全部 captions 生效；条目里同名字段可逐条覆盖
- `font` 按名字查字体表拿 resource_id；`border_color` 为 `#00XXXXXX`（全透明）视为无描边
- `letter_spacing`/`line_spacing` 传剪映 UI 值，落盘时按剪映映射换算

### add_keyframes

```json
{ "params": { "keyframes": [
    { "segment_ref": { "call_id": "main_images", "index": 0 },
      "offset": 0, "property": "KFTypePositionX", "value": 0.6 } ] } }
```

- **`segment_ref` 代替真实 segment_id**（Coze 侧拿不到本地生成的 id）：`call_id` 只能指向 calls 里更靠前的片段调用，`index` 是该次调用第几个条目；也兼容直接给 `segment_id`（手工调试）
- `property` 白名单：`KFTypePositionX/Y`、`UNIFORM_SCALE`、`KFTypeScaleX/Y`、`KFTypeRotation`、`KFTypeAlpha`、`KFTypeVolume`、`KFTypeSaturation/Contrast/Brightness`
- `offset` 相对片段开头的微秒；位置类 `value` 为归一化值（剪映显示值/画布边长），|值|>3 自动按像素换算

### add_effects

```json
{ "params": { "effect_infos": [ { "effect": "金粉闪闪", "start": 0, "end": 2000000 } ] } }
```

特效名从元数据表（1097 个画面特效 + 240 个人物特效）解析 effect_id/resource_id；未命中记 warning，剪映端大概率加载不出来。

## 导入器行为

- **validate**：tool 白名单、call_id 唯一、segment_ref 只许前向引用、property 白名单。任一错误直接拒绝，不创建草稿
- **prefetch**：全部远程素材先下载到 `temp/draft_key_cache/`（按 URL sha1 缓存，3 次重试）。任一失败整体中止，**不产生半成品草稿**。Coze 素材 URL 有时效，拿到 key 尽快导入
- **execute**：create_draft → 按序执行 calls，每调用独立轨道 + render_index 递增（音频 11000+n / 图 14000+n / 文字 15000+n / 特效 16000+n）
- **幂等**：指纹登记在 `temp/draft_key_imports.json`；重复导入返回 `already_imported: true`；`--force` 删旧草稿（含 root_meta_info 条目）重导
- 草稿写入位置：`JIANYING_DRAFT_ROOT` 环境变量 > 剪映默认草稿目录 > 兜底 `temp/jianying_drafts/`

## 完整样例

见 [sample_draft_key.json](sample_draft_key.json)。Coze 侧的产出方式见 `workflows/god/local_key.py`
（生成 `神工作流模板_本地草稿-v1.json`：剪映小助手节点已替换为「汇总草稿key」代码节点，End 输出 key 字符串）。

## 已知降级项（对比剪映小助手云端拼装）

- 文本花字/气泡/阴影暂不支持（描边支持）
- 图片组合动画（group）有元数据表但 key schema v1 未暴露
- 真机兼容性基准为 pyJianYingDraft 0.3.0（剪映 5.9+/6.x 草稿结构，version 360000 / new_version 110.0.0）；首次使用务必在真机过一遍闸门验证
