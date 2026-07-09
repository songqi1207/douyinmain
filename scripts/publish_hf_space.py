#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Create or update a Hugging Face Docker Space from this repo."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-id", required=True, help="Space repo id, e.g. username/coze-audio-tools")
    parser.add_argument("--token", default=os.getenv("HF_TOKEN", ""), help="Hugging Face token")
    parser.add_argument("--private", action="store_true", help="Create the Space as private")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    token = (args.token or "").strip()
    if not token:
        print("HF token is required. Pass --token or set HF_TOKEN.", file=sys.stderr)
        return 2

    try:
        from huggingface_hub import HfApi
    except ImportError:
        print("Missing dependency: huggingface_hub. Install with `python -m pip install huggingface_hub`.", file=sys.stderr)
        return 2

    repo_root = Path(__file__).resolve().parent.parent
    api = HfApi(token=token)

    api.create_repo(
        repo_id=args.repo_id,
        repo_type="space",
        space_sdk="docker",
        private=args.private,
        exist_ok=True,
    )

    api.upload_folder(
        repo_id=args.repo_id,
        repo_type="space",
        folder_path=str(repo_root),
        ignore_patterns=[
            ".git/*",
            "__pycache__/*",
            "*.pyc",
            "*.pyo",
            "*.log",
            ".env",
            "env/*",
            "venv/*",
            ".venv/*",
            "terminals/*",
            "agent-transcripts/*",
        ],
        commit_message="Deploy Coze Audio Tools Space",
    )

    space_host = args.repo_id.replace("/", "-") + ".hf.space"
    print(f"Space uploaded: https://huggingface.co/spaces/{args.repo_id}")
    print(f"Runtime URL: https://{space_host}")
    print(f"Coze OpenAPI URL: https://{space_host}/api/openapi/coze_audio_tools.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
