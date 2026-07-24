"""Pair and authenticate user-owned Windows Jianying render devices."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import time
import uuid
from pathlib import Path

from site_accounts import DB_PATH


PAIRING_TTL_SECONDS = int(os.getenv("DEVICE_PAIRING_TTL_SECONDS") or 600)
ONLINE_TTL_SECONDS = int(os.getenv("DEVICE_ONLINE_TTL_SECONDS") or 90)


def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=30)
    connection.row_factory = sqlite3.Row
    return connection


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def init_device_database() -> None:
    with _connect() as db:
        db.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS render_devices (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                name TEXT NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                platform TEXT NOT NULL,
                capabilities_json TEXT NOT NULL DEFAULT '{}',
                last_seen REAL,
                created_at REAL NOT NULL,
                revoked_at REAL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_render_devices_user
                ON render_devices(user_id, revoked_at, last_seen);
            CREATE TABLE IF NOT EXISTS render_pairing_codes (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                code_hash TEXT NOT NULL UNIQUE,
                expires_at REAL NOT NULL,
                created_at REAL NOT NULL,
                consumed_at REAL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_render_pairing_codes_expiry
                ON render_pairing_codes(expires_at, consumed_at);
            """
        )
        db.commit()


def _public_device(row, now: float | None = None) -> dict:
    current = time.time() if now is None else now
    try:
        capabilities = json.loads(row["capabilities_json"] or "{}")
    except (TypeError, ValueError):
        capabilities = {}
    last_seen = row["last_seen"]
    return {
        "id": row["id"],
        "name": row["name"],
        "platform": row["platform"],
        "capabilities": capabilities,
        "online": bool(last_seen and current - float(last_seen) <= ONLINE_TTL_SECONDS),
        "last_seen": last_seen,
        "created_at": row["created_at"],
    }


def create_pairing_code(user_id: str) -> dict:
    now = time.time()
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    with _connect() as db:
        db.execute(
            "DELETE FROM render_pairing_codes WHERE expires_at < ? OR consumed_at IS NOT NULL",
            (now,),
        )
        for _ in range(8):
            code = "".join(secrets.choice(alphabet) for _ in range(8))
            try:
                db.execute(
                    """INSERT INTO render_pairing_codes
                       (id, user_id, code_hash, expires_at, created_at, consumed_at)
                       VALUES (?, ?, ?, ?, ?, NULL)""",
                    (uuid.uuid4().hex, user_id, _digest(code), now + PAIRING_TTL_SECONDS, now),
                )
                db.commit()
                return {"code": code, "expires_at": now + PAIRING_TTL_SECONDS}
            except sqlite3.IntegrityError:
                continue
    raise RuntimeError("pairing_code_unavailable")


def pair_device(code: str, name: str, platform: str = "windows", capabilities: dict | None = None) -> dict:
    normalized_code = "".join(str(code or "").upper().split())
    normalized_name = str(name or "").strip()[:80] or "我的电脑"
    normalized_platform = str(platform or "windows").strip().lower()[:30]
    if len(normalized_code) != 8:
        raise ValueError("配对码无效或已过期")
    now = time.time()
    token = secrets.token_urlsafe(40)
    device_id = uuid.uuid4().hex
    with _connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            """SELECT p.*, u.active FROM render_pairing_codes p
               JOIN users u ON u.id = p.user_id
               WHERE p.code_hash = ?""",
            (_digest(normalized_code),),
        ).fetchone()
        if not row or row["consumed_at"] is not None or row["expires_at"] < now or not int(row["active"]):
            db.rollback()
            raise ValueError("配对码无效或已过期")
        db.execute(
            """INSERT INTO render_devices
               (id, user_id, name, token_hash, platform, capabilities_json, last_seen, created_at, revoked_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)""",
            (
                device_id,
                row["user_id"],
                normalized_name,
                _digest(token),
                normalized_platform,
                json.dumps(capabilities or {}, ensure_ascii=False),
                None,
                now,
            ),
        )
        db.execute(
            "UPDATE render_pairing_codes SET consumed_at = ? WHERE id = ?",
            (now, row["id"]),
        )
        db.commit()
    return {"device_id": device_id, "device_token": token, "name": normalized_name}


def authenticate_device(token: str) -> dict | None:
    raw = str(token or "").strip()
    if not raw:
        return None
    with _connect() as db:
        row = db.execute(
            """SELECT d.*, u.active FROM render_devices d
               JOIN users u ON u.id = d.user_id
               WHERE d.token_hash = ? AND d.revoked_at IS NULL""",
            (_digest(raw),),
        ).fetchone()
    if not row or not int(row["active"]):
        return None
    return {**_public_device(row), "user_id": row["user_id"]}


def heartbeat_device(device_id: str, capabilities: dict | None = None) -> dict | None:
    now = time.time()
    with _connect() as db:
        if capabilities is None:
            cursor = db.execute(
                "UPDATE render_devices SET last_seen = ? WHERE id = ? AND revoked_at IS NULL",
                (now, device_id),
            )
        else:
            cursor = db.execute(
                """UPDATE render_devices SET last_seen = ?, capabilities_json = ?
                   WHERE id = ? AND revoked_at IS NULL""",
                (now, json.dumps(capabilities, ensure_ascii=False), device_id),
            )
        db.commit()
        if not cursor.rowcount:
            return None
        row = db.execute("SELECT * FROM render_devices WHERE id = ?", (device_id,)).fetchone()
    return _public_device(row, now)


def list_devices(user_id: str) -> list[dict]:
    with _connect() as db:
        rows = db.execute(
            """SELECT * FROM render_devices
               WHERE user_id = ? AND revoked_at IS NULL
               ORDER BY COALESCE(last_seen, 0) DESC, created_at DESC""",
            (user_id,),
        ).fetchall()
    now = time.time()
    return [_public_device(row, now) for row in rows]


def preferred_device(user_id: str) -> dict | None:
    return next((device for device in list_devices(user_id) if device["online"]), None)


def revoke_device(user_id: str, device_id: str) -> bool:
    with _connect() as db:
        cursor = db.execute(
            """UPDATE render_devices SET revoked_at = ?
               WHERE id = ? AND user_id = ? AND revoked_at IS NULL""",
            (time.time(), device_id, user_id),
        )
        db.commit()
    return bool(cursor.rowcount)


init_device_database()
