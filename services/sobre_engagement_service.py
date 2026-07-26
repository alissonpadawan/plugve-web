from __future__ import annotations

import hashlib
import re
import sqlite3
import unicodedata
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


COMMENT_MIN_LENGTH = 8
COMMENT_MAX_LENGTH = 500
NAME_MAX_LENGTH = 60
EMAIL_MAX_LENGTH = 254
PAGE_SIZE = 5
MAX_PAGE_SIZE = 20

_EMAIL_RE = re.compile(r"^[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?(?:\.[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?)+$", re.I)
_NAME_RE = re.compile(r"^[A-Za-zÀ-ÖØ-öø-ÿĀ-ž'’\- ]+$")
_URL_RE = re.compile(
    r"(?i)(?:https?://|ftp://|www\.|\b(?:[a-z0-9-]+\.)+(?:com(?:\.br)?|net(?:\.br)?|org(?:\.br)?|gov\.br|edu\.br|io|co|app|dev|info|biz|me|ly|br)\b)"
)
_EMAIL_IN_COMMENT_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_HTML_RE = re.compile(r"<\s*/?\s*[a-z][^>]*>|javascript\s*:", re.I)
_PHONE_CANDIDATE_RE = re.compile(r"(?<!\w)\+?\d[\d\s().\-]{6,}\d(?!\w)")

_BLOCKED_TERMS = {
    "arrombado", "buceta", "caralho", "cuzao", "desgracado", "fdp",
    "filho da puta", "foda se", "fodase", "imbecil", "merda", "otario",
    "piranha", "porra", "puta", "puto", "retardado", "vai tomar no cu",
}


