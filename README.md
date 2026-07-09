---
title: Coze Audio Tools
emoji: hammer_and_wrench
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# Coze Audio Tools

Self-hosted utility service for Coze plugin deployment.

## Endpoints

- `GET /api/openapi/coze_audio_tools.json`
- `POST /api/tools/get_audio_duration`

## Example

```bash
curl -X POST "https://<your-space>.hf.space/api/tools/get_audio_duration" \
  -H "Content-Type: application/json" \
  -d "{\"mp3_url\":\"https://example.com/test.mp3\"}"
```

## Response

```json
{
  "success": true,
  "duration": 12.34,
  "message": "ok"
}
```

## Coze Import

Import this OpenAPI URL into Coze:

`https://<your-space>.hf.space/api/openapi/coze_audio_tools.json`

## Deploy to Hugging Face Spaces

```bash
python -m pip install huggingface_hub
python scripts/publish_hf_space.py --repo-id <username>/<space-name> --token <hf_token>
```
