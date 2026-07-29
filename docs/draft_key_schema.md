# Draft Key Schema

`draft_key` is the JSON payload used by the workflow generator to describe a Jianying draft.

## Local Import

```bash
python scripts/import_draft_key.py key.json [--force] [--dry-run] [--stdin]
```

## FastAPI Usage

Current generation and export flows are exposed through `fastapi_app.py`:

- `POST /api/v1/jobs`
- `POST /api/v1/draft-key-renders`
- `GET /api/v1/jobs/{job_id}`
- `GET /api/v1/jobs/{job_id}/logs`

The old Flask `/api/tools/*` service has been removed from the active application.

## Top-Level Shape

```json
{
  "schema_version": "1.0",
  "kind": "jianying_draft_key",
  "meta": {
    "workflow": "example",
    "run_id": "example-run-id",
    "title": "example title"
  },
  "draft": {
    "width": 1080,
    "height": 1920,
    "name": "example draft"
  },
  "calls": []
}
```

`calls` is an ordered list of draft operations such as audio, image, caption, effect, and keyframe insertion.
