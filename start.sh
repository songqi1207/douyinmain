#!/bin/bash
set -e

cd "$(dirname "$0")"
python3 -m uvicorn fastapi_app:app --host 0.0.0.0 --port "${PORT:-8000}"
