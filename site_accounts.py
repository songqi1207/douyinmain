"""Small SQLite account/session store for the member-facing workflow site."""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Iterable

from workflow_jobs import DATA_DIR


DB_PATH = Path(os.getenv("SITE_DB_PATH") or DATA_DIR / "site.sqlite3").resolve()
SESSION_TTL_SECONDS = int(os.getenv("SITE_SESSION_TTL_SECONDS") or 30 * 24 * 60 * 60)
USERNAME_PATTERN = re.compile(r"^[\w\u4e00-\u9fff]{3,20}$", re.UNICODE)
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=30)
    connection.row_factory = sqlite3.Row
    return connection


def init_site_database():
    with _connect() as db:
        db.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                email TEXT,
                password_hash TEXT NOT NULL,
                password_salt TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                active INTEGER NOT NULL DEFAULT 1,
                must_change_password INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                expires_at REAL NOT NULL,
                created_at REAL NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS favorites (
                user_id TEXT NOT NULL,
                resource_type TEXT NOT NULL,
                resource_id TEXT NOT NULL,
                created_at REAL NOT NULL,
                PRIMARY KEY(user_id, resource_type, resource_id),
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS resource_events (
                id TEXT PRIMARY KEY,
                resource_type TEXT NOT NULL,
                resource_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                user_id TEXT,
                dedupe_key TEXT,
                created_at REAL NOT NULL,
                UNIQUE(resource_type, resource_id, event_type, dedupe_key)
            );
            CREATE INDEX IF NOT EXISTS idx_resource_events_lookup
                ON resource_events(resource_type, resource_id, event_type);
            CREATE TABLE IF NOT EXISTS registration_applications (
                id TEXT PRIMARY KEY,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                status TEXT NOT NULL,
                delivery_status TEXT NOT NULL DEFAULT 'not_sent',
                delivery_error TEXT,
                reviewed_by TEXT,
                reviewed_at REAL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                FOREIGN KEY(reviewed_by) REFERENCES users(id)
            );
            """
        )
        columns = {row["name"] for row in db.execute("PRAGMA table_info(users)").fetchall()}
        if "email" not in columns:
            db.execute("ALTER TABLE users ADD COLUMN email TEXT")
        if "active" not in columns:
            db.execute("ALTER TABLE users ADD COLUMN active INTEGER NOT NULL DEFAULT 1")
        if "must_change_password" not in columns:
            db.execute("ALTER TABLE users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0")
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email COLLATE NOCASE) WHERE email IS NOT NULL")
        db.commit()


def _hash_password(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 240_000).hex()


def _public_user(row) -> dict:
    return {
        "id": row["id"],
        "username": row["username"],
        "email": row["email"],
        "role": row["role"],
        "must_change_password": bool(row["must_change_password"]),
    }


def register_user(username: str, password: str) -> dict:
    username = str(username or "").strip()
    if not USERNAME_PATTERN.fullmatch(username):
        raise ValueError("用户名需为 3-20 个中英文、数字或下划线")
    if len(str(password or "")) < 6:
        raise ValueError("密码至少需要 6 个字符")
    salt = secrets.token_bytes(16)
    user_id = uuid.uuid4().hex
    try:
        with _connect() as db:
            db.execute(
                """INSERT INTO users
                   (id, username, email, password_hash, password_salt, role, active, must_change_password, created_at)
                   VALUES (?, ?, NULL, ?, ?, 'user', 1, 0, ?)""",
                (user_id, username, _hash_password(password, salt), salt.hex(), time.time()),
            )
            db.commit()
    except sqlite3.IntegrityError as exc:
        raise ValueError("用户名已存在") from exc
    return {"id": user_id, "username": username, "role": "user"}


def authenticate_user(username: str, password: str) -> dict | None:
    identifier = str(username or "").strip()
    with _connect() as db:
        row = db.execute(
            """SELECT * FROM users
               WHERE active = 1 AND (username = ? COLLATE NOCASE OR email = ? COLLATE NOCASE)""",
            (identifier, identifier),
        ).fetchone()
    if not row:
        return None
    expected = _hash_password(str(password or ""), bytes.fromhex(row["password_salt"]))
    return _public_user(row) if hmac.compare_digest(expected, row["password_hash"]) else None


def _normalize_email(email: str) -> str:
    normalized = str(email or "").strip().lower()
    if len(normalized) > 254 or not EMAIL_PATTERN.fullmatch(normalized):
        raise ValueError("请输入有效的邮箱地址")
    return normalized


def _public_application(row) -> dict:
    return {
        "id": row["id"],
        "email": row["email"],
        "status": row["status"],
        "delivery_status": row["delivery_status"],
        "delivery_error": row["delivery_error"],
        "reviewed_at": row["reviewed_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def submit_registration_application(email: str) -> dict:
    email = _normalize_email(email)
    now = time.time()
    with _connect() as db:
        existing_user = db.execute(
            "SELECT active FROM users WHERE email = ? COLLATE NOCASE", (email,)
        ).fetchone()
        if existing_user and int(existing_user["active"]):
            raise ValueError("该邮箱已经注册，请直接登录")
        existing = db.execute(
            "SELECT * FROM registration_applications WHERE email = ? COLLATE NOCASE", (email,)
        ).fetchone()
        if existing and existing["status"] in {"pending", "delivering"}:
            raise ValueError("该邮箱的申请正在审核中")
        if existing and existing["status"] == "approved":
            raise ValueError("该邮箱已通过审核，请查看邮件并登录")
        if existing:
            db.execute(
                """UPDATE registration_applications
                   SET status = 'pending', delivery_status = 'not_sent', delivery_error = NULL,
                       reviewed_by = NULL, reviewed_at = NULL, updated_at = ? WHERE id = ?""",
                (now, existing["id"]),
            )
            application_id = existing["id"]
        else:
            application_id = uuid.uuid4().hex
            db.execute(
                """INSERT INTO registration_applications
                   (id, email, status, delivery_status, delivery_error, reviewed_by, reviewed_at, created_at, updated_at)
                   VALUES (?, ?, 'pending', 'not_sent', NULL, NULL, NULL, ?, ?)""",
                (application_id, email, now, now),
            )
        db.commit()
        row = db.execute("SELECT * FROM registration_applications WHERE id = ?", (application_id,)).fetchone()
    return _public_application(row)


def list_registration_applications(status: str = "pending") -> list[dict]:
    status = str(status or "pending").strip().lower()
    with _connect() as db:
        if status == "all":
            rows = db.execute(
                "SELECT * FROM registration_applications ORDER BY created_at DESC"
            ).fetchall()
        else:
            if status not in {"pending", "delivering", "approved", "rejected"}:
                raise ValueError("不支持的审核状态")
            rows = db.execute(
                "SELECT * FROM registration_applications WHERE status = ? ORDER BY created_at ASC",
                (status,),
            ).fetchall()
    return [_public_application(row) for row in rows]


def prepare_registration_approval(application_id: str, reviewer_id: str) -> tuple[dict, str]:
    """Create an inactive account and return its one-time generated password for delivery."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
    temporary_password = "".join(secrets.choice(alphabet) for _ in range(12))
    salt = secrets.token_bytes(16)
    now = time.time()
    with _connect() as db:
        application = db.execute(
            "SELECT * FROM registration_applications WHERE id = ?", (application_id,)
        ).fetchone()
        if not application:
            raise KeyError("application_not_found")
        if application["status"] != "pending":
            raise ValueError("只有待审核申请可以通过")
        existing_user = db.execute(
            "SELECT * FROM users WHERE email = ? COLLATE NOCASE", (application["email"],)
        ).fetchone()
        if existing_user and int(existing_user["active"]):
            raise ValueError("该邮箱已经存在可登录账号")
        if existing_user:
            db.execute(
                """UPDATE users SET password_hash = ?, password_salt = ?, active = 0,
                   must_change_password = 0 WHERE id = ?""",
                (_hash_password(temporary_password, salt), salt.hex(), existing_user["id"]),
            )
        else:
            db.execute(
                """INSERT INTO users
                   (id, username, email, password_hash, password_salt, role, active, must_change_password, created_at)
                   VALUES (?, ?, ?, ?, ?, 'user', 0, 0, ?)""",
                (
                    uuid.uuid4().hex,
                    application["email"],
                    application["email"],
                    _hash_password(temporary_password, salt),
                    salt.hex(),
                    now,
                ),
            )
        db.execute(
            """UPDATE registration_applications SET status = 'delivering', delivery_status = 'sending',
               delivery_error = NULL, reviewed_by = ?, reviewed_at = ?, updated_at = ? WHERE id = ?""",
            (reviewer_id, now, now, application_id),
        )
        db.commit()
        row = db.execute("SELECT * FROM registration_applications WHERE id = ?", (application_id,)).fetchone()
    return _public_application(row), temporary_password


def complete_registration_approval(application_id: str) -> dict:
    now = time.time()
    with _connect() as db:
        application = db.execute(
            "SELECT * FROM registration_applications WHERE id = ?", (application_id,)
        ).fetchone()
        if not application or application["status"] != "delivering":
            raise ValueError("申请不在发信处理中")
        db.execute(
            "UPDATE users SET active = 1 WHERE email = ? COLLATE NOCASE", (application["email"],)
        )
        db.execute(
            """UPDATE registration_applications SET status = 'approved', delivery_status = 'sent',
               delivery_error = NULL, updated_at = ? WHERE id = ?""",
            (now, application_id),
        )
        db.commit()
        row = db.execute("SELECT * FROM registration_applications WHERE id = ?", (application_id,)).fetchone()
    return _public_application(row)


def fail_registration_delivery(application_id: str, message: str) -> dict:
    now = time.time()
    safe_message = str(message or "邮件发送失败")[:500]
    with _connect() as db:
        application = db.execute(
            "SELECT * FROM registration_applications WHERE id = ?", (application_id,)
        ).fetchone()
        if not application:
            raise KeyError("application_not_found")
        db.execute(
            "UPDATE users SET active = 0 WHERE email = ? COLLATE NOCASE", (application["email"],)
        )
        db.execute(
            """UPDATE registration_applications SET status = 'pending', delivery_status = 'failed',
               delivery_error = ?, updated_at = ? WHERE id = ?""",
            (safe_message, now, application_id),
        )
        db.commit()
        row = db.execute("SELECT * FROM registration_applications WHERE id = ?", (application_id,)).fetchone()
    return _public_application(row)


def reject_registration_application(application_id: str, reviewer_id: str) -> dict:
    now = time.time()
    with _connect() as db:
        application = db.execute(
            "SELECT * FROM registration_applications WHERE id = ?", (application_id,)
        ).fetchone()
        if not application:
            raise KeyError("application_not_found")
        if application["status"] not in {"pending", "delivering"}:
            raise ValueError("该申请已经处理")
        db.execute(
            "DELETE FROM users WHERE email = ? COLLATE NOCASE AND active = 0", (application["email"],)
        )
        db.execute(
            """UPDATE registration_applications SET status = 'rejected', delivery_status = 'not_sent',
               delivery_error = NULL, reviewed_by = ?, reviewed_at = ?, updated_at = ? WHERE id = ?""",
            (reviewer_id, now, now, application_id),
        )
        db.commit()
        row = db.execute("SELECT * FROM registration_applications WHERE id = ?", (application_id,)).fetchone()
    return _public_application(row)


def ensure_configured_admin() -> None:
    email = (os.getenv("SITE_ADMIN_EMAIL") or "").strip().lower()
    password = os.getenv("SITE_ADMIN_PASSWORD") or ""
    if not email and not password:
        return
    email = _normalize_email(email)
    if len(password) < 10:
        raise RuntimeError("SITE_ADMIN_PASSWORD 至少需要 10 个字符")
    salt = secrets.token_bytes(16)
    now = time.time()
    with _connect() as db:
        row = db.execute(
            "SELECT id FROM users WHERE email = ? COLLATE NOCASE OR username = ? COLLATE NOCASE",
            (email, email),
        ).fetchone()
        if row:
            db.execute(
                """UPDATE users SET email = ?, role = 'admin', active = 1,
                   password_hash = ?, password_salt = ?, must_change_password = 0 WHERE id = ?""",
                (email, _hash_password(password, salt), salt.hex(), row["id"]),
            )
        else:
            db.execute(
                """INSERT INTO users
                   (id, username, email, password_hash, password_salt, role, active, must_change_password, created_at)
                   VALUES (?, ?, ?, ?, ?, 'admin', 1, 0, ?)""",
                (uuid.uuid4().hex, email, email, _hash_password(password, salt), salt.hex(), now),
            )
        db.commit()


def create_session(user_id: str) -> str:
    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    now = time.time()
    with _connect() as db:
        db.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
        db.execute("INSERT INTO sessions VALUES (?, ?, ?, ?)", (token_hash, user_id, now + SESSION_TTL_SECONDS, now))
        db.commit()
    return raw_token


def delete_session(raw_token: str | None):
    if not raw_token:
        return
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    with _connect() as db:
        db.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
        db.commit()


def user_from_session(raw_token: str | None) -> dict | None:
    if not raw_token:
        return None
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    with _connect() as db:
        row = db.execute(
            """SELECT users.* FROM sessions
               JOIN users ON users.id = sessions.user_id
               WHERE sessions.token_hash = ? AND sessions.expires_at > ? AND users.active = 1""",
            (token_hash, time.time()),
        ).fetchone()
    return _public_user(row) if row else None


def favorite_ids(user_id: str, resource_type: str) -> list[str]:
    with _connect() as db:
        rows = db.execute(
            "SELECT resource_id FROM favorites WHERE user_id = ? AND resource_type = ? ORDER BY created_at DESC",
            (user_id, resource_type),
        ).fetchall()
    return [row["resource_id"] for row in rows]


def toggle_favorite(user_id: str, resource_type: str, resource_id: str) -> bool:
    resource_id = str(resource_id or "").strip()
    if not resource_id:
        raise ValueError("收藏目标不能为空")
    with _connect() as db:
        exists = db.execute(
            "SELECT 1 FROM favorites WHERE user_id = ? AND resource_type = ? AND resource_id = ?",
            (user_id, resource_type, resource_id),
        ).fetchone()
        if exists:
            db.execute(
                "DELETE FROM favorites WHERE user_id = ? AND resource_type = ? AND resource_id = ?",
                (user_id, resource_type, resource_id),
            )
            selected = False
        else:
            db.execute(
                "INSERT INTO favorites VALUES (?, ?, ?, ?)",
                (user_id, resource_type, resource_id, time.time()),
            )
            selected = True
        db.commit()
    return selected


def record_resource_event(
    resource_type: str,
    resource_id: str,
    event_type: str,
    *,
    user_id: str | None = None,
    dedupe_key: str | None = None,
) -> bool:
    """Persist a real view/download/run event and return whether it was new."""
    resource_type = str(resource_type or "").strip().lower()
    resource_id = str(resource_id or "").strip()
    event_type = str(event_type or "").strip().lower()
    if resource_type not in {"workflow", "voice"}:
        raise ValueError("不支持的资源类型")
    if event_type not in {"view", "download", "run", "synthesis"}:
        raise ValueError("不支持的事件类型")
    if not resource_id:
        raise ValueError("资源编号不能为空")
    with _connect() as db:
        cursor = db.execute(
            """INSERT OR IGNORE INTO resource_events
               (id, resource_type, resource_id, event_type, user_id, dedupe_key, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (uuid.uuid4().hex, resource_type, resource_id, event_type, user_id, dedupe_key, time.time()),
        )
        db.commit()
    return cursor.rowcount > 0


def resource_stats(resource_type: str, resource_ids: Iterable[str]) -> dict[str, dict[str, int]]:
    """Return counts produced by this site, never copied source-site snapshots."""
    ids = list(dict.fromkeys(str(item or "").strip() for item in resource_ids if str(item or "").strip()))
    result = {
        resource_id: {"views": 0, "favorites": 0, "downloads": 0, "runs": 0}
        for resource_id in ids
    }
    if not ids:
        return result
    placeholders = ",".join("?" for _ in ids)
    with _connect() as db:
        event_rows = db.execute(
            f"""SELECT resource_id, event_type, COUNT(*) AS total
                FROM resource_events
                WHERE resource_type = ? AND resource_id IN ({placeholders})
                GROUP BY resource_id, event_type""",
            (resource_type, *ids),
        ).fetchall()
        favorite_rows = db.execute(
            f"""SELECT resource_id, COUNT(*) AS total
                FROM favorites
                WHERE resource_type = ? AND resource_id IN ({placeholders})
                GROUP BY resource_id""",
            (resource_type, *ids),
        ).fetchall()
    event_fields = {"view": "views", "download": "downloads", "run": "runs", "synthesis": "runs"}
    for row in event_rows:
        field = event_fields.get(row["event_type"])
        if field and row["resource_id"] in result:
            result[row["resource_id"]][field] = int(row["total"])
    for row in favorite_rows:
        if row["resource_id"] in result:
            result[row["resource_id"]]["favorites"] = int(row["total"])
    return result


def site_account_summary() -> dict[str, int]:
    with _connect() as db:
        users = int(db.execute("SELECT COUNT(*) FROM users WHERE active = 1").fetchone()[0])
        favorites = int(db.execute("SELECT COUNT(*) FROM favorites").fetchone()[0])
        events = {
            row["event_type"]: int(row["total"])
            for row in db.execute(
                "SELECT event_type, COUNT(*) AS total FROM resource_events GROUP BY event_type"
            ).fetchall()
        }
    return {
        "users": users,
        "favorites": favorites,
        "views": events.get("view", 0),
        "downloads": events.get("download", 0),
        "runs": events.get("run", 0) + events.get("synthesis", 0),
    }


init_site_database()
ensure_configured_admin()
