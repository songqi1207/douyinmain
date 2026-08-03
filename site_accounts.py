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

from cryptography.fernet import Fernet, InvalidToken

from workflow_jobs import DATA_DIR


DB_PATH = Path(os.getenv("SITE_DB_PATH") or DATA_DIR / "site.sqlite3").resolve()
SESSION_TTL_SECONDS = int(os.getenv("SITE_SESSION_TTL_SECONDS") or 30 * 24 * 60 * 60)
DEFAULT_GENERATION_CREDITS = int(os.getenv("DEFAULT_GENERATION_CREDITS") or 10)
LEGACY_CREDIT_POINT_RATE = max(1, int(os.getenv("LEGACY_CREDIT_POINT_RATE") or 4))
DEFAULT_POINTS_BALANCE = int(
    os.getenv("DEFAULT_POINTS_BALANCE") or 1000
)
DEFAULT_STORAGE_LIMIT_BYTES = int(os.getenv("DEFAULT_STORAGE_LIMIT_BYTES") or 5 * 1024 * 1024 * 1024)
VIDEO_STORAGE_POINT_MB = max(1, int(os.getenv("VIDEO_STORAGE_POINT_MB") or 100))
VIDEO_STORAGE_POINT_UNIT_BYTES = VIDEO_STORAGE_POINT_MB * 1024 * 1024
POINT_DENOMINATION_SCALE = max(1, int(os.getenv("POINT_DENOMINATION_SCALE") or 25))
DEFAULT_INVITER_REWARD_POINTS = int(os.getenv("DEFAULT_INVITER_REWARD_POINTS") or 250)
DEFAULT_INVITEE_REWARD_POINTS = int(os.getenv("DEFAULT_INVITEE_REWARD_POINTS") or 250)
BILLING_MARKUP_MULTIPLIER = max(2, int(os.getenv("BILLING_MARKUP_MULTIPLIER") or 2))
DEFAULT_COZE_COST_POINTS = max(0, int(os.getenv("DEFAULT_COZE_COST_POINTS") or 25))
DEFAULT_MIHE_COST_POINTS = max(0, int(os.getenv("DEFAULT_MIHE_COST_POINTS") or 0))
DEFAULT_LOCAL_MIHE_COST_POINTS = max(0, int(os.getenv("DEFAULT_LOCAL_MIHE_COST_POINTS") or 25))
USERNAME_PATTERN = re.compile(r"^[\w\u4e00-\u9fff]{3,20}$", re.UNICODE)
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class QuotaError(RuntimeError):
    pass


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
            CREATE TABLE IF NOT EXISTS user_quotas (
                user_id TEXT PRIMARY KEY,
                generation_balance INTEGER NOT NULL,
                storage_limit_bytes INTEGER NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS schema_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS generation_reservations (
                job_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                units INTEGER NOT NULL,
                state TEXT NOT NULL,
                reserved_at REAL NOT NULL,
                settled_at REAL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_generation_reservations_user
                ON generation_reservations(user_id, state, reserved_at);
            CREATE TABLE IF NOT EXISTS quota_ledger (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                job_id TEXT,
                event_type TEXT NOT NULL,
                units INTEGER NOT NULL,
                balance_after INTEGER NOT NULL,
                detail TEXT,
                created_at REAL NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_quota_ledger_user
                ON quota_ledger(user_id, created_at DESC);
            CREATE TABLE IF NOT EXISTS video_storage (
                job_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                preview_url TEXT,
                download_url TEXT,
                size_bytes INTEGER NOT NULL,
                storage_points INTEGER NOT NULL DEFAULT 0,
                state TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_video_storage_user
                ON video_storage(user_id, state, updated_at DESC);
            CREATE TABLE IF NOT EXISTS invite_rewards (
                invitee_user_id TEXT PRIMARY KEY,
                inviter_user_id TEXT NOT NULL,
                inviter_points INTEGER NOT NULL,
                invitee_points INTEGER NOT NULL,
                created_at REAL NOT NULL,
                FOREIGN KEY(invitee_user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(inviter_user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_invite_rewards_inviter
                ON invite_rewards(inviter_user_id, created_at DESC);
            CREATE TABLE IF NOT EXISTS workflow_pricing (
                workflow_code TEXT PRIMARY KEY,
                coze_cost_points INTEGER NOT NULL,
                mihe_cost_points INTEGER NOT NULL,
                updated_at REAL NOT NULL
            );
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
            CREATE TABLE IF NOT EXISTS password_vault (
                user_id TEXT PRIMARY KEY,
                ciphertext TEXT NOT NULL,
                updated_at REAL NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS password_vault_audit (
                id TEXT PRIMARY KEY,
                admin_user_id TEXT NOT NULL,
                target_user_id TEXT NOT NULL,
                action TEXT NOT NULL,
                source_ip TEXT,
                created_at REAL NOT NULL,
                FOREIGN KEY(admin_user_id) REFERENCES users(id),
                FOREIGN KEY(target_user_id) REFERENCES users(id)
            );
            CREATE INDEX IF NOT EXISTS idx_password_vault_audit_created
                ON password_vault_audit(created_at DESC);
            """
        )
        columns = {row["name"] for row in db.execute("PRAGMA table_info(users)").fetchall()}
        if "email" not in columns:
            db.execute("ALTER TABLE users ADD COLUMN email TEXT")
        if "active" not in columns:
            db.execute("ALTER TABLE users ADD COLUMN active INTEGER NOT NULL DEFAULT 1")
        if "must_change_password" not in columns:
            db.execute("ALTER TABLE users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0")
        if "invite_code" not in columns:
            db.execute("ALTER TABLE users ADD COLUMN invite_code TEXT")
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email COLLATE NOCASE) WHERE email IS NOT NULL")
        video_storage_columns = {row["name"] for row in db.execute("PRAGMA table_info(video_storage)").fetchall()}
        if "storage_points" not in video_storage_columns:
            db.execute("ALTER TABLE video_storage ADD COLUMN storage_points INTEGER NOT NULL DEFAULT 0")
        application_columns = {
            row["name"] for row in db.execute("PRAGMA table_info(registration_applications)").fetchall()
        }
        if "invite_code" not in application_columns:
            db.execute("ALTER TABLE registration_applications ADD COLUMN invite_code TEXT")
        if "inviter_user_id" not in application_columns:
            db.execute("ALTER TABLE registration_applications ADD COLUMN inviter_user_id TEXT")
        for row in db.execute("SELECT id FROM users WHERE invite_code IS NULL OR invite_code = ''").fetchall():
            db.execute(
                "UPDATE users SET invite_code = ? WHERE id = ?",
                (str(row["id"])[:8].upper(), row["id"]),
            )
        db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_invite_code ON users(invite_code COLLATE NOCASE) WHERE invite_code IS NOT NULL"
        )
        now = time.time()
        points_migration = db.execute(
            "SELECT value FROM schema_meta WHERE key = 'points_wallet_v1'"
        ).fetchone()
        if not points_migration:
            existing_quotas = int(db.execute("SELECT COUNT(*) FROM user_quotas").fetchone()[0])
            if existing_quotas:
                db.execute(
                    "UPDATE user_quotas SET generation_balance = generation_balance * ? WHERE generation_balance >= 0",
                    (LEGACY_CREDIT_POINT_RATE,),
                )
                db.execute(
                    "UPDATE generation_reservations SET units = units * ?",
                    (LEGACY_CREDIT_POINT_RATE,),
                )
                db.execute(
                    "UPDATE quota_ledger SET units = units * ?, balance_after = balance_after * ?",
                    (LEGACY_CREDIT_POINT_RATE, LEGACY_CREDIT_POINT_RATE),
                )
            db.execute(
                "INSERT INTO schema_meta (key, value, updated_at) VALUES ('points_wallet_v1', ?, ?)",
                (str(LEGACY_CREDIT_POINT_RATE), now),
            )
        default_points_migration = db.execute(
            "SELECT value FROM schema_meta WHERE key = 'points_default_1000_v1'"
        ).fetchone()
        if not default_points_migration:
            previous_default = DEFAULT_GENERATION_CREDITS * LEGACY_CREDIT_POINT_RATE
            topup_points = max(0, DEFAULT_POINTS_BALANCE - previous_default)
            if topup_points:
                ordinary_quotas = db.execute(
                    """SELECT q.user_id, q.generation_balance
                       FROM user_quotas q JOIN users u ON u.id = q.user_id
                       WHERE u.role <> 'admin' AND q.generation_balance >= 0"""
                ).fetchall()
                for row in ordinary_quotas:
                    balance_after = int(row["generation_balance"]) + topup_points
                    db.execute(
                        "UPDATE user_quotas SET generation_balance = ?, updated_at = ? WHERE user_id = ?",
                        (balance_after, now, row["user_id"]),
                    )
                    db.execute(
                        """INSERT INTO quota_ledger
                           (id, user_id, job_id, event_type, units, balance_after, detail, created_at)
                           VALUES (?, ?, NULL, 'adjust', ?, ?, ?, ?)""",
                        (
                            uuid.uuid4().hex,
                            row["user_id"],
                            topup_points,
                            balance_after,
                            "平台初始积分标准升级，自动补发积分",
                            now,
                        ),
                    )
            db.execute(
                "INSERT INTO schema_meta (key, value, updated_at) VALUES ('points_default_1000_v1', ?, ?)",
                (str(DEFAULT_POINTS_BALANCE), now),
            )
        denomination_migration = db.execute(
            "SELECT value FROM schema_meta WHERE key = 'points_denomination_25_v1'"
        ).fetchone()
        if not denomination_migration:
            db.execute(
                """UPDATE workflow_pricing
                   SET coze_cost_points = coze_cost_points * ?,
                       mihe_cost_points = mihe_cost_points * ?,
                       updated_at = ?""",
                (POINT_DENOMINATION_SCALE, POINT_DENOMINATION_SCALE, now),
            )
            reward_rows = db.execute("SELECT * FROM invite_rewards").fetchall()
            for reward in reward_rows:
                next_inviter_points = int(reward["inviter_points"]) * POINT_DENOMINATION_SCALE
                next_invitee_points = int(reward["invitee_points"]) * POINT_DENOMINATION_SCALE
                db.execute(
                    """UPDATE invite_rewards SET inviter_points = ?, invitee_points = ?
                       WHERE invitee_user_id = ?""",
                    (next_inviter_points, next_invitee_points, reward["invitee_user_id"]),
                )
                for rewarded_user_id, delta, detail in (
                    (
                        reward["inviter_user_id"],
                        next_inviter_points - int(reward["inviter_points"]),
                        "积分单位统一升级，补发历史邀请人奖励差额",
                    ),
                    (
                        reward["invitee_user_id"],
                        next_invitee_points - int(reward["invitee_points"]),
                        "积分单位统一升级，补发历史受邀用户奖励差额",
                    ),
                ):
                    if delta <= 0:
                        continue
                    quota = db.execute(
                        "SELECT generation_balance FROM user_quotas WHERE user_id = ?",
                        (rewarded_user_id,),
                    ).fetchone()
                    if not quota or int(quota["generation_balance"]) < 0:
                        continue
                    balance_after = int(quota["generation_balance"]) + delta
                    db.execute(
                        "UPDATE user_quotas SET generation_balance = ?, updated_at = ? WHERE user_id = ?",
                        (balance_after, now, rewarded_user_id),
                    )
                    db.execute(
                        """INSERT INTO quota_ledger
                           (id, user_id, job_id, event_type, units, balance_after, detail, created_at)
                           VALUES (?, ?, NULL, 'adjust', ?, ?, ?, ?)""",
                        (uuid.uuid4().hex, rewarded_user_id, delta, balance_after, detail, now),
                    )
            db.execute(
                "INSERT INTO schema_meta (key, value, updated_at) VALUES ('points_denomination_25_v1', ?, ?)",
                (str(POINT_DENOMINATION_SCALE), now),
            )
        db.execute(
            """INSERT OR IGNORE INTO user_quotas
               (user_id, generation_balance, storage_limit_bytes, created_at, updated_at)
               SELECT id,
                      CASE WHEN role = 'admin' THEN -1 ELSE ? END,
                      CASE WHEN role = 'admin' THEN -1 ELSE ? END,
                      ?, ?
               FROM users""",
            (DEFAULT_POINTS_BALANCE, DEFAULT_STORAGE_LIMIT_BYTES, now, now),
        )
        storage_points_migration = db.execute(
            "SELECT value FROM schema_meta WHERE key = 'cloud_storage_points_v1'"
        ).fetchone()
        if not storage_points_migration:
            # Existing cloud videos are included once, without charging them again on
            # every startup.  Admin storage remains unlimited and is never debited.
            rows = db.execute(
                """SELECT s.job_id, s.user_id, s.size_bytes, q.generation_balance
                   FROM video_storage s
                   JOIN users u ON u.id = s.user_id
                   JOIN user_quotas q ON q.user_id = s.user_id
                   WHERE s.state = 'active' AND s.storage_points = 0 AND u.role <> 'admin'"""
            ).fetchall()
            for row in rows:
                points = storage_points_for_bytes(int(row["size_bytes"]))
                if points <= 0:
                    continue
                balance_after = int(row["generation_balance"]) - points
                db.execute(
                    "UPDATE video_storage SET storage_points = ?, updated_at = ? WHERE job_id = ?",
                    (points, now, row["job_id"]),
                )
                db.execute(
                    "UPDATE user_quotas SET generation_balance = ?, updated_at = ? WHERE user_id = ?",
                    (balance_after, now, row["user_id"]),
                )
                db.execute(
                    """INSERT INTO quota_ledger
                       (id, user_id, job_id, event_type, units, balance_after, detail, created_at)
                       VALUES (?, ?, ?, 'storage_reserve', ?, ?, ?, ?)""",
                    (
                        uuid.uuid4().hex,
                        row["user_id"],
                        row["job_id"],
                        -points,
                        balance_after,
                        f"历史云视频保留占用 {points} 积分（每 {VIDEO_STORAGE_POINT_MB}MB 计 1 分）",
                        now,
                    ),
                )
            db.execute(
                "INSERT INTO schema_meta (key, value, updated_at) VALUES ('cloud_storage_points_v1', ?, ?)",
                (str(VIDEO_STORAGE_POINT_MB), now),
            )
        db.commit()


def _hash_password(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 240_000).hex()


def password_vault_configured() -> bool:
    return bool((os.getenv("PASSWORD_VAULT_KEY") or "").strip())


def _password_vault_cipher() -> Fernet:
    key = (os.getenv("PASSWORD_VAULT_KEY") or "").strip()
    if not key:
        raise RuntimeError("password_vault_not_configured")
    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, TypeError) as exc:
        raise RuntimeError("password_vault_key_invalid") from exc


def _store_password_vault(db: sqlite3.Connection, user_id: str, password: str) -> None:
    if not password_vault_configured():
        return
    ciphertext = _password_vault_cipher().encrypt(str(password).encode("utf-8")).decode("ascii")
    db.execute(
        """INSERT INTO password_vault (user_id, ciphertext, updated_at)
           VALUES (?, ?, ?)
           ON CONFLICT(user_id) DO UPDATE SET
             ciphertext = excluded.ciphertext,
             updated_at = excluded.updated_at""",
        (user_id, ciphertext, time.time()),
    )


def verify_user_password(user_id: str, password: str) -> bool:
    with _connect() as db:
        row = db.execute("SELECT password_hash, password_salt FROM users WHERE id = ? AND active = 1", (user_id,)).fetchone()
    if not row:
        return False
    expected = _hash_password(str(password or ""), bytes.fromhex(row["password_salt"]))
    return hmac.compare_digest(expected, row["password_hash"])


def _record_password_vault_audit(
    db: sqlite3.Connection,
    admin_user_id: str,
    target_user_id: str,
    action: str,
    source_ip: str = "",
) -> None:
    db.execute(
        """INSERT INTO password_vault_audit
           (id, admin_user_id, target_user_id, action, source_ip, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            uuid.uuid4().hex,
            admin_user_id,
            target_user_id,
            str(action)[:40],
            str(source_ip or "")[:80],
            time.time(),
        ),
    )


def reveal_user_password(admin_user_id: str, target_user_id: str, source_ip: str = "") -> str:
    cipher = _password_vault_cipher()
    with _connect() as db:
        target = db.execute("SELECT id, role FROM users WHERE id = ? AND active = 1", (target_user_id,)).fetchone()
        if not target:
            raise KeyError("user_not_found")
        if target["role"] == "admin":
            raise PermissionError("admin_password_not_revealable")
        row = db.execute("SELECT ciphertext FROM password_vault WHERE user_id = ?", (target_user_id,)).fetchone()
        if not row:
            raise KeyError("password_not_recoverable")
        try:
            password = cipher.decrypt(row["ciphertext"].encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeError, ValueError) as exc:
            raise RuntimeError("password_vault_decrypt_failed") from exc
        _record_password_vault_audit(db, admin_user_id, target_user_id, "reveal", source_ip)
        db.commit()
    return password


def reset_user_password_for_admin(
    admin_user_id: str,
    target_user_id: str,
    new_password: str = "",
    source_ip: str = "",
) -> str:
    # Refuse to rotate a password unless the recoverable copy can be stored.
    # This prevents an apparently successful reset from creating another
    # password that the administrator cannot retrieve later.
    _password_vault_cipher()
    password = str(new_password or "")
    if not password:
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@#$%"
        password = "".join(secrets.choice(alphabet) for _ in range(14))
    if len(password) < 8 or len(password) > 128:
        raise ValueError("new_password_length")
    salt = secrets.token_bytes(16)
    with _connect() as db:
        target = db.execute("SELECT id, role FROM users WHERE id = ? AND active = 1", (target_user_id,)).fetchone()
        if not target:
            raise KeyError("user_not_found")
        if target["role"] == "admin":
            raise PermissionError("admin_password_not_resettable_here")
        db.execute(
            """UPDATE users SET password_hash = ?, password_salt = ?, must_change_password = 0
               WHERE id = ?""",
            (_hash_password(password, salt), salt.hex(), target_user_id),
        )
        _store_password_vault(db, target_user_id, password)
        db.execute("DELETE FROM sessions WHERE user_id = ?", (target_user_id,))
        _record_password_vault_audit(db, admin_user_id, target_user_id, "reset", source_ip)
        db.commit()
    return password


def _public_user(row) -> dict:
    return {
        "id": row["id"],
        "username": row["username"],
        "email": row["email"],
        "role": row["role"],
        "must_change_password": bool(row["must_change_password"]),
        "invite_code": row["invite_code"] if "invite_code" in row.keys() else None,
    }


def active_admin_user() -> dict | None:
    """Return the single configured active administrator, if available."""
    with _connect() as db:
        row = db.execute(
            """SELECT * FROM users
               WHERE role = 'admin' AND active = 1
               ORDER BY created_at ASC LIMIT 1"""
        ).fetchone()
    return _public_user(row) if row else None


def _ensure_quota_row(db: sqlite3.Connection, user_id: str):
    user = db.execute(
        "SELECT id, username, email, role, active, invite_code FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    if not user:
        raise KeyError("user_not_found")
    now = time.time()
    unlimited = user["role"] == "admin"
    db.execute(
        """INSERT OR IGNORE INTO user_quotas
           (user_id, generation_balance, storage_limit_bytes, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?)""",
        (
            user_id,
            -1 if unlimited else DEFAULT_POINTS_BALANCE,
            -1 if unlimited else DEFAULT_STORAGE_LIMIT_BYTES,
            now,
            now,
        ),
    )
    if unlimited:
        db.execute(
            "UPDATE user_quotas SET generation_balance = -1, storage_limit_bytes = -1, updated_at = ? WHERE user_id = ?",
            (now, user_id),
        )
    quota = db.execute("SELECT * FROM user_quotas WHERE user_id = ?", (user_id,)).fetchone()
    return user, quota


def _quota_snapshot(db: sqlite3.Connection, user_id: str, *, include_ledger: bool = True) -> dict:
    user, quota = _ensure_quota_row(db, user_id)
    storage_used = int(
        db.execute(
            "SELECT COALESCE(SUM(size_bytes), 0) FROM video_storage WHERE user_id = ? AND state = 'active'",
            (user_id,),
        ).fetchone()[0]
    )
    reserved = int(
        db.execute(
            "SELECT COALESCE(SUM(units), 0) FROM generation_reservations WHERE user_id = ? AND state = 'reserved'",
            (user_id,),
        ).fetchone()[0]
    )
    storage_points_reserved = int(
        db.execute(
            "SELECT COALESCE(SUM(storage_points), 0) FROM video_storage WHERE user_id = ? AND state = 'active'",
            (user_id,),
        ).fetchone()[0]
    )
    consumed = int(
        db.execute(
            "SELECT COALESCE(SUM(units), 0) FROM generation_reservations WHERE user_id = ? AND state = 'consumed'",
            (user_id,),
        ).fetchone()[0]
    )
    unlimited = user["role"] == "admin"
    storage_limit = int(quota["storage_limit_bytes"])
    invited = db.execute(
        "SELECT COUNT(*), COALESCE(SUM(inviter_points), 0) FROM invite_rewards WHERE inviter_user_id = ?",
        (user_id,),
    ).fetchone()
    balance = -1 if unlimited else int(quota["generation_balance"])
    result = {
        "user": {
            "id": user["id"],
            "username": user["username"],
            "email": user["email"],
            "role": user["role"],
            "active": bool(user["active"]),
        },
        "unlimited": unlimited,
        "generation_balance": balance,
        "generation_reserved": reserved,
        "generation_consumed": consumed,
        "points_balance": balance,
        "points_reserved": reserved,
        "storage_points_reserved": 0 if unlimited else storage_points_reserved,
        "points_reserved_total": reserved if unlimited else reserved + storage_points_reserved,
        "points_consumed": consumed,
        "storage_used_bytes": storage_used,
        "storage_limit_bytes": -1 if unlimited else storage_limit,
        "storage_available_bytes": -1 if unlimited else max(0, storage_limit - storage_used),
        "can_generate": unlimited or (
            int(quota["generation_balance"]) > 0 and storage_used < storage_limit
        ),
        "invite": {
            "code": user["invite_code"],
            "invited_count": int(invited[0]),
            "rewarded_points": int(invited[1]),
            "inviter_reward_points": DEFAULT_INVITER_REWARD_POINTS,
            "invitee_reward_points": DEFAULT_INVITEE_REWARD_POINTS,
        },
        "billing_multiplier": BILLING_MARKUP_MULTIPLIER,
    }
    if include_ledger:
        rows = db.execute(
            """SELECT id, job_id, event_type, units, balance_after, detail, created_at
               FROM quota_ledger WHERE user_id = ? ORDER BY created_at DESC LIMIT 50""",
            (user_id,),
        ).fetchall()
        result["ledger"] = [dict(row) for row in rows]
    return result


def quota_snapshot(user_id: str) -> dict:
    with _connect() as db:
        result = _quota_snapshot(db, user_id)
        db.commit()
    return result


def list_user_quotas() -> list[dict]:
    with _connect() as db:
        user_ids = [
            row["id"]
            for row in db.execute(
                "SELECT id FROM users WHERE active = 1 ORDER BY role DESC, created_at ASC"
            ).fetchall()
        ]
        result = [_quota_snapshot(db, user_id, include_ledger=False) for user_id in user_ids]
        db.commit()
    return result


def _default_workflow_costs(workflow_code: str) -> tuple[int, int]:
    code = str(workflow_code or "").strip().upper()
    if code == "DRAFT_KEY_EXPORT":
        return 0, 0
    mihe_points = DEFAULT_LOCAL_MIHE_COST_POINTS if code in {"OWN01", "OWN02", "OWN03"} else DEFAULT_MIHE_COST_POINTS
    return DEFAULT_COZE_COST_POINTS, mihe_points


def workflow_pricing_snapshot(workflow_code: str) -> dict:
    code = str(workflow_code or "").strip().upper()
    if not code:
        raise ValueError("workflow_code_required")
    default_coze, default_mihe = _default_workflow_costs(code)
    now = time.time()
    with _connect() as db:
        db.execute(
            """INSERT OR IGNORE INTO workflow_pricing
               (workflow_code, coze_cost_points, mihe_cost_points, updated_at)
               VALUES (?, ?, ?, ?)""",
            (code, default_coze, default_mihe, now),
        )
        row = db.execute(
            "SELECT * FROM workflow_pricing WHERE workflow_code = ?", (code,)
        ).fetchone()
        db.commit()
    coze_points = max(0, int(row["coze_cost_points"]))
    mihe_points = max(0, int(row["mihe_cost_points"]))
    provider_cost_points = coze_points + mihe_points
    return {
        "workflow_code": code,
        "coze_cost_points": coze_points,
        "mihe_cost_points": mihe_points,
        "provider_cost_points": provider_cost_points,
        "billing_multiplier": BILLING_MARKUP_MULTIPLIER,
        "price_points": provider_cost_points * BILLING_MARKUP_MULTIPLIER,
        "updated_at": float(row["updated_at"]),
    }


def update_workflow_pricing(
    workflow_code: str,
    *,
    coze_cost_points: int,
    mihe_cost_points: int,
) -> dict:
    code = str(workflow_code or "").strip().upper()
    coze_points = int(coze_cost_points)
    mihe_points = int(mihe_cost_points)
    if not code:
        raise ValueError("workflow_code_required")
    if not 0 <= coze_points <= 1_000_000 or not 0 <= mihe_points <= 1_000_000:
        raise ValueError("invalid_workflow_cost")
    with _connect() as db:
        db.execute(
            """INSERT INTO workflow_pricing
               (workflow_code, coze_cost_points, mihe_cost_points, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(workflow_code) DO UPDATE SET
                 coze_cost_points = excluded.coze_cost_points,
                 mihe_cost_points = excluded.mihe_cost_points,
                 updated_at = excluded.updated_at""",
            (code, coze_points, mihe_points, time.time()),
        )
        db.commit()
    return workflow_pricing_snapshot(code)


def reserve_generation(user_id: str, job_id: str, units: int = 1) -> dict:
    units = max(0, int(units))
    now = time.time()
    with _connect() as db:
        db.execute("BEGIN IMMEDIATE")
        user, quota = _ensure_quota_row(db, user_id)
        if user["role"] == "admin" or units == 0:
            db.commit()
            return _quota_snapshot(db, user_id, include_ledger=False)
        existing = db.execute(
            "SELECT state FROM generation_reservations WHERE job_id = ?",
            (job_id,),
        ).fetchone()
        if existing:
            db.commit()
            return _quota_snapshot(db, user_id, include_ledger=False)
        storage_used = int(
            db.execute(
                "SELECT COALESCE(SUM(size_bytes), 0) FROM video_storage WHERE user_id = ? AND state = 'active'",
                (user_id,),
            ).fetchone()[0]
        )
        if storage_used >= int(quota["storage_limit_bytes"]):
            db.rollback()
            raise QuotaError("storage_quota_exhausted")
        balance = int(quota["generation_balance"])
        if balance < units:
            db.rollback()
            raise QuotaError("generation_quota_exhausted")
        balance_after = balance - units
        db.execute(
            "UPDATE user_quotas SET generation_balance = ?, updated_at = ? WHERE user_id = ?",
            (balance_after, now, user_id),
        )
        db.execute(
            """INSERT INTO generation_reservations
               (job_id, user_id, units, state, reserved_at, settled_at)
               VALUES (?, ?, ?, 'reserved', ?, NULL)""",
            (job_id, user_id, units, now),
        )
        db.execute(
            """INSERT INTO quota_ledger
               (id, user_id, job_id, event_type, units, balance_after, detail, created_at)
               VALUES (?, ?, ?, 'reserve', ?, ?, ?, ?)""",
            (uuid.uuid4().hex, user_id, job_id, -units, balance_after, "生成任务已创建，暂时冻结积分", now),
        )
        db.commit()
        return _quota_snapshot(db, user_id, include_ledger=False)


def settle_generation_reservation(job_id: str, succeeded: bool) -> bool:
    now = time.time()
    with _connect() as db:
        db.execute("BEGIN IMMEDIATE")
        reservation = db.execute(
            "SELECT * FROM generation_reservations WHERE job_id = ?",
            (job_id,),
        ).fetchone()
        if not reservation or reservation["state"] != "reserved":
            db.commit()
            return False
        user_id = reservation["user_id"]
        units = int(reservation["units"])
        _, quota = _ensure_quota_row(db, user_id)
        balance = int(quota["generation_balance"])
        if succeeded:
            state = "consumed"
            event_type = "consume"
            ledger_units = 0
            detail = "视频生成成功，冻结积分已确认消费"
            balance_after = balance
        else:
            state = "refunded"
            event_type = "refund"
            ledger_units = units
            detail = "任务失败，冻结积分已自动退回"
            balance_after = balance + units
            db.execute(
                "UPDATE user_quotas SET generation_balance = ?, updated_at = ? WHERE user_id = ?",
                (balance_after, now, user_id),
            )
        db.execute(
            "UPDATE generation_reservations SET state = ?, settled_at = ? WHERE job_id = ?",
            (state, now, job_id),
        )
        db.execute(
            """INSERT INTO quota_ledger
               (id, user_id, job_id, event_type, units, balance_after, detail, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (uuid.uuid4().hex, user_id, job_id, event_type, ledger_units, balance_after, detail, now),
        )
        db.commit()
    return True


def adjust_user_quota(
    user_id: str,
    *,
    generation_delta: int = 0,
    storage_limit_bytes: int | None = None,
    detail: str = "管理员调整额度",
) -> dict:
    now = time.time()
    with _connect() as db:
        db.execute("BEGIN IMMEDIATE")
        user, quota = _ensure_quota_row(db, user_id)
        if user["role"] == "admin":
            db.commit()
            return _quota_snapshot(db, user_id)
        balance_after = max(0, int(quota["generation_balance"]) + int(generation_delta))
        next_storage_limit = int(quota["storage_limit_bytes"])
        if storage_limit_bytes is not None:
            next_storage_limit = max(0, int(storage_limit_bytes))
        db.execute(
            """UPDATE user_quotas SET generation_balance = ?, storage_limit_bytes = ?, updated_at = ?
               WHERE user_id = ?""",
            (balance_after, next_storage_limit, now, user_id),
        )
        if int(generation_delta):
            db.execute(
                """INSERT INTO quota_ledger
                   (id, user_id, job_id, event_type, units, balance_after, detail, created_at)
                   VALUES (?, ?, NULL, 'adjust', ?, ?, ?, ?)""",
                (uuid.uuid4().hex, user_id, int(generation_delta), balance_after, str(detail)[:200], now),
            )
        db.commit()
        return _quota_snapshot(db, user_id)


def record_video_storage(
    job_id: str,
    user_id: str,
    preview_url: str,
    download_url: str,
    size_bytes: int,
    *,
    billable_bytes: int | None = None,
) -> None:
    now = time.time()
    with _connect() as db:
        db.execute("BEGIN IMMEDIATE")
        user, quota = _ensure_quota_row(db, user_id)
        existing = db.execute(
            "SELECT storage_points FROM video_storage WHERE job_id = ? AND user_id = ?",
            (job_id, user_id),
        ).fetchone()
        old_points = int(existing["storage_points"]) if existing else 0
        required_points = 0 if user["role"] == "admin" else storage_points_for_bytes(
            int(size_bytes if billable_bytes is None else billable_bytes)
        )
        delta = required_points - old_points
        balance_after = int(quota["generation_balance"])
        if delta:
            balance_after -= delta
            db.execute(
                "UPDATE user_quotas SET generation_balance = ?, updated_at = ? WHERE user_id = ?",
                (balance_after, now, user_id),
            )
            event_type = "storage_reserve" if delta > 0 else "storage_release"
            detail = (
                f"云视频保留占用 {delta} 积分（每 {VIDEO_STORAGE_POINT_MB}MB 计 1 分，删除后释放）"
                if delta > 0
                else f"云视频大小更新，释放 {-delta} 积分"
            )
            db.execute(
                """INSERT INTO quota_ledger
                   (id, user_id, job_id, event_type, units, balance_after, detail, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (uuid.uuid4().hex, user_id, job_id, event_type, -delta, balance_after, detail, now),
            )
        db.execute(
            """INSERT INTO video_storage
               (job_id, user_id, preview_url, download_url, size_bytes, storage_points, state, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?)
               ON CONFLICT(job_id) DO UPDATE SET
                 user_id = excluded.user_id,
                 preview_url = excluded.preview_url,
                 download_url = excluded.download_url,
                 size_bytes = excluded.size_bytes,
                 storage_points = excluded.storage_points,
                 state = 'active',
                 updated_at = excluded.updated_at""",
            (
                job_id,
                user_id,
                str(preview_url or "")[:2000],
                str(download_url or "")[:2000],
                max(0, int(size_bytes)),
                required_points,
                now,
                now,
            ),
        )
        db.commit()


def mark_video_storage_deleted(job_id: str, user_id: str) -> int:
    now = time.time()
    with _connect() as db:
        row = db.execute(
            "SELECT size_bytes, storage_points FROM video_storage WHERE job_id = ? AND user_id = ? AND state = 'active'",
            (job_id, user_id),
        ).fetchone()
        if not row:
            return 0
        storage_points = int(row["storage_points"])
        if storage_points:
            quota = db.execute(
                "SELECT generation_balance FROM user_quotas WHERE user_id = ?", (user_id,)
            ).fetchone()
            balance_after = int(quota["generation_balance"]) + storage_points
            db.execute(
                "UPDATE user_quotas SET generation_balance = ?, updated_at = ? WHERE user_id = ?",
                (balance_after, now, user_id),
            )
            db.execute(
                """INSERT INTO quota_ledger
                   (id, user_id, job_id, event_type, units, balance_after, detail, created_at)
                   VALUES (?, ?, ?, 'storage_release', ?, ?, ?, ?)""",
                (
                    uuid.uuid4().hex,
                    user_id,
                    job_id,
                    storage_points,
                    balance_after,
                    f"删除云视频，释放 {storage_points} 积分",
                    now,
                ),
            )
        db.execute(
            "UPDATE video_storage SET state = 'deleted', size_bytes = 0, storage_points = 0, updated_at = ? WHERE job_id = ?",
            (now, job_id),
        )
        db.commit()
    return int(row["size_bytes"])


def storage_points_for_bytes(size_bytes: int) -> int:
    """Return the non-recurring cloud retention deposit for a video."""
    size = max(0, int(size_bytes))
    if size <= 0:
        return 0
    return max(1, (size + VIDEO_STORAGE_POINT_UNIT_BYTES - 1) // VIDEO_STORAGE_POINT_UNIT_BYTES)


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
                   (id, username, email, password_hash, password_salt, role, active,
                    must_change_password, invite_code, created_at)
                   VALUES (?, ?, NULL, ?, ?, 'user', 1, 0, ?, ?)""",
                (
                    user_id,
                    username,
                    _hash_password(password, salt),
                    salt.hex(),
                    user_id[:8].upper(),
                    time.time(),
                ),
            )
            _store_password_vault(db, user_id, password)
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
        "invite_code": row["invite_code"] if "invite_code" in row.keys() else None,
    }


def submit_registration_application(email: str, invite_code: str = "") -> dict:
    email = _normalize_email(email)
    normalized_invite_code = str(invite_code or "").strip().upper()
    now = time.time()
    with _connect() as db:
        inviter = None
        if normalized_invite_code:
            inviter = db.execute(
                "SELECT id FROM users WHERE invite_code = ? COLLATE NOCASE AND active = 1",
                (normalized_invite_code,),
            ).fetchone()
            if not inviter:
                raise ValueError("邀请码不存在或已失效")
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
                       reviewed_by = NULL, reviewed_at = NULL, invite_code = ?,
                       inviter_user_id = ?, updated_at = ? WHERE id = ?""",
                (normalized_invite_code or None, inviter["id"] if inviter else None, now, existing["id"]),
            )
            application_id = existing["id"]
        else:
            application_id = uuid.uuid4().hex
            db.execute(
                """INSERT INTO registration_applications
                   (id, email, status, delivery_status, delivery_error, reviewed_by, reviewed_at,
                    created_at, updated_at, invite_code, inviter_user_id)
                   VALUES (?, ?, 'pending', 'not_sent', NULL, NULL, NULL, ?, ?, ?, ?)""",
                (
                    application_id,
                    email,
                    now,
                    now,
                    normalized_invite_code or None,
                    inviter["id"] if inviter else None,
                ),
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
            _store_password_vault(db, existing_user["id"], temporary_password)
        else:
            user_id = uuid.uuid4().hex
            db.execute(
                """INSERT INTO users
                   (id, username, email, password_hash, password_salt, role, active,
                    must_change_password, invite_code, created_at)
                   VALUES (?, ?, ?, ?, ?, 'user', 0, 0, ?, ?)""",
                (
                    user_id,
                    application["email"],
                    application["email"],
                    _hash_password(temporary_password, salt),
                    salt.hex(),
                    user_id[:8].upper(),
                    now,
                ),
            )
            _store_password_vault(db, user_id, temporary_password)
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
            """UPDATE users SET active = 1, must_change_password = 1
               WHERE email = ? COLLATE NOCASE""",
            (application["email"],),
        )
        db.execute(
            """UPDATE registration_applications SET status = 'approved', delivery_status = 'sent',
               delivery_error = NULL, updated_at = ? WHERE id = ?""",
            (now, application_id),
        )
        invitee = db.execute(
            "SELECT id, role FROM users WHERE email = ? COLLATE NOCASE",
            (application["email"],),
        ).fetchone()
        inviter_user_id = application["inviter_user_id"]
        if invitee and inviter_user_id and inviter_user_id != invitee["id"]:
            inviter = db.execute(
                "SELECT id, role FROM users WHERE id = ? AND active = 1",
                (inviter_user_id,),
            ).fetchone()
            if inviter:
                inviter_points = 0 if inviter["role"] == "admin" else DEFAULT_INVITER_REWARD_POINTS
                invitee_points = 0 if invitee["role"] == "admin" else DEFAULT_INVITEE_REWARD_POINTS
                inserted = db.execute(
                    """INSERT OR IGNORE INTO invite_rewards
                       (invitee_user_id, inviter_user_id, inviter_points, invitee_points, created_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (invitee["id"], inviter["id"], inviter_points, invitee_points, now),
                )
                if inserted.rowcount:
                    for rewarded_user_id, points, event_type, detail in (
                        (inviter["id"], inviter_points, "invite_reward", "邀请的新用户已通过审核，奖励积分到账"),
                        (invitee["id"], invitee_points, "welcome_bonus", "使用邀请码注册并通过审核，奖励积分到账"),
                    ):
                        if points <= 0:
                            continue
                        _, rewarded_quota = _ensure_quota_row(db, rewarded_user_id)
                        balance_after = int(rewarded_quota["generation_balance"]) + points
                        db.execute(
                            "UPDATE user_quotas SET generation_balance = ?, updated_at = ? WHERE user_id = ?",
                            (balance_after, now, rewarded_user_id),
                        )
                        db.execute(
                            """INSERT INTO quota_ledger
                               (id, user_id, job_id, event_type, units, balance_after, detail, created_at)
                               VALUES (?, ?, NULL, ?, ?, ?, ?, ?)""",
                            (uuid.uuid4().hex, rewarded_user_id, event_type, points, balance_after, detail, now),
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
    if not email:
        return
    email = _normalize_email(email)
    if password and len(password) < 10:
        raise RuntimeError("SITE_ADMIN_PASSWORD 至少需要 10 个字符")
    now = time.time()
    with _connect() as db:
        db.execute(
            """UPDATE users SET role = 'user'
               WHERE role = 'admin' AND (email IS NULL OR email <> ? COLLATE NOCASE)""",
            (email,),
        )
        row = db.execute(
            "SELECT id FROM users WHERE email = ? COLLATE NOCASE OR username = ? COLLATE NOCASE",
            (email, email),
        ).fetchone()
        if row:
            if password:
                salt = secrets.token_bytes(16)
                db.execute(
                    """UPDATE users SET email = ?, role = 'admin', active = 1,
                       password_hash = ?, password_salt = ?, must_change_password = 0 WHERE id = ?""",
                    (email, _hash_password(password, salt), salt.hex(), row["id"]),
                )
            else:
                db.execute(
                    "UPDATE users SET email = ?, role = 'admin', active = 1 WHERE id = ?",
                    (email, row["id"]),
                )
        else:
            if not password:
                raise RuntimeError("管理员账号不存在，首次创建时必须配置 SITE_ADMIN_PASSWORD")
            salt = secrets.token_bytes(16)
            user_id = uuid.uuid4().hex
            db.execute(
                """INSERT INTO users
                   (id, username, email, password_hash, password_salt, role, active,
                    must_change_password, invite_code, created_at)
                   VALUES (?, ?, ?, ?, ?, 'admin', 1, 0, ?, ?)""",
                (user_id, email, email, _hash_password(password, salt), salt.hex(), user_id[:8].upper(), now),
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


def change_user_password(user_id: str, current_password: str, new_password: str) -> dict:
    current_password = str(current_password or "")
    new_password = str(new_password or "")
    if len(new_password) < 8 or len(new_password) > 128:
        raise ValueError("new_password_length")
    if hmac.compare_digest(current_password, new_password):
        raise ValueError("password_reuse")

    with _connect() as db:
        row = db.execute(
            "SELECT * FROM users WHERE id = ? AND active = 1",
            (user_id,),
        ).fetchone()
        if not row:
            raise KeyError("user_not_found")
        expected = _hash_password(
            current_password,
            bytes.fromhex(row["password_salt"]),
        )
        if not hmac.compare_digest(expected, row["password_hash"]):
            raise ValueError("invalid_current_password")

        salt = secrets.token_bytes(16)
        db.execute(
            """UPDATE users
               SET password_hash = ?, password_salt = ?, must_change_password = 0
               WHERE id = ?""",
            (_hash_password(new_password, salt), salt.hex(), user_id),
        )
        if row["role"] != "admin":
            _store_password_vault(db, user_id, new_password)
        db.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        db.commit()
        updated = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return _public_user(updated)


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
