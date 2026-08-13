# Workflow media Worker

This Worker exposes read-only objects from the `douyin-workflow-public` R2
bucket. Only the `covers/`, `previews/`, `workflows/`, and exported-video
`exports/` key prefixes are public.

`PUT /exports/<name>.mp4` and multipart upload actions accept either the
production `EXPORT_UPLOAD_TOKEN` secret or a short-lived HMAC token scoped to
one exact object key. The API server issues scoped tokens only to the paired
device that owns the render job, so the permanent secret is never installed in
the desktop helper. Other prefixes are never writable.

`GET /exports/_?action=list&limit=500&cursor=...` returns an export-object
inventory for recovery and requires the same bearer token. It exposes only
object names, sizes, upload times, and ETags.

Deploy from this directory with:

```powershell
wrangler deploy
```
