from __future__ import annotations

import hashlib
import re
import sqlite3
import unicodedata
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any



ANALYSIS_TYPES = ("tco", "depreciacao", "fipe_plus")
REQUEST_STATUSES = ("pending", "attended", "discarded")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_text(value: Any, max_length: int = 180) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    return text[:max_length]


def _normalize_key_part(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")[:180]


class SiteUsageValidationError(ValueError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code

    def __str__(self) -> str:
        return self.message


class SiteUsageService:
    """Persistência leve para métricas de uso e solicitações de curva.

    O banco guarda somente contagens agregadas e os dados técnicos do veículo
    solicitado. Não registra IP, geolocalização ou e-mail do visitante.
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
                CREATE TABLE IF NOT EXISTS analysis_counts (
                    analysis_type TEXT PRIMARY KEY,
                    value INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS curve_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_key TEXT NOT NULL UNIQUE,
                    vehicle_type TEXT NOT NULL DEFAULT '',
                    codigo_fipe TEXT NOT NULL DEFAULT '',
                    codigo_marca TEXT NOT NULL DEFAULT '',
                    codigo_modelo TEXT NOT NULL DEFAULT '',
                    codigo_ano TEXT NOT NULL DEFAULT '',
                    marca TEXT NOT NULL DEFAULT '',
                    modelo TEXT NOT NULL DEFAULT '',
                    ano_modelo TEXT NOT NULL DEFAULT '',
                    combustivel TEXT NOT NULL DEFAULT '',
                    request_count INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'attended', 'discarded')),
                    first_requested_at TEXT NOT NULL,
                    last_requested_at TEXT NOT NULL,
                    status_updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS curve_request_visitors (
                    request_id INTEGER NOT NULL,
                    visitor_hash TEXT NOT NULL,
                    requested_at TEXT NOT NULL,
                    PRIMARY KEY (request_id, visitor_hash),
                    FOREIGN KEY (request_id) REFERENCES curve_requests(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_curve_requests_status_last
                    ON curve_requests(status, last_requested_at DESC);
                """
            )
            now = _utc_now_iso()
            for analysis_type in ANALYSIS_TYPES:
                connection.execute(
                    "INSERT OR IGNORE INTO analysis_counts(analysis_type, value, updated_at) VALUES (?, 0, ?)",
                    (analysis_type, now),
                )

    @staticmethod
    def visitor_hash(visitor_id: str) -> str:
        return hashlib.sha256(str(visitor_id or "").encode("utf-8")).hexdigest()

    def record_analysis(self, analysis_type: str, amount: int = 1) -> dict[str, int]:
        analysis_type = str(analysis_type or "").strip().lower()
        if analysis_type not in ANALYSIS_TYPES:
            raise SiteUsageValidationError("Tipo de análise inválido.")
        amount = int(amount or 1)
        if amount < 1 or amount > 1000:
            raise SiteUsageValidationError("Quantidade de análises inválida.")
        now = _utc_now_iso()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO analysis_counts(analysis_type, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(analysis_type) DO UPDATE SET
                    value = value + excluded.value,
                    updated_at = excluded.updated_at
                """,
                (analysis_type, amount, now),
            )
        return self.get_analysis_counts()

    def get_analysis_counts(self) -> dict[str, int]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT analysis_type, value FROM analysis_counts"
            ).fetchall()
        counts = {analysis_type: 0 for analysis_type in ANALYSIS_TYPES}
        for row in rows:
            key = str(row["analysis_type"] or "")
            if key in counts:
                counts[key] = max(0, int(row["value"] or 0))
        counts["total"] = sum(counts[key] for key in ANALYSIS_TYPES)
        return counts

    def _request_key(self, payload: dict[str, Any]) -> str:
        vehicle_type = _normalize_key_part(payload.get("tipo") or payload.get("vehicle_type") or "auto")
        codigo_fipe = _normalize_key_part(payload.get("codigo_fipe"))
        codigo_ano = _normalize_key_part(payload.get("codigo_ano") or payload.get("ano_modelo"))
        codigo_modelo = _normalize_key_part(payload.get("codigo_modelo"))
        codigo_marca = _normalize_key_part(payload.get("codigo_marca"))
        if codigo_fipe:
            return f"fipe:{codigo_fipe}|ano:{codigo_ano}"
        if codigo_modelo:
            return f"{vehicle_type}|marca:{codigo_marca}|modelo:{codigo_modelo}|ano:{codigo_ano}"
        marca = _normalize_key_part(payload.get("marca"))
        modelo = _normalize_key_part(payload.get("modelo"))
        if not (marca and modelo):
            raise SiteUsageValidationError("Não foi possível identificar o veículo solicitado.")
        return f"{vehicle_type}|{marca}|{modelo}|ano:{codigo_ano}"

    def submit_curve_request(self, *, visitor_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise SiteUsageValidationError("Solicitação inválida.")
        visitor_id = str(visitor_id or "").strip()
        if not visitor_id:
            raise SiteUsageValidationError("Sessão inválida. Atualize a página e tente novamente.", 403)

        request_key = self._request_key(payload)
        vehicle = {
            "vehicle_type": _clean_text(payload.get("tipo") or payload.get("vehicle_type") or "auto", 30),
            "codigo_fipe": _clean_text(payload.get("codigo_fipe"), 40),
            "codigo_marca": _clean_text(payload.get("codigo_marca"), 40),
            "codigo_modelo": _clean_text(payload.get("codigo_modelo"), 40),
            "codigo_ano": _clean_text(payload.get("codigo_ano"), 60),
            "marca": _clean_text(payload.get("marca"), 100),
            "modelo": _clean_text(payload.get("modelo"), 180),
            "ano_modelo": _clean_text(
                payload.get("ano_modelo") or payload.get("ano_modelo_raw") or payload.get("AnoModelo"),
                60,
            ),
            "combustivel": _clean_text(payload.get("combustivel") or payload.get("Combustivel"), 80),
        }
        if not vehicle["modelo"] and not vehicle["codigo_modelo"]:
            raise SiteUsageValidationError("Selecione um veículo antes de solicitar a curva.")

        visitor_hash = self.visitor_hash(visitor_id)
        now = _utc_now_iso()
        with self._connection() as connection:
            row = connection.execute(
                "SELECT id, status, request_count FROM curve_requests WHERE request_key = ?",
                (request_key,),
            ).fetchone()
            if row is None:
                cursor = connection.execute(
                    """
                    INSERT INTO curve_requests(
                        request_key, vehicle_type, codigo_fipe, codigo_marca, codigo_modelo,
                        codigo_ano, marca, modelo, ano_modelo, combustivel, request_count,
                        status, first_requested_at, last_requested_at, status_updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 'pending', ?, ?, ?)
                    """,
                    (
                        request_key,
                        vehicle["vehicle_type"], vehicle["codigo_fipe"], vehicle["codigo_marca"],
                        vehicle["codigo_modelo"], vehicle["codigo_ano"], vehicle["marca"],
                        vehicle["modelo"], vehicle["ano_modelo"], vehicle["combustivel"],
                        now, now, now,
                    ),
                )
                request_id = int(cursor.lastrowid)
                previous_status = "pending"
            else:
                request_id = int(row["id"])
                previous_status = str(row["status"] or "pending")
                connection.execute(
                    """
                    UPDATE curve_requests SET
                        vehicle_type = ?, codigo_fipe = ?, codigo_marca = ?, codigo_modelo = ?,
                        codigo_ano = ?, marca = ?, modelo = ?, ano_modelo = ?, combustivel = ?
                    WHERE id = ?
                    """,
                    (
                        vehicle["vehicle_type"], vehicle["codigo_fipe"], vehicle["codigo_marca"],
                        vehicle["codigo_modelo"], vehicle["codigo_ano"], vehicle["marca"],
                        vehicle["modelo"], vehicle["ano_modelo"], vehicle["combustivel"], request_id,
                    ),
                )

            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO curve_request_visitors(request_id, visitor_hash, requested_at)
                VALUES (?, ?, ?)
                """,
                (request_id, visitor_hash, now),
            )
            added = cursor.rowcount > 0
            if added:
                connection.execute(
                    """
                    UPDATE curve_requests SET
                        request_count = request_count + 1,
                        last_requested_at = ?,
                        status = 'pending',
                        status_updated_at = CASE WHEN status <> 'pending' THEN ? ELSE status_updated_at END
                    WHERE id = ?
                    """,
                    (now, now, request_id),
                )

        return {
            "received": True,
            "already_requested": not added,
            "reopened": bool(added and previous_status != "pending"),
        }

    @staticmethod
    def _serialize_request(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "vehicle_type": str(row["vehicle_type"] or ""),
            "codigo_fipe": str(row["codigo_fipe"] or ""),
            "codigo_marca": str(row["codigo_marca"] or ""),
            "codigo_modelo": str(row["codigo_modelo"] or ""),
            "codigo_ano": str(row["codigo_ano"] or ""),
            "marca": str(row["marca"] or ""),
            "modelo": str(row["modelo"] or ""),
            "ano_modelo": str(row["ano_modelo"] or ""),
            "combustivel": str(row["combustivel"] or ""),
            "request_count": int(row["request_count"] or 0),
            "status": str(row["status"] or "pending"),
            "first_requested_at": str(row["first_requested_at"] or ""),
            "last_requested_at": str(row["last_requested_at"] or ""),
            "status_updated_at": str(row["status_updated_at"] or ""),
        }

    def list_curve_requests(
        self,
        *,
        status: str = "all",
        offset: int = 0,
        limit: int = 500,
    ) -> dict[str, Any]:
        status = str(status or "all").strip().lower()
        if status not in {"all", *REQUEST_STATUSES}:
            raise SiteUsageValidationError("Status de solicitação inválido.")
        offset = max(0, int(offset or 0))
        limit = min(1000, max(1, int(limit or 500)))
        where = "" if status == "all" else "WHERE status = ?"
        params: tuple[Any, ...] = () if status == "all" else (status,)
        with self._connection() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM curve_requests
                {where}
                ORDER BY CASE status WHEN 'pending' THEN 0 WHEN 'attended' THEN 1 ELSE 2 END,
                         last_requested_at DESC, id DESC
                LIMIT ? OFFSET ?
                """,
                (*params, limit, offset),
            ).fetchall()
            total_row = connection.execute(
                f"SELECT COUNT(*) AS total FROM curve_requests {where}",
                params,
            ).fetchone()
        items = [self._serialize_request(row) for row in rows]
        total = int(total_row["total"] if total_row else 0)
        return {
            "requests": items,
            "total": total,
            "offset": offset,
            "limit": limit,
            "has_more": offset + len(items) < total,
        }

    def update_curve_request_status(self, request_id: int, status: str) -> dict[str, Any] | None:
        try:
            request_id = int(request_id)
        except (TypeError, ValueError) as exc:
            raise SiteUsageValidationError("Solicitação inválida.") from exc
        status = str(status or "").strip().lower()
        if request_id <= 0 or status not in REQUEST_STATUSES:
            raise SiteUsageValidationError("Solicitação ou status inválido.")
        now = _utc_now_iso()
        with self._connection() as connection:
            cursor = connection.execute(
                "UPDATE curve_requests SET status = ?, status_updated_at = ? WHERE id = ?",
                (status, now, request_id),
            )
            if cursor.rowcount <= 0:
                return None
            row = connection.execute(
                "SELECT * FROM curve_requests WHERE id = ?", (request_id,)
            ).fetchone()
        return self._serialize_request(row) if row is not None else None


@lru_cache(maxsize=4)
def _cached_site_usage_service(database_path: str) -> SiteUsageService:
    return SiteUsageService(database_path)


def get_site_usage_service() -> SiteUsageService:
    from flask import current_app
    return _cached_site_usage_service(str(current_app.config["ARQUIVO_USO_SITE"]))
