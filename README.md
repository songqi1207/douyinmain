# AIVideoCreator Workflow Center

FastAPI + React workflow center for generating draft keys, queuing local Jianying exports, and serving helper downloads.

## Local Development

```bash
python -m uvicorn fastapi_app:app --host 127.0.0.1 --port 8000
```

```bash
cd frontend
npm ci
npm run dev
```

Open `http://localhost:5173/business/`.

## Docker

```bash
docker compose build --no-cache
docker compose up -d
```

The Dockerfile builds the React frontend first, then starts `fastapi_app:app` with Uvicorn.
