from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator


UTC = timezone.utc


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso_utc(value: datetime | None = None) -> str:
    return (value or utc_now()).astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_iso_utc(value: str | None) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


class AuthRepository:
    def __init__(self, database_path: str | Path):
        self.path = Path(database_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.ensure_schema()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(self.path, timeout=10)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        con.execute("PRAGMA busy_timeout = 5000")
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def ensure_schema(self) -> None:
        with self.connection() as con:
            con.execute("PRAGMA journal_mode = WAL")
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    public_id TEXT NOT NULL UNIQUE,
                    full_name TEXT NOT NULL,
                    email_normalized TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    profile_type TEXT NOT NULL,
                    institution TEXT NOT NULL DEFAULT '',
                    course_area TEXT NOT NULL DEFAULT '',
                    purpose TEXT NOT NULL DEFAULT '',
                    access_status TEXT NOT NULL,
                    email_verified_at TEXT,
                    created_at TEXT NOT NULL,
                    requested_at TEXT NOT NULL,
                    approved_at TEXT,
                    rejected_at TEXT,
                    suspended_at TEXT,
                    disabled_at TEXT,
                    last_login_at TEXT,
                    privacy_accepted_at TEXT NOT NULL,
                    privacy_version TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_auth_users_status ON users(access_status);
                CREATE INDEX IF NOT EXISTS idx_auth_users_created ON users(created_at);

                CREATE TABLE IF NOT EXISTS auth_challenges (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    purpose TEXT NOT NULL,
                    token_hash TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    max_attempts INTEGER NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    used_at TEXT,
                    invalidated_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_auth_challenges_user_purpose
                    ON auth_challenges(user_id, purpose, created_at DESC);

                CREATE TABLE IF NOT EXISTS auth_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_token_hash TEXT NOT NULL UNIQUE,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    revoked_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_auth_sessions_user ON auth_sessions(user_id, revoked_at, expires_at);

                CREATE TABLE IF NOT EXISTS auth_audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                    action TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_auth_audit_user ON auth_audit_log(user_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS auth_notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    notification_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    sent_at TEXT,
                    error_message TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_auth_notifications_user
                    ON auth_notifications(user_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS auth_rate_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scope TEXT NOT NULL,
                    subject_hash TEXT NOT NULL,
                    occurred_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_auth_rate_scope_subject_time
                    ON auth_rate_events(scope, subject_hash, occurred_at);
                """
            )

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        return dict(row) if row is not None else None

    def create_user(self, **fields: Any) -> dict[str, Any]:
        now = iso_utc()
        with self.connection() as con:
            cur = con.execute(
                """
                INSERT INTO users (
                    public_id, full_name, email_normalized, password_hash,
                    profile_type, institution, course_area, purpose, access_status,
                    created_at, requested_at, privacy_accepted_at, privacy_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fields["public_id"], fields["full_name"], fields["email_normalized"], fields["password_hash"],
                    fields["profile_type"], fields.get("institution", ""), fields.get("course_area", ""),
                    fields.get("purpose", ""), fields.get("access_status", "email_pending"),
                    now, now, now, fields["privacy_version"],
                ),
            )
            row = con.execute("SELECT * FROM users WHERE id = ?", (cur.lastrowid,)).fetchone()
            return dict(row)

    def get_user_by_email(self, email_normalized: str) -> dict[str, Any] | None:
        with self.connection() as con:
            return self._row(con.execute("SELECT * FROM users WHERE email_normalized = ?", (email_normalized,)).fetchone())

    def get_user_by_public_id(self, public_id: str) -> dict[str, Any] | None:
        with self.connection() as con:
            return self._row(con.execute("SELECT * FROM users WHERE public_id = ?", (public_id,)).fetchone())

    def get_user_by_id(self, user_id: int) -> dict[str, Any] | None:
        with self.connection() as con:
            return self._row(con.execute("SELECT * FROM users WHERE id = ?", (int(user_id),)).fetchone())

    def set_email_verified(self, user_id: int) -> dict[str, Any]:
        now = iso_utc()
        with self.connection() as con:
            con.execute(
                "UPDATE users SET email_verified_at = ?, access_status = 'pending_approval', requested_at = ? WHERE id = ?",
                (now, now, int(user_id)),
            )
            return dict(con.execute("SELECT * FROM users WHERE id = ?", (int(user_id),)).fetchone())

    def set_password(self, user_id: int, password_hash: str) -> None:
        with self.connection() as con:
            con.execute("UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, int(user_id)))

    def mark_login(self, user_id: int) -> None:
        with self.connection() as con:
            con.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (iso_utc(), int(user_id)))

    def set_status(self, user_id: int, status: str) -> dict[str, Any]:
        status = str(status)
        now = iso_utc()
        timestamp_column = {
            "active": "approved_at",
            "rejected": "rejected_at",
            "suspended": "suspended_at",
            "disabled": "disabled_at",
        }.get(status)
        with self.connection() as con:
            if timestamp_column:
                con.execute(
                    f"UPDATE users SET access_status = ?, {timestamp_column} = ? WHERE id = ?",
                    (status, now, int(user_id)),
                )
            else:
                con.execute("UPDATE users SET access_status = ? WHERE id = ?", (status, int(user_id)))
            return dict(con.execute("SELECT * FROM users WHERE id = ?", (int(user_id),)).fetchone())

    def invalidate_challenges(self, user_id: int, purpose: str) -> None:
        with self.connection() as con:
            con.execute(
                "UPDATE auth_challenges SET invalidated_at = ? WHERE user_id = ? AND purpose = ? AND used_at IS NULL AND invalidated_at IS NULL",
                (iso_utc(), int(user_id), str(purpose)),
            )

    def create_challenge(self, *, user_id: int, purpose: str, token_hash: str, ttl_seconds: int, max_attempts: int) -> dict[str, Any]:
        now = utc_now()
        expires = now + timedelta(seconds=max(60, int(ttl_seconds)))
        with self.connection() as con:
            cur = con.execute(
                """
                INSERT INTO auth_challenges
                    (user_id, purpose, token_hash, expires_at, max_attempts, attempts, created_at)
                VALUES (?, ?, ?, ?, ?, 0, ?)
                """,
                (int(user_id), str(purpose), str(token_hash), iso_utc(expires), int(max_attempts), iso_utc(now)),
            )
            return dict(con.execute("SELECT * FROM auth_challenges WHERE id = ?", (cur.lastrowid,)).fetchone())

    def latest_challenge(self, user_id: int, purpose: str) -> dict[str, Any] | None:
        with self.connection() as con:
            row = con.execute(
                """
                SELECT * FROM auth_challenges
                WHERE user_id = ? AND purpose = ? AND used_at IS NULL AND invalidated_at IS NULL
                ORDER BY id DESC LIMIT 1
                """,
                (int(user_id), str(purpose)),
            ).fetchone()
            return self._row(row)

    def increment_challenge_attempt(self, challenge_id: int) -> dict[str, Any]:
        with self.connection() as con:
            con.execute("UPDATE auth_challenges SET attempts = attempts + 1 WHERE id = ?", (int(challenge_id),))
            return dict(con.execute("SELECT * FROM auth_challenges WHERE id = ?", (int(challenge_id),)).fetchone())

    def consume_challenge(self, challenge_id: int) -> bool:
        """Consome uma vez, de forma atômica, mesmo sob requisições concorrentes."""
        now = iso_utc()
        with self.connection() as con:
            cur = con.execute(
                """
                UPDATE auth_challenges
                SET used_at = ?
                WHERE id = ?
                  AND used_at IS NULL
                  AND invalidated_at IS NULL
                  AND attempts < max_attempts
                  AND expires_at > ?
                """,
                (now, int(challenge_id), now),
            )
            return cur.rowcount == 1

    def invalidate_challenge(self, challenge_id: int) -> None:
        with self.connection() as con:
            con.execute("UPDATE auth_challenges SET invalidated_at = ? WHERE id = ? AND invalidated_at IS NULL", (iso_utc(), int(challenge_id)))

    def create_session(self, *, token_hash: str, user_id: int, ttl_seconds: int) -> dict[str, Any]:
        now = utc_now()
        expires = now + timedelta(seconds=max(300, int(ttl_seconds)))
        with self.connection() as con:
            cur = con.execute(
                """
                INSERT INTO auth_sessions (session_token_hash, user_id, created_at, last_seen_at, expires_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (str(token_hash), int(user_id), iso_utc(now), iso_utc(now), iso_utc(expires)),
            )
            return dict(con.execute("SELECT * FROM auth_sessions WHERE id = ?", (cur.lastrowid,)).fetchone())

    def get_session_user(self, token_hash: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
        now = iso_utc()
        with self.connection() as con:
            row = con.execute(
                """
                SELECT s.id AS session_id, s.session_token_hash, s.user_id AS session_user_id,
                       s.created_at AS session_created_at, s.last_seen_at, s.expires_at, s.revoked_at,
                       u.*
                FROM auth_sessions s
                JOIN users u ON u.id = s.user_id
                WHERE s.session_token_hash = ? AND s.revoked_at IS NULL AND s.expires_at > ?
                LIMIT 1
                """,
                (str(token_hash), now),
            ).fetchone()
            if row is None:
                return None
            data = dict(row)
            session_data = {
                "id": data.pop("session_id"),
                "session_token_hash": data.pop("session_token_hash"),
                "user_id": data.pop("session_user_id"),
                "created_at": data.pop("session_created_at"),
                "last_seen_at": data.pop("last_seen_at"),
                "expires_at": data.pop("expires_at"),
                "revoked_at": data.pop("revoked_at"),
            }
            return session_data, data

    def touch_session(self, session_id: int) -> None:
        with self.connection() as con:
            con.execute("UPDATE auth_sessions SET last_seen_at = ? WHERE id = ?", (iso_utc(), int(session_id)))

    def revoke_session(self, token_hash: str) -> None:
        if not token_hash:
            return
        with self.connection() as con:
            con.execute(
                "UPDATE auth_sessions SET revoked_at = COALESCE(revoked_at, ?) WHERE session_token_hash = ?",
                (iso_utc(), str(token_hash)),
            )

    def revoke_user_sessions(self, user_id: int) -> None:
        with self.connection() as con:
            con.execute(
                "UPDATE auth_sessions SET revoked_at = COALESCE(revoked_at, ?) WHERE user_id = ? AND revoked_at IS NULL",
                (iso_utc(), int(user_id)),
            )

    def audit(self, *, user_id: int | None, action: str, metadata: dict[str, Any] | None = None) -> None:
        safe_metadata = metadata or {}
        with self.connection() as con:
            con.execute(
                "INSERT INTO auth_audit_log (user_id, action, created_at, metadata_json) VALUES (?, ?, ?, ?)",
                (int(user_id) if user_id is not None else None, str(action), iso_utc(), json.dumps(safe_metadata, ensure_ascii=False, separators=(",", ":"))),
            )

    def list_users(
        self, *, status: str = "all", query: str = "", profile_type: str = "",
        institution: str = "", offset: int = 0, limit: int = 200
    ) -> dict[str, Any]:
        clauses: list[str] = []
        params: list[Any] = []
        status_value = str(status or "all").strip().lower()
        if status_value and status_value != "all":
            statuses = [item.strip() for item in status_value.split(",") if item.strip()]
            if statuses:
                placeholders = ",".join("?" for _ in statuses)
                clauses.append(f"access_status IN ({placeholders})")
                params.extend(statuses)
        query_value = str(query or "").strip().lower()
        if query_value:
            like = f"%{query_value}%"
            clauses.append("(LOWER(full_name) LIKE ? OR LOWER(email_normalized) LIKE ?)")
            params.extend([like, like])
        profile_value = str(profile_type or "").strip().lower()
        if profile_value:
            clauses.append("profile_type = ?")
            params.append(profile_value)
        institution_value = str(institution or "").strip().lower()
        if institution_value:
            clauses.append("LOWER(institution) LIKE ?")
            params.append(f"%{institution_value}%")
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        safe_offset = max(0, int(offset or 0))
        safe_limit = max(1, min(1000, int(limit or 200)))
        with self.connection() as con:
            total = int(con.execute(f"SELECT COUNT(*) FROM users{where}", tuple(params)).fetchone()[0])
            rows = con.execute(
                f"""
                SELECT id, public_id, full_name, email_normalized, profile_type, institution,
                       course_area, purpose, access_status, email_verified_at, created_at, requested_at,
                       approved_at, rejected_at, suspended_at, disabled_at, last_login_at,
                       privacy_accepted_at, privacy_version
                FROM users{where}
                ORDER BY
                    CASE access_status
                        WHEN 'pending_approval' THEN 0
                        WHEN 'email_pending' THEN 1
                        WHEN 'active' THEN 2
                        WHEN 'suspended' THEN 3
                        WHEN 'rejected' THEN 4
                        ELSE 5
                    END,
                    requested_at DESC, id DESC
                LIMIT ? OFFSET ?
                """,
                tuple(params + [safe_limit, safe_offset]),
            ).fetchall()
            return {"items": [dict(row) for row in rows], "total": total, "offset": safe_offset, "limit": safe_limit}

    def list_audit_log(self, user_id: int, *, limit: int = 100) -> list[dict[str, Any]]:
        with self.connection() as con:
            rows = con.execute(
                "SELECT id, action, created_at, metadata_json FROM auth_audit_log WHERE user_id = ? ORDER BY id DESC LIMIT ?",
                (int(user_id), max(1, min(500, int(limit or 100)))),
            ).fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            try:
                item["metadata"] = json.loads(str(item.pop("metadata_json") or "{}"))
            except Exception:
                item["metadata"] = {}
                item.pop("metadata_json", None)
            items.append(item)
        return items

    def count_active_sessions(self, user_id: int) -> int:
        now = iso_utc()
        with self.connection() as con:
            row = con.execute(
                "SELECT COUNT(*) FROM auth_sessions WHERE user_id = ? AND revoked_at IS NULL AND expires_at > ?",
                (int(user_id), now),
            ).fetchone()
            return int(row[0] if row else 0)

    def transition_status(self, user_id: int, *, from_statuses: tuple[str, ...], to_status: str) -> tuple[dict[str, Any] | None, bool]:
        expected = tuple(str(item) for item in from_statuses if str(item))
        if not expected:
            raise ValueError("from_statuses não pode ser vazio")
        placeholders = ",".join("?" for _ in expected)
        now = iso_utc()
        assignments = ["access_status = ?"]
        values: list[Any] = [str(to_status)]
        if to_status == "active":
            assignments.append("approved_at = COALESCE(approved_at, ?)")
            values.append(now)
        elif to_status == "rejected":
            assignments.append("rejected_at = ?")
            values.append(now)
        elif to_status == "suspended":
            assignments.append("suspended_at = ?")
            values.append(now)
        elif to_status == "disabled":
            assignments.append("disabled_at = ?")
            values.append(now)
        values.extend([int(user_id), *expected])
        with self.connection() as con:
            cur = con.execute(
                f"UPDATE users SET {', '.join(assignments)} WHERE id = ? AND access_status IN ({placeholders})",
                tuple(values),
            )
            row = con.execute("SELECT * FROM users WHERE id = ?", (int(user_id),)).fetchone()
            return self._row(row), cur.rowcount == 1

    def record_notification(
        self, *, user_id: int, notification_type: str, status: str, error_message: str = ""
    ) -> dict[str, Any]:
        now = iso_utc()
        sent_at = now if str(status) == "sent" else None
        with self.connection() as con:
            cur = con.execute(
                """
                INSERT INTO auth_notifications
                    (user_id, notification_type, status, created_at, sent_at, error_message)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (int(user_id), str(notification_type), str(status), now, sent_at, str(error_message or "")[:1000]),
            )
            return dict(con.execute("SELECT * FROM auth_notifications WHERE id = ?", (cur.lastrowid,)).fetchone())

    def list_notifications(self, user_id: int, *, limit: int = 30) -> list[dict[str, Any]]:
        with self.connection() as con:
            rows = con.execute(
                """SELECT id, notification_type, status, created_at, sent_at, error_message
                   FROM auth_notifications WHERE user_id = ? ORDER BY id DESC LIMIT ?""",
                (int(user_id), max(1, min(200, int(limit or 30)))),
            ).fetchall()
            return [dict(row) for row in rows]

    def rate_limit_hit(self, *, scope: str, subject_hash: str, window_seconds: int, max_events: int) -> tuple[bool, int]:
        now = utc_now()
        cutoff = now - timedelta(seconds=max(1, int(window_seconds)))
        with self.connection() as con:
            con.execute("DELETE FROM auth_rate_events WHERE occurred_at < ?", (iso_utc(now - timedelta(days=2)),))
            rows = con.execute(
                "SELECT occurred_at FROM auth_rate_events WHERE scope = ? AND subject_hash = ? AND occurred_at >= ? ORDER BY id ASC",
                (str(scope), str(subject_hash), iso_utc(cutoff)),
            ).fetchall()
            if len(rows) >= int(max_events):
                first = parse_iso_utc(rows[0]["occurred_at"]) or now
                retry = max(1, int((first + timedelta(seconds=int(window_seconds)) - now).total_seconds()))
                return False, retry
            con.execute(
                "INSERT INTO auth_rate_events (scope, subject_hash, occurred_at) VALUES (?, ?, ?)",
                (str(scope), str(subject_hash), iso_utc(now)),
            )
            return True, 0
