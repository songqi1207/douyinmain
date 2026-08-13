"""Short-lived, object-scoped credentials for direct device uploads."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def create_direct_upload_token(
    secret: str,
    *,
    object_key: str,
    job_id: str,
    device_id: str,
    size_bytes: int,
    part_bytes: int,
    ttl_seconds: int = 7200,
    now: float | None = None,
) -> str:
    """Create a bearer token that can upload only one exact R2 object."""

    normalized_secret = str(secret or "").strip()
    if not normalized_secret:
        raise ValueError("direct upload signing secret is empty")
    issued_at = int(time.time() if now is None else now)
    normalized_size = int(size_bytes)
    normalized_part_size = int(part_bytes)
    if normalized_size < 1 or normalized_part_size < 1:
        raise ValueError("direct upload size is invalid")
    payload = {
        "v": 1,
        "op": "upload",
        "key": str(object_key),
        "job_id": str(job_id),
        "device_id": str(device_id),
        "size_bytes": normalized_size,
        "part_bytes": normalized_part_size,
        "total_parts": (normalized_size + normalized_part_size - 1) // normalized_part_size,
        "iat": issued_at,
        "exp": issued_at + max(300, min(86400, int(ttl_seconds))),
    }
    payload_segment = _base64url(
        json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    signature = hmac.new(
        normalized_secret.encode("utf-8"),
        payload_segment.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{payload_segment}.{_base64url(signature)}"
