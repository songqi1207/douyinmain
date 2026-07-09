# Coze Programming Deployment

This repo can be migrated into Coze Programming as a web app project and then exposed to Coze plugins through its public domain.

## Why this route

- Coze Programming supports importing an existing GitHub repo or a local zip project.
- Coze Programming provides a cloud coding environment with file editor and terminal.
- Web app projects can contain full frontend and backend logic and can be deployed to a public `.coze.site` domain.
- Coze plugins can be created from an existing public API service.

## Recommended project type

Use a `web app` project in Coze Programming.

Reason:
- This repo is a Flask service with HTTP endpoints.
- We need a public domain for:
  - `POST /api/tools/get_audio_duration`
  - `GET /api/openapi/coze_audio_tools.json`

## Import options

### Option A: GitHub import

1. Push this repo to GitHub.
2. In Coze Programming, use `Import > GitHub Import`.
3. Select the repo and let Coze initialize the project.

Reference:
- https://docs.coze.cn/guides_import_from_github

### Option B: Local zip import

1. Zip the repo root.
2. In Coze Programming, import the local project package.

Reference:
- https://docs.coze.cn/guides_import_from_github

## What to tell Coze AI after import

Paste this prompt into Coze Programming:

```text
This is an existing Flask backend project.

Do not rewrite it into another framework unless required.
Keep these endpoints unchanged:
- GET /api/openapi/coze_audio_tools.json
- POST /api/tools/get_audio_duration

The project depends on:
- Python 3.11
- pip install -r requirements.txt
- ffprobe/ffmpeg available in runtime
- nodejs is required by existing template generator scripts

Please make the imported project runnable inside Coze Programming, preserve the API behavior, and expose it through the deployed project domain.
```

## Required environment variables

At minimum, set these if the related features are needed:

- `MIHE_KEY`
- `CDN_TOKEN`
- `PREVIEW_VIDEO_URL_BOOK`
- `PREVIEW_VIDEO_URL_CIGARETTE`
- `PREVIEW_VIDEO_URL_GOD`

Reference:
- https://docs.coze.cn/guides_environment_variables

## Run and verify inside Coze Programming

Use the built-in terminal to verify:

```bash
pip install -r requirements.txt
python app.py
```

Then verify:

```bash
curl http://127.0.0.1:5001/api/openapi/coze_audio_tools.json
curl -X POST http://127.0.0.1:5001/api/tools/get_audio_duration \
  -H "Content-Type: application/json" \
  -d "{\"file_path\":\"./temp/test.wav\"}"
```

Reference:
- https://docs.coze.cn/guides_ai_powered_workflow_development

## Deploy

Deploy the imported web app project and use the default `.coze.site` domain or a custom domain.

References:
- https://docs.coze.cn/guides_deploy_vibe_web
- https://docs.coze.cn/guides_deployment_ops_overview

## Convert deployed API into a Coze plugin

After deployment, create a plugin from the deployed domain:

1. Go to `Resource Library > Plugin`
2. Create plugin from existing API service
3. Base URL: your deployed project domain
4. Add tool:
   - Path: `/api/tools/get_audio_duration`
   - Method: `POST`
5. Or import:
   - `https://<your-domain>/api/openapi/coze_audio_tools.json`

References:
- https://docs.coze.cn/guides_services
- https://docs.coze.cn/guides_import

## Expected final URL shape

- `https://<your-project>.coze.site/api/openapi/coze_audio_tools.json`
- `https://<your-project>.coze.site/api/tools/get_audio_duration`