@dataclass(slots=True)
class EngagementValidationError(ValueError):
    message: str
    status_code: int = 400

    def __str__(self) -> str:
        return self.message


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_for_filter(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    table = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"})
    text = text.translate(table)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _has_phone(value: str) -> bool:
    for match in _PHONE_CANDIDATE_RE.finditer(value):
        if len(re.sub(r"\D", "", match.group(0))) >= 8:
            return True
    return False


def _validate_name(value: Any) -> str:
    name = re.sub(r"\s+", " ", str(value or "").strip())
    if len(name) < 2:
        raise EngagementValidationError("Informe seu nome.")
    if len(name) > NAME_MAX_LENGTH:
        raise EngagementValidationError(f"O nome deve ter no máximo {NAME_MAX_LENGTH} caracteres.")
    if not _NAME_RE.fullmatch(name):
        raise EngagementValidationError("Use apenas letras, espaços, hífen ou apóstrofo no nome.")
    return name


def _validate_email(value: Any) -> str:
    email = str(value or "").strip().lower()
    if not email:
        raise EngagementValidationError("Informe seu e-mail.")
    if len(email) > EMAIL_MAX_LENGTH or not _EMAIL_RE.fullmatch(email):
        raise EngagementValidationError("Informe um e-mail válido.")
    return email


def _validate_comment(value: Any) -> str:
    body = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    body = re.sub(r"[\t ]+", " ", body)
    body = re.sub(r"\n{3,}", "\n\n", body)
    if len(body) < COMMENT_MIN_LENGTH:
        raise EngagementValidationError(f"O comentário deve ter pelo menos {COMMENT_MIN_LENGTH} caracteres.")
    if len(body) > COMMENT_MAX_LENGTH:
        raise EngagementValidationError(f"O comentário deve ter no máximo {COMMENT_MAX_LENGTH} caracteres.")
    if _HTML_RE.search(body):
        raise EngagementValidationError("O comentário deve conter somente texto.")
    if _URL_RE.search(body):
        raise EngagementValidationError("Links não são permitidos nos comentários.")
    if _EMAIL_IN_COMMENT_RE.search(body):
        raise EngagementValidationError("Não inclua e-mails no comentário.")
    if _has_phone(body):
        raise EngagementValidationError("Não inclua números de telefone no comentário.")
    normalized = _normalize_for_filter(body)
    padded = f" {normalized} "
    if any(f" {term} " in padded for term in _BLOCKED_TERMS):
        raise EngagementValidationError("O comentário contém linguagem não permitida.")
    if re.search(r"(.)\1{7,}", normalized.replace(" ", "")):
        raise EngagementValidationError("Evite repetições excessivas no comentário.")
    return body


class SobreEngagementService:
    def __init__(self, database_path: str | Path):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS engagement_stats (
                    key TEXT PRIMARY KEY,
                    value INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS visitors (
                    visitor_hash TEXT PRIMARY KEY,
                    first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS votes (
                    visitor_hash TEXT PRIMARY KEY,
                    vote TEXT NOT NULL CHECK (vote IN ('like', 'dislike')),
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS comments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    visitor_hash TEXT NOT NULL,
                    name TEXT NOT NULL,
                    email TEXT NOT NULL,
                    body TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'published'
                        CHECK (status IN ('published', 'hidden'))
                );
                CREATE INDEX IF NOT EXISTS idx_comments_status_id
                    ON comments(status, id DESC);
                CREATE INDEX IF NOT EXISTS idx_comments_visitor_created
                    ON comments(visitor_hash, created_at DESC);
                """
            )
            columns = {str(row["name"]) for row in connection.execute("PRAGMA table_info(comments)").fetchall()}
            if "parent_id" not in columns:
                connection.execute("ALTER TABLE comments ADD COLUMN parent_id INTEGER REFERENCES comments(id) ON DELETE CASCADE")
            if "is_official" not in columns:
                connection.execute("ALTER TABLE comments ADD COLUMN is_official INTEGER NOT NULL DEFAULT 0")
            if "official_label" not in columns:
                connection.execute("ALTER TABLE comments ADD COLUMN official_label TEXT NOT NULL DEFAULT ''")
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_comments_parent_status_id ON comments(parent_id, status, id)"
            )
            connection.execute(
                "INSERT OR IGNORE INTO engagement_stats(key, value) VALUES ('visitors', 0)"
            )

    @staticmethod
    def visitor_hash(visitor_id: str) -> str:
        return hashlib.sha256(str(visitor_id).encode("utf-8")).hexdigest()

    def register_visitor(self, visitor_id: str) -> bool:
        visitor_hash = self.visitor_hash(visitor_id)
        now = _utc_now().isoformat()
        with self._connection() as connection:
            cursor = connection.execute(
                "INSERT OR IGNORE INTO visitors(visitor_hash, first_seen, last_seen) VALUES (?, ?, ?)",
                (visitor_hash, now, now),
            )
            is_new = cursor.rowcount == 1
            if is_new:
                connection.execute("UPDATE engagement_stats SET value = value + 1 WHERE key = 'visitors'")
            else:
                connection.execute("UPDATE visitors SET last_seen = ? WHERE visitor_hash = ?", (now, visitor_hash))
        return is_new

    def get_user_vote(self, visitor_id: str) -> str | None:
        visitor_hash = self.visitor_hash(visitor_id)
        with self._connection() as connection:
            row = connection.execute("SELECT vote FROM votes WHERE visitor_hash = ?", (visitor_hash,)).fetchone()
        return str(row["vote"]) if row else None

    def set_vote(self, visitor_id: str, vote: str | None) -> dict[str, Any]:
        if vote not in {"like", "dislike", None}:
            raise EngagementValidationError("Voto inválido.")
        visitor_hash = self.visitor_hash(visitor_id)
        now = _utc_now().isoformat()
        with self._connection() as connection:
            if vote is None:
                connection.execute("DELETE FROM votes WHERE visitor_hash = ?", (visitor_hash,))
            else:
                connection.execute(
                    """
                    INSERT INTO votes(visitor_hash, vote, updated_at) VALUES (?, ?, ?)
                    ON CONFLICT(visitor_hash) DO UPDATE SET vote = excluded.vote, updated_at = excluded.updated_at
                    """,
                    (visitor_hash, vote, now),
                )
        stats = self.get_stats()
        stats["user_vote"] = vote
        return stats

    def get_stats(self) -> dict[str, int]:
        with self._connection() as connection:
            visitor_row = connection.execute("SELECT value FROM engagement_stats WHERE key = 'visitors'").fetchone()
            vote_rows = connection.execute("SELECT vote, COUNT(*) AS total FROM votes GROUP BY vote").fetchall()
            comment_row = connection.execute(
                "SELECT COUNT(*) AS total FROM comments WHERE status = 'published' AND parent_id IS NULL"
            ).fetchone()
        votes = {str(row["vote"]): int(row["total"]) for row in vote_rows}
        return {
            "visitors": int(visitor_row["value"] if visitor_row else 0),
            "likes": votes.get("like", 0),
            "dislikes": votes.get("dislike", 0),
            "comments": int(comment_row["total"] if comment_row else 0),
        }

    def list_comments(self, offset: int = 0, limit: int = PAGE_SIZE) -> dict[str, Any]:
        offset = max(0, int(offset or 0))
        limit = min(MAX_PAGE_SIZE, max(1, int(limit or PAGE_SIZE)))
        with self._connection() as connection:
            roots = connection.execute(
                """
                SELECT id, name, body, created_at, parent_id, is_official, official_label
                FROM comments
                WHERE status = 'published' AND parent_id IS NULL
                ORDER BY id DESC LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
            total_row = connection.execute(
                "SELECT COUNT(*) AS total FROM comments WHERE status = 'published' AND parent_id IS NULL"
            ).fetchone()
            root_ids = [int(row["id"]) for row in roots]
            replies_by_parent: dict[int, list[dict[str, Any]]] = {root_id: [] for root_id in root_ids}
            if root_ids:
                placeholders = ",".join("?" for _ in root_ids)
                reply_rows = connection.execute(
                    f"""
                    SELECT id, name, body, created_at, parent_id, is_official, official_label
                    FROM comments
                    WHERE status = 'published' AND parent_id IN ({placeholders})
                    ORDER BY id ASC
                    """,
                    root_ids,
                ).fetchall()
                for row in reply_rows:
                    replies_by_parent.setdefault(int(row["parent_id"]), []).append(self._serialize_comment(row))
        total = int(total_row["total"] if total_row else 0)
        comments = []
        for row in roots:
            item = self._serialize_comment(row)
            item["replies"] = replies_by_parent.get(int(row["id"]), [])
            comments.append(item)
        return {
            "comments": comments,
            "total": total,
            "offset": offset,
            "limit": limit,
            "has_more": offset + len(comments) < total,
        }

    def _enforce_public_rate_limit(self, connection: sqlite3.Connection, visitor_hash: str, now: datetime) -> None:
        recent = connection.execute(
            "SELECT created_at FROM comments WHERE visitor_hash = ? ORDER BY id DESC LIMIT 6",
            (visitor_hash,),
        ).fetchall()
        recent_dates = []
        for row in recent:
            try:
                recent_dates.append(datetime.fromisoformat(str(row["created_at"])))
            except ValueError:
                continue
        if recent_dates and now - recent_dates[0] < timedelta(minutes=2):
            raise EngagementValidationError("Aguarde dois minutos antes de enviar outro comentário.", 429)
        if sum(1 for created_at in recent_dates if now - created_at < timedelta(days=1)) >= 5:
            raise EngagementValidationError("Limite diário de comentários atingido. Tente novamente amanhã.", 429)

    def add_comment(
        self,
        *,
        visitor_id: str,
        name: Any,
        email: Any,
        body: Any,
        honeypot: Any = "",
        parent_id: Any = None,
    ) -> dict[str, Any]:
        if str(honeypot or "").strip():
            raise EngagementValidationError("Não foi possível publicar o comentário.")
        clean_name = _validate_name(name)
        clean_email = _validate_email(email)
        clean_body = _validate_comment(body)
        clean_parent_id: int | None = None
        if parent_id not in (None, "", 0, "0"):
            try:
                clean_parent_id = int(parent_id)
            except (TypeError, ValueError) as exc:
                raise EngagementValidationError("Comentário de referência inválido.") from exc
            if clean_parent_id <= 0:
                raise EngagementValidationError("Comentário de referência inválido.")
        visitor_hash = self.visitor_hash(visitor_id)
        now = _utc_now()
        with self._connection() as connection:
            self._enforce_public_rate_limit(connection, visitor_hash, now)
            if clean_parent_id is not None:
                parent = connection.execute(
                    "SELECT id FROM comments WHERE id = ? AND parent_id IS NULL AND status = 'published'",
                    (clean_parent_id,),
                ).fetchone()
                if parent is None:
                    raise EngagementValidationError("O comentário original não está disponível.", 404)
            cursor = connection.execute(
                """
                INSERT INTO comments(
                    visitor_hash, name, email, body, created_at, status,
                    parent_id, is_official, official_label
                ) VALUES (?, ?, ?, ?, ?, 'published', ?, 0, '')
                """,
                (visitor_hash, clean_name, clean_email, clean_body, now.isoformat(), clean_parent_id),
            )
            row = connection.execute(
                """
                SELECT id, name, body, created_at, parent_id, is_official, official_label
                FROM comments WHERE id = ?
                """,
                (int(cursor.lastrowid),),
            ).fetchone()
        item = self._serialize_comment(row)
        if clean_parent_id is None:
            item["replies"] = []
        return item

    def add_official_reply(self, parent_comment_id: Any, body: Any, label: str = "CurVE") -> dict[str, Any]:
        try:
            parent_comment_id = int(parent_comment_id)
        except (TypeError, ValueError) as exc:
            raise EngagementValidationError("Comentário inválido.") from exc
        if parent_comment_id <= 0:
            raise EngagementValidationError("Comentário inválido.")
        clean_body = _validate_comment(body)
        clean_label = re.sub(r"\s+", " ", str(label or "CurVE").strip())[:40] or "CurVE"
        now = _utc_now().isoformat()
        with self._connection() as connection:
            parent = connection.execute(
                "SELECT id FROM comments WHERE id = ? AND parent_id IS NULL AND status = 'published'",
                (parent_comment_id,),
            ).fetchone()
            if parent is None:
                raise EngagementValidationError("O comentário original não está disponível.", 404)
            cursor = connection.execute(
                """
                INSERT INTO comments(
                    visitor_hash, name, email, body, created_at, status,
                    parent_id, is_official, official_label
                ) VALUES (?, ?, '', ?, ?, 'published', ?, 1, ?)
                """,
                (self.visitor_hash("official-curve"), clean_label, clean_body, now, parent_comment_id, clean_label),
            )
            row = connection.execute(
                """
                SELECT id, name, body, created_at, parent_id, is_official, official_label
                FROM comments WHERE id = ?
                """,
                (int(cursor.lastrowid),),
            ).fetchone()
        return self._serialize_comment(row)

    def list_comments_admin(self, *, offset: int = 0, limit: int = 100, status: str = "all") -> dict[str, Any]:
        offset = max(0, int(offset or 0))
        limit = min(500, max(1, int(limit or 100)))
        status = str(status or "all").strip().lower()
        if status not in {"all", "published", "hidden"}:
            raise EngagementValidationError("Status de comentário inválido.")
        where = "" if status == "all" else "WHERE status = ?"
        params: tuple[Any, ...] = () if status == "all" else (status,)
        with self._connection() as connection:
            rows = connection.execute(
                f"""
                SELECT id, name, email, body, created_at, status,
                       parent_id, is_official, official_label
                FROM comments {where}
                ORDER BY CASE WHEN parent_id IS NULL THEN id ELSE parent_id END DESC,
                         CASE WHEN parent_id IS NULL THEN 0 ELSE 1 END,
                         id ASC
                LIMIT ? OFFSET ?
                """,
                (*params, limit, offset),
            ).fetchall()
            total_row = connection.execute(f"SELECT COUNT(*) AS total FROM comments {where}", params).fetchone()
        total = int(total_row["total"] if total_row else 0)
        comments = [self._serialize_admin_comment(row) for row in rows]
        return {
            "comments": comments,
            "total": total,
            "offset": offset,
            "limit": limit,
            "has_more": offset + len(comments) < total,
        }

    def delete_comment(self, comment_id: int) -> bool:
        try:
            comment_id = int(comment_id)
        except (TypeError, ValueError) as exc:
            raise EngagementValidationError("Comentário inválido.") from exc
        if comment_id <= 0:
            raise EngagementValidationError("Comentário inválido.")
        with self._connection() as connection:
            connection.execute("DELETE FROM comments WHERE parent_id = ?", (comment_id,))
            cursor = connection.execute("DELETE FROM comments WHERE id = ?", (comment_id,))
        return cursor.rowcount == 1

    @staticmethod
    def _display_date(value: str, *, admin: bool = False) -> str:
        try:
            created_at = datetime.fromisoformat(value)
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            return created_at.astimezone(timezone.utc).strftime("%d/%m/%Y %H:%M UTC" if admin else "%d/%m/%Y")
        except ValueError:
            return value if admin else ""

    @classmethod
    def _serialize_admin_comment(cls, row: sqlite3.Row) -> dict[str, Any]:
        created_at_raw = str(row["created_at"])
        return {
            "id": int(row["id"]),
            "name": str(row["name"]),
            "email": str(row["email"]),
            "body": str(row["body"]),
            "created_at": created_at_raw,
            "date": cls._display_date(created_at_raw, admin=True),
            "status": str(row["status"]),
            "parent_id": int(row["parent_id"]) if row["parent_id"] is not None else None,
            "is_reply": row["parent_id"] is not None,
            "is_official": bool(row["is_official"]),
            "official_label": str(row["official_label"] or ""),
        }

    @classmethod
    def _serialize_comment(cls, row: sqlite3.Row) -> dict[str, Any]:
        created_at_raw = str(row["created_at"])
        return {
            "id": int(row["id"]),
            "name": str(row["official_label"] or row["name"]) if bool(row["is_official"]) else str(row["name"]),
            "body": str(row["body"]),
            "date": cls._display_date(created_at_raw),
            "parent_id": int(row["parent_id"]) if row["parent_id"] is not None else None,
            "is_official": bool(row["is_official"]),
            "official_label": str(row["official_label"] or ""),
        }
