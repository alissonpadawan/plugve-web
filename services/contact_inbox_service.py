from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.contact_email_service import ContactMessage


MESSAGE_STATUSES = ("unread", "read", "replied", "archived")
DELIVERY_STATUSES = ("pending", "sent", "failed")


class ContactInboxValidationError(ValueError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code

    def __str__(self) -> str:
        return self.message


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ContactInboxService:
    """Caixa administrativa persistente das mensagens enviadas pelo site.

    Os dados pessoais permanecem no banco persistente do servidor e só são
    expostos pelas rotas administrativas protegidas por token.
    """

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
                CREATE TABLE IF NOT EXISTS contact_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    email TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'unread'
                        CHECK (status IN ('unread', 'read', 'replied', 'archived')),
                    delivery_status TEXT NOT NULL DEFAULT 'pending'
                        CHECK (delivery_status IN ('pending', 'sent', 'failed')),
                    delivery_error TEXT NOT NULL DEFAULT ''
                );

                CREATE INDEX IF NOT EXISTS idx_contact_messages_status_created
                    ON contact_messages(status, created_at DESC);
                """
            )

    def create_message(self, contact: ContactMessage) -> dict[str, Any]:
        now = _utc_now_iso()
        with self._connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO contact_messages(
                    name, email, subject, message, created_at, updated_at,
                    status, delivery_status, delivery_error
                ) VALUES (?, ?, ?, ?, ?, ?, 'unread', 'pending', '')
                """,
                (contact.name, contact.email, contact.subject, contact.message, now, now),
            )
            message_id = int(cursor.lastrowid)
            row = connection.execute(
                "SELECT * FROM contact_messages WHERE id = ?", (message_id,)
            ).fetchone()
        return self._serialize(row)

    def update_delivery(
        self,
        message_id: int,
        status: str,
        error: str = "",
    ) -> dict[str, Any] | None:
        message_id = self._validate_id(message_id)
        status = str(status or "").strip().lower()
        if status not in DELIVERY_STATUSES:
            raise ContactInboxValidationError("Status de envio inválido.")
        clean_error = " ".join(str(error or "").split())[:500]
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE contact_messages
                SET delivery_status = ?, delivery_error = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, clean_error, _utc_now_iso(), message_id),
            )
            row = connection.execute(
                "SELECT * FROM contact_messages WHERE id = ?", (message_id,)
            ).fetchone()
        return self._serialize(row) if row else None

    def list_messages(
        self,
        *,
        status: str = "all",
        offset: int = 0,
        limit: int = 200,
    ) -> dict[str, Any]:
        status = str(status or "all").strip().lower()
        if status not in {"all", *MESSAGE_STATUSES}:
            raise ContactInboxValidationError("Status de mensagem inválido.")
        offset = max(0, int(offset or 0))
        limit = min(500, max(1, int(limit or 200)))
        where = "" if status == "all" else "WHERE status = ?"
        params: tuple[Any, ...] = () if status == "all" else (status,)
        with self._connection() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM contact_messages
                {where}
                ORDER BY id DESC
                LIMIT ? OFFSET ?
                """,
                (*params, limit, offset),
            ).fetchall()
            total_row = connection.execute(
                f"SELECT COUNT(*) AS total FROM contact_messages {where}", params
            ).fetchone()
            unread_row = connection.execute(
                "SELECT COUNT(*) AS total FROM contact_messages WHERE status = 'unread'"
            ).fetchone()
        messages = [self._serialize(row) for row in rows]
        total = int(total_row["total"] if total_row else 0)
        return {
            "messages": messages,
            "total": total,
            "unread": int(unread_row["total"] if unread_row else 0),
            "offset": offset,
            "limit": limit,
            "has_more": offset + len(messages) < total,
        }

    def update_status(self, message_id: int, status: str) -> dict[str, Any] | None:
        message_id = self._validate_id(message_id)
        status = str(status or "").strip().lower()
        if status not in MESSAGE_STATUSES:
            raise ContactInboxValidationError("Status de mensagem inválido.")
        with self._connection() as connection:
            connection.execute(
                "UPDATE contact_messages SET status = ?, updated_at = ? WHERE id = ?",
                (status, _utc_now_iso(), message_id),
            )
            row = connection.execute(
                "SELECT * FROM contact_messages WHERE id = ?", (message_id,)
            ).fetchone()
        return self._serialize(row) if row else None

    def delete_message(self, message_id: int) -> bool:
        message_id = self._validate_id(message_id)
        with self._connection() as connection:
            cursor = connection.execute(
                "DELETE FROM contact_messages WHERE id = ?", (message_id,)
            )
        return cursor.rowcount == 1

    @staticmethod
    def _validate_id(value: Any) -> int:
        try:
            message_id = int(value)
        except (TypeError, ValueError) as exc:
            raise ContactInboxValidationError("Mensagem inválida.") from exc
        if message_id <= 0:
            raise ContactInboxValidationError("Mensagem inválida.")
        return message_id

    @staticmethod
    def _serialize(row: sqlite3.Row) -> dict[str, Any]:
        created_at_raw = str(row["created_at"])
        try:
            created_at = datetime.fromisoformat(created_at_raw)
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            display_date = created_at.astimezone(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
        except ValueError:
            display_date = created_at_raw
        return {
            "id": int(row["id"]),
            "name": str(row["name"]),
            "email": str(row["email"]),
            "subject": str(row["subject"]),
            "message": str(row["message"]),
            "created_at": created_at_raw,
            "date": display_date,
            "updated_at": str(row["updated_at"]),
            "status": str(row["status"]),
            "delivery_status": str(row["delivery_status"]),
            "delivery_error": str(row["delivery_error"] or ""),
        }
