# Workflow media Worker

This Worker exposes read-only objects from the `douyin-workflow-public` R2
bucket. Only the `covers/`, `previews/`, `workflows/`, and exported-video
`exports/` key prefixes are public.

`PUT /exports/<name>.mp4` is reserved for the production server and requires
the `EXPORT_UPLOAD_TOKEN` Worker secret. Other prefixes are never writable.

`GET /exports/_?action=list&limit=500&cursor=...` returns an export-object
inventory for recovery and requires the same bearer token. It exposes only
object names, sizes, upload times, and ETags.

Deploy from this directory with:

```powershell
wrangler deploy
```
