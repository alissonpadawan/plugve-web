from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


SNAPSHOT_SCHEMA = "curve-result-snapshot-v1"
RESULT_TYPES = {"S": "tco", "D": "depreciacao", "F": "fipe_plus"}
CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
LOCAL_TIMEZONE = "America/Sao_Paulo"
MAX_SNAPSHOT_BYTES = 3_000_000


class ResultSnapshotError(ValueError):
    pass


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hash_optional_identifier(value: str) -> str:
    value = str(value or "").strip()
    return hashlib.sha256(value.encode("utf-8")).hexdigest() if value else ""


class ResultSnapshotService:
    """Persistência imutável dos resultados históricos da CurVE.

    V50.11 não oferece ainda a interface pública de recuperação. O objetivo desta
    camada é congelar o resultado no instante da geração, com hash de integridade,
    para que uma etapa posterior possa reabri-lo sem consultar FIPE/ANP/ANEEL nem
    recalcular o resultado original.
    """

    def __init__(self, database_path: str | Path, platform_version: str = ""):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.platform_version = str(platform_version or "").strip() or "desconhecida"
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
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
                CREATE TABLE IF NOT EXISTS result_snapshots (
                    result_code TEXT PRIMARY KEY,
                    result_type TEXT NOT NULL CHECK (result_type IN ('S','D','F')),
                    module TEXT NOT NULL,
                    created_at_utc TEXT NOT NULL,
                    created_at_local TEXT NOT NULL,
                    timezone_name TEXT NOT NULL,
                    schema_version TEXT NOT NULL,
                    platform_version TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    payload_bytes INTEGER NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    visitor_hash TEXT NOT NULL DEFAULT '',
                    session_hash TEXT NOT NULL DEFAULT ''
                );

                CREATE INDEX IF NOT EXISTS idx_result_snapshots_created
                    ON result_snapshots(created_at_utc DESC, result_code DESC);
                CREATE INDEX IF NOT EXISTS idx_result_snapshots_type_created
                    ON result_snapshots(result_type, created_at_utc DESC);
                CREATE INDEX IF NOT EXISTS idx_result_snapshots_visitor
                    ON result_snapshots(visitor_hash, created_at_utc DESC);

                CREATE TRIGGER IF NOT EXISTS trg_result_snapshots_immutable_update
                BEFORE UPDATE ON result_snapshots
                BEGIN
                    SELECT RAISE(ABORT, 'result_snapshot_immutable');
                END;

                CREATE TRIGGER IF NOT EXISTS trg_result_snapshots_immutable_delete
                BEFORE DELETE ON result_snapshots
                BEGIN
                    SELECT RAISE(ABORT, 'result_snapshot_immutable');
                END;
                """
            )

    @staticmethod
    def _normalize_type(result_type: str) -> str:
        normalized = str(result_type or "").strip().upper()
        if normalized not in RESULT_TYPES:
            raise ResultSnapshotError("Tipo de resultado inválido. Use S, D ou F.")
        return normalized

    @staticmethod
    def _now() -> tuple[datetime, datetime]:
        utc_now = datetime.now(timezone.utc)
        try:
            local_now = utc_now.astimezone(ZoneInfo(LOCAL_TIMEZONE))
        except Exception:
            local_now = utc_now
        return utc_now, local_now

    @staticmethod
    def _new_code(result_type: str, local_now: datetime) -> str:
        suffix = "".join(secrets.choice(CODE_ALPHABET) for _ in range(10))
        return f"{result_type}-{local_now.strftime('%Y%m%d')}-{suffix}"

    def create_snapshot(
        self,
        *,
        result_type: str,
        module: str,
        payload: dict[str, Any],
        visitor_id: str = "",
        session_id: str = "",
    ) -> dict[str, Any]:
        result_type = self._normalize_type(result_type)
        module = str(module or "").strip().lower()
        if module != RESULT_TYPES[result_type]:
            raise ResultSnapshotError(
                f"Módulo incompatível com o tipo {result_type}: esperado {RESULT_TYPES[result_type]}."
            )
        if not isinstance(payload, dict) or not payload:
            raise ResultSnapshotError("Snapshot vazio ou inválido.")

        utc_now, local_now = self._now()
        envelope = {
            "snapshot_schema": SNAPSHOT_SCHEMA,
            "platform_version": self.platform_version,
            "result_type": result_type,
            "module": module,
            "created_at_utc": utc_now.isoformat(),
            "created_at_local": local_now.isoformat(),
            "timezone": LOCAL_TIMEZONE,
            "payload": payload,
        }
        snapshot_json = _canonical_json(envelope)
        payload_bytes = len(snapshot_json.encode("utf-8"))
        if payload_bytes > MAX_SNAPSHOT_BYTES:
            raise ResultSnapshotError(
                f"Snapshot excede o limite de {MAX_SNAPSHOT_BYTES} bytes ({payload_bytes} bytes)."
            )
        payload_sha256 = _sha256_text(snapshot_json)
        visitor_hash = _hash_optional_identifier(visitor_id)
        session_hash = _hash_optional_identifier(session_id)

        with self._connection() as connection:
            for _ in range(20):
                result_code = self._new_code(result_type, local_now)
                try:
                    connection.execute(
                        """
                        INSERT INTO result_snapshots(
                            result_code, result_type, module,
                            created_at_utc, created_at_local, timezone_name,
                            schema_version, platform_version,
                            payload_sha256, payload_bytes, snapshot_json,
                            visitor_hash, session_hash
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            result_code,
                            result_type,
                            module,
                            envelope["created_at_utc"],
                            envelope["created_at_local"],
                            LOCAL_TIMEZONE,
                            SNAPSHOT_SCHEMA,
                            self.platform_version,
                            payload_sha256,
                            payload_bytes,
                            snapshot_json,
                            visitor_hash,
                            session_hash,
                        ),
                    )
                    break
                except sqlite3.IntegrityError as exc:
                    if "UNIQUE" not in str(exc).upper() and "PRIMARY" not in str(exc).upper():
                        raise
            else:
                raise ResultSnapshotError("Não foi possível gerar um identificador único.")

        return {
            "code": result_code,
            "result_type": result_type,
            "module": module,
            "created_at_utc": envelope["created_at_utc"],
            "created_at_local": envelope["created_at_local"],
            "created_at_local_display": local_now.strftime("%d/%m/%Y %H:%M"),
            "timezone": LOCAL_TIMEZONE,
            "payload_sha256": payload_sha256,
            "payload_bytes": payload_bytes,
            "platform_version": self.platform_version,
        }

    def get_snapshot(self, result_code: str, *, verify_integrity: bool = True) -> dict[str, Any] | None:
        code = str(result_code or "").strip().upper()
        if not code:
            return None
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM result_snapshots WHERE result_code = ?", (code,)
            ).fetchone()
        if row is None:
            return None
        snapshot_json = str(row["snapshot_json"] or "")
        if verify_integrity and _sha256_text(snapshot_json) != str(row["payload_sha256"] or ""):
            raise ResultSnapshotError("Falha de integridade no snapshot armazenado.")
        envelope = json.loads(snapshot_json)
        return {
            "code": str(row["result_code"]),
            "result_type": str(row["result_type"]),
            "module": str(row["module"]),
            "created_at_utc": str(row["created_at_utc"]),
            "created_at_local": str(row["created_at_local"]),
            "timezone": str(row["timezone_name"]),
            "schema_version": str(row["schema_version"]),
            "platform_version": str(row["platform_version"]),
            "payload_sha256": str(row["payload_sha256"]),
            "payload_bytes": int(row["payload_bytes"] or 0),
            "snapshot": envelope,
        }

    def count(self, result_type: str = "") -> int:
        normalized = str(result_type or "").strip().upper()
        with self._connection() as connection:
            if normalized:
                normalized = self._normalize_type(normalized)
                row = connection.execute(
                    "SELECT COUNT(*) AS total FROM result_snapshots WHERE result_type = ?",
                    (normalized,),
                ).fetchone()
            else:
                row = connection.execute("SELECT COUNT(*) AS total FROM result_snapshots").fetchone()
        return int(row["total"] if row else 0)


@lru_cache(maxsize=8)
def _cached_result_snapshot_service(database_path: str, platform_version: str) -> ResultSnapshotService:
    return ResultSnapshotService(database_path, platform_version=platform_version)


def get_result_snapshot_service() -> ResultSnapshotService:
    from flask import current_app

    return _cached_result_snapshot_service(
        str(current_app.config["ARQUIVO_RESULTADOS"]),
        str(current_app.config.get("CURVE_VERSION") or ""),
    )
