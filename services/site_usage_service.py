from __future__ import annotations

import hashlib
import json
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
RESULT_CODE_RE = re.compile(r"^[SDF]-\d{8}-[23456789ABCDEFGHJKLMNPQRSTUVWXYZ]{10}$")
RESULT_COMPLETION_ACTIONS = {
    ("tco", "simulation_completed"),
    ("depreciacao", "consultation_completed"),
    ("fipe_plus", "consultation_completed"),
}


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


def _normalize_technology_value(value: Any) -> str:
    """Normaliza a propulsão para fins de telemetria, sem alterar cálculos.

    V50.16 passa a gravar novas atividades em quatro grupos comparáveis
    (bev/phev/hev/icev). Valores legados genéricos, como ``ve``, são
    preservados como ``ve`` porque não é possível reclassificá-los com
    segurança retroativamente sem o snapshot/veículo original completo.
    """
    raw = unicodedata.normalize("NFKD", str(value or "").strip().upper())
    raw = "".join(ch for ch in raw if not unicodedata.combining(ch))
    raw = re.sub(r"[^A-Z0-9]+", "_", raw).strip("_")
    if not raw:
        return ""
    if raw in {"PHEV", "PLUG_IN", "PLUGIN", "HIBRIDO_PLUGIN", "HIBRIDO_PLUG_IN"}:
        return "phev"
    if raw in {"EV_PURO", "BEV", "EV", "ELETRICO", "ELETRICA"}:
        return "bev"
    if raw in {"HEV", "MHEV", "HEV_NAO_PLUGIN", "HIBRIDO", "HIBRIDA", "HYBRID"}:
        return "hev"
    if raw in {"ICE", "ICEV", "COMBUSTAO", "TERMICO", "TERMICA"}:
        return "icev"
    if raw == "VE":
        return "ve"
    return _clean_text(value, 40).lower()


def _result_code_from_metadata(metadata: Any) -> str:
    if not isinstance(metadata, dict):
        return ""
    code = _clean_text(metadata.get("resultado_codigo"), 40).upper()
    return code if RESULT_CODE_RE.fullmatch(code) else ""


class SiteUsageValidationError(ValueError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code

    def __str__(self) -> str:
        return self.message


class SiteUsageService:
    """Persistência leve de uso da plataforma CurVE.

    A telemetria V50.06 é pseudonimizada. O banco não recebe IP bruto: guarda
    somente identificadores hash, contexto técnico coarse e as ações necessárias
    para acompanhar uso da Simular, Depreciação e Fipe+.
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

                CREATE TABLE IF NOT EXISTS usage_visitors (
                    visitor_hash TEXT PRIMARY KEY,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    session_count INTEGER NOT NULL DEFAULT 0,
                    event_count INTEGER NOT NULL DEFAULT 0,
                    page_view_count INTEGER NOT NULL DEFAULT 0,
                    network_hash TEXT NOT NULL DEFAULT '',
                    city TEXT NOT NULL DEFAULT '',
                    region TEXT NOT NULL DEFAULT '',
                    country TEXT NOT NULL DEFAULT '',
                    browser_family TEXT NOT NULL DEFAULT '',
                    device_type TEXT NOT NULL DEFAULT '',
                    os_family TEXT NOT NULL DEFAULT '',
                    first_referrer_host TEXT NOT NULL DEFAULT '',
                    last_path TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS usage_sessions (
                    session_hash TEXT PRIMARY KEY,
                    visitor_hash TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    event_count INTEGER NOT NULL DEFAULT 0,
                    network_hash TEXT NOT NULL DEFAULT '',
                    city TEXT NOT NULL DEFAULT '',
                    region TEXT NOT NULL DEFAULT '',
                    country TEXT NOT NULL DEFAULT '',
                    browser_family TEXT NOT NULL DEFAULT '',
                    device_type TEXT NOT NULL DEFAULT '',
                    os_family TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY (visitor_hash) REFERENCES usage_visitors(visitor_hash) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS usage_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    visitor_hash TEXT NOT NULL,
                    session_hash TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    module TEXT NOT NULL,
                    action TEXT NOT NULL,
                    path TEXT NOT NULL DEFAULT '',
                    simulation_uf TEXT NOT NULL DEFAULT '',
                    simulation_city TEXT NOT NULL DEFAULT '',
                    horizon_years INTEGER,
                    km_year INTEGER,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    result_code TEXT NOT NULL DEFAULT '',
                    access_network TEXT NOT NULL DEFAULT '',
                    access_city TEXT NOT NULL DEFAULT '',
                    access_region TEXT NOT NULL DEFAULT '',
                    access_country TEXT NOT NULL DEFAULT '',
                    access_browser TEXT NOT NULL DEFAULT '',
                    access_device TEXT NOT NULL DEFAULT '',
                    access_os TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY (visitor_hash) REFERENCES usage_visitors(visitor_hash) ON DELETE CASCADE,
                    FOREIGN KEY (session_hash) REFERENCES usage_sessions(session_hash) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS usage_event_vehicles (
                    event_id INTEGER NOT NULL,
                    position INTEGER NOT NULL,
                    role TEXT NOT NULL DEFAULT '',
                    vehicle_key TEXT NOT NULL DEFAULT '',
                    vehicle_type TEXT NOT NULL DEFAULT '',
                    codigo_fipe TEXT NOT NULL DEFAULT '',
                    codigo_marca TEXT NOT NULL DEFAULT '',
                    codigo_modelo TEXT NOT NULL DEFAULT '',
                    codigo_ano TEXT NOT NULL DEFAULT '',
                    marca TEXT NOT NULL DEFAULT '',
                    modelo TEXT NOT NULL DEFAULT '',
                    ano_modelo TEXT NOT NULL DEFAULT '',
                    combustivel TEXT NOT NULL DEFAULT '',
                    technology TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (event_id, position),
                    FOREIGN KEY (event_id) REFERENCES usage_events(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS usage_event_dedupe (
                    dedupe_key TEXT PRIMARY KEY,
                    event_id INTEGER,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (event_id) REFERENCES usage_events(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_curve_requests_status_last
                    ON curve_requests(status, last_requested_at DESC);
                CREATE INDEX IF NOT EXISTS idx_usage_events_when
                    ON usage_events(occurred_at DESC, id DESC);
                CREATE INDEX IF NOT EXISTS idx_usage_events_module_action_when
                    ON usage_events(module, action, occurred_at DESC);
                CREATE INDEX IF NOT EXISTS idx_usage_events_visitor_when
                    ON usage_events(visitor_hash, occurred_at DESC);
                CREATE INDEX IF NOT EXISTS idx_usage_event_vehicles_key
                    ON usage_event_vehicles(vehicle_key, event_id);
                CREATE INDEX IF NOT EXISTS idx_usage_visitors_last
                    ON usage_visitors(last_seen_at DESC);
                CREATE INDEX IF NOT EXISTS idx_usage_sessions_visitor
                    ON usage_sessions(visitor_hash, started_at DESC);
                """
            )

            # V50.17 — migração compatível do banco V50.06–V50.16. A partir
            # desta versão o contexto coarse de acesso e o código S/D/F ficam
            # congelados no próprio evento. Isso impede que uma alteração
            # posterior da sessão faça uma pesquisa antiga "mudar de cidade"
            # no painel administrativo.
            event_columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(usage_events)").fetchall()
            }
            required_event_columns = {
                "result_code": "TEXT NOT NULL DEFAULT ''",
                "access_network": "TEXT NOT NULL DEFAULT ''",
                "access_city": "TEXT NOT NULL DEFAULT ''",
                "access_region": "TEXT NOT NULL DEFAULT ''",
                "access_country": "TEXT NOT NULL DEFAULT ''",
                "access_browser": "TEXT NOT NULL DEFAULT ''",
                "access_device": "TEXT NOT NULL DEFAULT ''",
                "access_os": "TEXT NOT NULL DEFAULT ''",
            }
            added_columns: set[str] = set()
            for column, definition in required_event_columns.items():
                if column not in event_columns:
                    connection.execute(f"ALTER TABLE usage_events ADD COLUMN {column} {definition}")
                    added_columns.add(column)

            if added_columns.intersection({
                "access_network", "access_city", "access_region", "access_country",
                "access_browser", "access_device", "access_os",
            }):
                connection.execute(
                    """
                    UPDATE usage_events
                    SET access_network = COALESCE(NULLIF(access_network, ''), (SELECT s.network_hash FROM usage_sessions s WHERE s.session_hash=usage_events.session_hash), ''),
                        access_city = COALESCE(NULLIF(access_city, ''), (SELECT s.city FROM usage_sessions s WHERE s.session_hash=usage_events.session_hash), ''),
                        access_region = COALESCE(NULLIF(access_region, ''), (SELECT s.region FROM usage_sessions s WHERE s.session_hash=usage_events.session_hash), ''),
                        access_country = COALESCE(NULLIF(access_country, ''), (SELECT s.country FROM usage_sessions s WHERE s.session_hash=usage_events.session_hash), ''),
                        access_browser = COALESCE(NULLIF(access_browser, ''), (SELECT s.browser_family FROM usage_sessions s WHERE s.session_hash=usage_events.session_hash), ''),
                        access_device = COALESCE(NULLIF(access_device, ''), (SELECT s.device_type FROM usage_sessions s WHERE s.session_hash=usage_events.session_hash), ''),
                        access_os = COALESCE(NULLIF(access_os, ''), (SELECT s.os_family FROM usage_sessions s WHERE s.session_hash=usage_events.session_hash), '')
                    """
                )

            if "result_code" in added_columns:
                rows = connection.execute(
                    "SELECT id, metadata_json FROM usage_events WHERE result_code = ''"
                ).fetchall()
                for row in rows:
                    try:
                        metadata = json.loads(str(row["metadata_json"] or "{}"))
                    except Exception:
                        metadata = {}
                    code = _result_code_from_metadata(metadata)
                    if code:
                        connection.execute(
                            "UPDATE usage_events SET result_code=? WHERE id=?",
                            (code, int(row["id"])),
                        )

            connection.executescript(
                """
                CREATE INDEX IF NOT EXISTS idx_usage_events_result_code_when
                    ON usage_events(result_code, occurred_at DESC);
                CREATE INDEX IF NOT EXISTS idx_usage_events_access_location_when
                    ON usage_events(access_region, access_city, occurred_at DESC);
                CREATE INDEX IF NOT EXISTS idx_usage_event_vehicles_brand
                    ON usage_event_vehicles(marca, event_id);
                CREATE INDEX IF NOT EXISTS idx_usage_event_vehicles_technology
                    ON usage_event_vehicles(technology, event_id);
                CREATE INDEX IF NOT EXISTS idx_usage_event_vehicles_fipe
                    ON usage_event_vehicles(codigo_fipe, event_id);
                """
            )

            # Backfill idempotente para bases que já possuam resultados S/D/F.
            # Se uma versão antiga tiver duas linhas do mesmo resultado, a mais
            # antiga se torna a referência sem apagar o histórico legado.
            existing_completion_rows = connection.execute(
                """
                SELECT id, result_code, module, action, occurred_at
                FROM usage_events
                WHERE result_code <> '' AND (
                    (module='tco' AND action='simulation_completed') OR
                    (module='depreciacao' AND action='consultation_completed') OR
                    (module='fipe_plus' AND action='consultation_completed')
                )
                ORDER BY id ASC
                """
            ).fetchall()
            for row in existing_completion_rows:
                dedupe_key = f"{row['module']}|{row['action']}|{row['result_code']}"
                connection.execute(
                    "INSERT OR IGNORE INTO usage_event_dedupe(dedupe_key,event_id,created_at) VALUES (?,?,?)",
                    (dedupe_key, int(row["id"]), str(row["occurred_at"] or _utc_now_iso())),
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

    @staticmethod
    def session_hash(session_id: str) -> str:
        return hashlib.sha256(str(session_id or "").encode("utf-8")).hexdigest()

    def _increment_analysis(self, connection: sqlite3.Connection, analysis_type: str, amount: int = 1) -> None:
        if analysis_type not in ANALYSIS_TYPES:
            return
        now = _utc_now_iso()
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

    def record_analysis(self, analysis_type: str, amount: int = 1) -> dict[str, int]:
        analysis_type = str(analysis_type or "").strip().lower()
        if analysis_type not in ANALYSIS_TYPES:
            raise SiteUsageValidationError("Tipo de análise inválido.")
        amount = int(amount or 1)
        if amount < 1 or amount > 1000:
            raise SiteUsageValidationError("Quantidade de análises inválida.")
        with self._connection() as connection:
            self._increment_analysis(connection, analysis_type, amount)
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

    @staticmethod
    def _vehicle_key(payload: dict[str, Any]) -> str:
        codigo_fipe = _normalize_key_part(payload.get("codigo_fipe"))
        codigo_ano = _normalize_key_part(payload.get("codigo_ano") or payload.get("ano_modelo"))
        if codigo_fipe:
            return f"fipe:{codigo_fipe}|ano:{codigo_ano}"
        codigo_modelo = _normalize_key_part(payload.get("codigo_modelo"))
        codigo_marca = _normalize_key_part(payload.get("codigo_marca"))
        if codigo_modelo:
            return f"marca:{codigo_marca}|modelo:{codigo_modelo}|ano:{codigo_ano}"
        marca = _normalize_key_part(payload.get("marca"))
        modelo = _normalize_key_part(payload.get("modelo") or payload.get("nome"))
        return f"nome:{marca}|{modelo}|ano:{codigo_ano}" if (marca or modelo) else ""

    @staticmethod
    def _clean_metadata(metadata: Any) -> str:
        if not isinstance(metadata, dict):
            metadata = {}
        cleaned: dict[str, Any] = {}
        for key, value in list(metadata.items())[:40]:
            safe_key = _clean_text(key, 80)
            if not safe_key:
                continue
            if isinstance(value, bool) or value is None:
                cleaned[safe_key] = value
            elif isinstance(value, (int, float)):
                cleaned[safe_key] = value
            elif isinstance(value, (list, tuple)):
                cleaned[safe_key] = [_clean_text(item, 120) for item in list(value)[:20]]
            else:
                cleaned[safe_key] = _clean_text(value, 300)
        return json.dumps(cleaned, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _serialize_event(row: sqlite3.Row, vehicles: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        try:
            metadata = json.loads(str(row["metadata_json"] or "{}"))
        except Exception:
            metadata = {}
        stored_result_code = str(row["result_code"] or "").strip().upper() if "result_code" in row.keys() else ""
        return {
            "id": int(row["id"]),
            "visitor": str(row["visitor_hash"] or "")[:12],
            "session": str(row["session_hash"] or "")[:12],
            "occurred_at": str(row["occurred_at"] or ""),
            "event_type": str(row["event_type"] or ""),
            "module": str(row["module"] or ""),
            "action": str(row["action"] or ""),
            "path": str(row["path"] or ""),
            "simulation_uf": str(row["simulation_uf"] or ""),
            "simulation_city": str(row["simulation_city"] or ""),
            "access_city": str(row["access_city"] or "") if "access_city" in row.keys() else "",
            "access_region": str(row["access_region"] or "") if "access_region" in row.keys() else "",
            "access_country": str(row["access_country"] or "") if "access_country" in row.keys() else "",
            "browser": str(row["access_browser"] or "") if "access_browser" in row.keys() else "",
            "device": str(row["access_device"] or "") if "access_device" in row.keys() else "",
            "os": str(row["access_os"] or "") if "access_os" in row.keys() else "",
            "network": str(row["access_network"] or "")[:12] if "access_network" in row.keys() else "",
            "horizon_years": row["horizon_years"],
            "km_year": row["km_year"],
            "metadata": metadata,
            "result_code": stored_result_code or str(metadata.get("resultado_codigo") or "").strip().upper(),
            "vehicles": vehicles or [],
        }

    def record_event(
        self,
        *,
        visitor_id: str,
        session_id: str,
        event_type: str,
        module: str,
        action: str,
        request_context: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        vehicles: list[dict[str, Any]] | None = None,
        simulation_uf: str = "",
        simulation_city: str = "",
        horizon_years: Any = None,
        km_year: Any = None,
        analysis_type: str = "",
    ) -> int:
        visitor_id = str(visitor_id or "").strip()
        session_id = str(session_id or "").strip()
        if not visitor_id or not session_id:
            raise SiteUsageValidationError("Identidade de telemetria ausente.", 403)
        event_type = _clean_text(event_type, 40).lower()
        module = _clean_text(module, 40).lower()
        action = _clean_text(action, 80).lower()
        if not event_type or not module or not action:
            raise SiteUsageValidationError("Evento de uso inválido.")
        analysis_type = str(analysis_type or "").strip().lower()
        if analysis_type and analysis_type not in ANALYSIS_TYPES:
            raise SiteUsageValidationError("Tipo de análise inválido.")

        context = request_context if isinstance(request_context, dict) else {}
        visitor_hash = self.visitor_hash(visitor_id)
        session_hash = self.session_hash(session_id)
        now = _utc_now_iso()
        page_view = event_type == "page_view" or action == "page_view"

        try:
            horizon = int(horizon_years) if str(horizon_years or "").strip() else None
        except (TypeError, ValueError):
            horizon = None
        try:
            km = int(float(km_year)) if str(km_year or "").strip() else None
        except (TypeError, ValueError):
            km = None

        fields = {
            "network_hash": _clean_text(context.get("network_hash"), 128),
            "city": _clean_text(context.get("city"), 100),
            "region": _clean_text(context.get("region"), 100),
            "country": _clean_text(context.get("country"), 60),
            "browser_family": _clean_text(context.get("browser_family"), 40),
            "device_type": _clean_text(context.get("device_type"), 30),
            "os_family": _clean_text(context.get("os_family"), 40),
            "referrer_host": _clean_text(context.get("referrer_host"), 180),
            "path": _clean_text(context.get("path"), 240),
        }
        result_code = _result_code_from_metadata(metadata)
        metadata_json = self._clean_metadata(metadata)

        with self._connection() as connection:
            existing_visitor = connection.execute(
                "SELECT visitor_hash FROM usage_visitors WHERE visitor_hash = ?", (visitor_hash,)
            ).fetchone()
            if existing_visitor is None:
                connection.execute(
                    """
                    INSERT INTO usage_visitors(
                        visitor_hash, first_seen_at, last_seen_at, session_count,
                        event_count, page_view_count, network_hash, city, region,
                        country, browser_family, device_type, os_family,
                        first_referrer_host, last_path
                    ) VALUES (?, ?, ?, 0, 0, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        visitor_hash, now, now, fields["network_hash"], fields["city"],
                        fields["region"], fields["country"], fields["browser_family"],
                        fields["device_type"], fields["os_family"], fields["referrer_host"],
                        fields["path"],
                    ),
                )

            existing_session = connection.execute(
                "SELECT session_hash FROM usage_sessions WHERE session_hash = ?", (session_hash,)
            ).fetchone()
            if existing_session is None:
                connection.execute(
                    """
                    INSERT INTO usage_sessions(
                        session_hash, visitor_hash, started_at, last_seen_at, event_count,
                        network_hash, city, region, country, browser_family, device_type, os_family
                    ) VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session_hash, visitor_hash, now, now, fields["network_hash"],
                        fields["city"], fields["region"], fields["country"],
                        fields["browser_family"], fields["device_type"], fields["os_family"],
                    ),
                )
                connection.execute(
                    "UPDATE usage_visitors SET session_count = session_count + 1 WHERE visitor_hash = ?",
                    (visitor_hash,),
                )

            # Uma simulação/consulta concluída corresponde a um snapshot S/D/F
            # único. Se o mesmo POST/JS for reenviado acidentalmente, não deve
            # inflar a inteligência de mercado. Reaberturas históricas e PDFs
            # continuam contabilizados individualmente porque são ações reais.
            dedupe_key = ""
            if result_code and (module, action) in RESULT_COMPLETION_ACTIONS:
                dedupe_key = f"{module}|{action}|{result_code}"
                cursor = connection.execute(
                    "INSERT OR IGNORE INTO usage_event_dedupe(dedupe_key,event_id,created_at) VALUES (?,NULL,?)",
                    (dedupe_key, now),
                )
                if int(cursor.rowcount or 0) == 0:
                    duplicate = connection.execute(
                        "SELECT event_id FROM usage_event_dedupe WHERE dedupe_key=?",
                        (dedupe_key,),
                    ).fetchone()
                    if duplicate is not None and int(duplicate["event_id"] or 0) > 0:
                        return int(duplicate["event_id"])

            cursor = connection.execute(
                """
                INSERT INTO usage_events(
                    visitor_hash, session_hash, occurred_at, event_type, module, action,
                    path, simulation_uf, simulation_city, horizon_years, km_year, metadata_json,
                    result_code, access_network, access_city, access_region, access_country,
                    access_browser, access_device, access_os
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    visitor_hash, session_hash, now, event_type, module, action,
                    fields["path"], _clean_text(simulation_uf, 20), _clean_text(simulation_city, 120),
                    horizon, km, metadata_json, result_code,
                    fields["network_hash"], fields["city"], fields["region"], fields["country"],
                    fields["browser_family"], fields["device_type"], fields["os_family"],
                ),
            )
            event_id = int(cursor.lastrowid)
            if dedupe_key:
                connection.execute(
                    "UPDATE usage_event_dedupe SET event_id=? WHERE dedupe_key=?",
                    (event_id, dedupe_key),
                )

            for position, raw in enumerate((vehicles or [])[:5], start=1):
                if not isinstance(raw, dict):
                    continue
                item = {
                    "role": _clean_text(raw.get("role"), 40),
                    "vehicle_key": self._vehicle_key(raw),
                    "vehicle_type": _clean_text(raw.get("tipo") or raw.get("vehicle_type"), 30),
                    "codigo_fipe": _clean_text(raw.get("codigo_fipe"), 40),
                    "codigo_marca": _clean_text(raw.get("codigo_marca"), 40),
                    "codigo_modelo": _clean_text(raw.get("codigo_modelo"), 40),
                    "codigo_ano": _clean_text(raw.get("codigo_ano"), 60),
                    "marca": _clean_text(raw.get("marca"), 100),
                    "modelo": _clean_text(raw.get("modelo") or raw.get("nome"), 180),
                    "ano_modelo": _clean_text(raw.get("ano_modelo"), 60),
                    "combustivel": _clean_text(raw.get("combustivel"), 80),
                    "technology": _normalize_technology_value(raw.get("tecnologia") or raw.get("technology")),
                }
                connection.execute(
                    """
                    INSERT INTO usage_event_vehicles(
                        event_id, position, role, vehicle_key, vehicle_type, codigo_fipe,
                        codigo_marca, codigo_modelo, codigo_ano, marca, modelo,
                        ano_modelo, combustivel, technology
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event_id, position, item["role"], item["vehicle_key"], item["vehicle_type"],
                        item["codigo_fipe"], item["codigo_marca"], item["codigo_modelo"],
                        item["codigo_ano"], item["marca"], item["modelo"], item["ano_modelo"],
                        item["combustivel"], item["technology"],
                    ),
                )

            connection.execute(
                """
                UPDATE usage_visitors SET
                    last_seen_at = ?, event_count = event_count + 1,
                    page_view_count = page_view_count + ?,
                    network_hash = CASE WHEN ? <> '' THEN ? ELSE network_hash END,
                    city = CASE WHEN ? <> '' THEN ? ELSE city END,
                    region = CASE WHEN ? <> '' THEN ? ELSE region END,
                    country = CASE WHEN ? <> '' THEN ? ELSE country END,
                    browser_family = CASE WHEN ? <> '' THEN ? ELSE browser_family END,
                    device_type = CASE WHEN ? <> '' THEN ? ELSE device_type END,
                    os_family = CASE WHEN ? <> '' THEN ? ELSE os_family END,
                    last_path = CASE WHEN ? <> '' THEN ? ELSE last_path END
                WHERE visitor_hash = ?
                """,
                (
                    now, 1 if page_view else 0,
                    fields["network_hash"], fields["network_hash"],
                    fields["city"], fields["city"], fields["region"], fields["region"],
                    fields["country"], fields["country"], fields["browser_family"], fields["browser_family"],
                    fields["device_type"], fields["device_type"], fields["os_family"], fields["os_family"],
                    fields["path"], fields["path"], visitor_hash,
                ),
            )
            connection.execute(
                """
                UPDATE usage_sessions SET
                    last_seen_at = ?, event_count = event_count + 1,
                    network_hash = CASE WHEN ? <> '' THEN ? ELSE network_hash END,
                    city = CASE WHEN ? <> '' THEN ? ELSE city END,
                    region = CASE WHEN ? <> '' THEN ? ELSE region END,
                    country = CASE WHEN ? <> '' THEN ? ELSE country END
                WHERE session_hash = ?
                """,
                (
                    now, fields["network_hash"], fields["network_hash"], fields["city"], fields["city"],
                    fields["region"], fields["region"], fields["country"], fields["country"], session_hash,
                ),
            )
            if analysis_type:
                self._increment_analysis(connection, analysis_type, 1)
        return event_id

    @staticmethod
    def _normalize_range(start: str = "", end: str = "") -> tuple[str, str]:
        def _normalize(value: str, *, end_of_day: bool) -> str:
            text = str(value or "").strip()
            if not text:
                return ""
            if len(text) == 10:
                text = text + ("T23:59:59.999999+00:00" if end_of_day else "T00:00:00+00:00")
            try:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError as exc:
                raise SiteUsageValidationError("Período de telemetria inválido.") from exc
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc).isoformat()

        return _normalize(start, end_of_day=False), _normalize(end, end_of_day=True)

    @staticmethod
    def _normalize_tz_offset_minutes(value: Any) -> int:
        try:
            offset = int(value or 0)
        except (TypeError, ValueError) as exc:
            raise SiteUsageValidationError("Fuso horário inválido.") from exc
        if offset < -840 or offset > 840:
            raise SiteUsageValidationError("Fuso horário fora do intervalo permitido.")
        return offset

    @staticmethod
    def _range_where(start: str = "", end: str = "", column: str = "occurred_at") -> tuple[str, list[Any]]:
        start, end = SiteUsageService._normalize_range(start, end)
        clauses: list[str] = []
        params: list[Any] = []
        if start:
            clauses.append(f"{column} >= ?")
            params.append(start)
        if end:
            clauses.append(f"{column} <= ?")
            params.append(end)
        return (" AND ".join(clauses), params)

    @staticmethod
    def _market_research_predicate(alias: str = "e") -> str:
        return (
            f"(({alias}.module='tco' AND {alias}.action='simulation_completed') "
            f"OR ({alias}.module='depreciacao' AND {alias}.action='consultation_completed') "
            f"OR ({alias}.module='fipe_plus' AND {alias}.action='consultation_completed'))"
        )

    @staticmethod
    def _technology_filter_values(value: Any) -> tuple[str, ...]:
        normalized = _normalize_technology_value(value)
        aliases = {
            "bev": ("bev", "ev_puro", "ev", "eletrico", "eletrica"),
            "phev": ("phev", "plug_in", "plugin", "hibrido_plugin", "hibrido_plug_in"),
            "hev": ("hev", "mhev", "hev_nao_plugin", "hibrido", "hibrida", "hybrid"),
            "icev": ("icev", "ice", "combustao", "termico", "termica"),
            "ve": ("ve",),
        }
        return aliases.get(normalized, (normalized,)) if normalized else ()

    @classmethod
    def _event_filter_where(
        cls,
        *,
        start: str = "",
        end: str = "",
        activity: str = "",
        vehicle: str = "",
        technology: str = "",
        brand: str = "",
        access_location: str = "",
        simulation_location: str = "",
        environment: str = "",
        result_code: str = "",
        visitor: str = "",
        module: str = "",
        alias: str = "e",
    ) -> tuple[str, list[Any]]:
        where, params = cls._range_where(start, end, column=f"{alias}.occurred_at")
        clauses = [where] if where else []

        activity = _clean_text(activity, 40).lower().replace("+", "_")
        if activity in {"tco", "depreciacao", "fipe_plus", "resultado", "home"}:
            clauses.append(f"{alias}.module = ?")
            params.append(activity)
        elif activity == "pdf":
            clauses.append(f"{alias}.action = 'pdf_exported'")
        elif activity in {"pesquisas", "research", "consultas"}:
            clauses.append(cls._market_research_predicate(alias))

        module = _clean_text(module, 40).lower().replace("+", "_")
        if module:
            clauses.append(f"{alias}.module = ?")
            params.append(module)

        visitor = re.sub(r"[^a-fA-F0-9]", "", str(visitor or ""))[:64].lower()
        if visitor:
            clauses.append(f"lower({alias}.visitor_hash) LIKE ?")
            params.append(visitor + "%")

        vehicle = _clean_text(vehicle, 180).lower()
        if vehicle:
            clauses.append(
                f"EXISTS (SELECT 1 FROM usage_event_vehicles vf WHERE vf.event_id={alias}.id "
                "AND lower(vf.marca || ' ' || vf.modelo || ' ' || vf.codigo_fipe || ' ' || vf.ano_modelo) LIKE ?)"
            )
            params.append(f"%{vehicle}%")

        brand = _clean_text(brand, 100).lower()
        if brand:
            clauses.append(
                f"EXISTS (SELECT 1 FROM usage_event_vehicles vf WHERE vf.event_id={alias}.id AND lower(vf.marca) LIKE ?)"
            )
            params.append(f"%{brand}%")

        technology_values = cls._technology_filter_values(technology)
        if technology_values:
            placeholders = ",".join("?" for _ in technology_values)
            clauses.append(
                f"EXISTS (SELECT 1 FROM usage_event_vehicles vf WHERE vf.event_id={alias}.id "
                f"AND lower(vf.technology) IN ({placeholders}))"
            )
            params.extend(technology_values)

        access_location = _clean_text(access_location, 120).lower()
        if access_location:
            clauses.append(
                f"lower(COALESCE(NULLIF({alias}.access_city,''), (SELECT sf.city FROM usage_sessions sf WHERE sf.session_hash={alias}.session_hash), '') || ' ' || "
                f"COALESCE(NULLIF({alias}.access_region,''), (SELECT sf.region FROM usage_sessions sf WHERE sf.session_hash={alias}.session_hash), '') || ' ' || "
                f"COALESCE(NULLIF({alias}.access_country,''), (SELECT sf.country FROM usage_sessions sf WHERE sf.session_hash={alias}.session_hash), '')) LIKE ?"
            )
            params.append(f"%{access_location}%")

        simulation_location = _clean_text(simulation_location, 120).lower()
        if simulation_location:
            clauses.append(f"lower({alias}.simulation_city || ' ' || {alias}.simulation_uf) LIKE ?")
            params.append(f"%{simulation_location}%")

        environment = _clean_text(environment, 160).lower()
        if environment:
            clauses.append(
                f"(lower({alias}.visitor_hash) LIKE ? OR lower("
                f"COALESCE(NULLIF({alias}.access_network,''), (SELECT sf.network_hash FROM usage_sessions sf WHERE sf.session_hash={alias}.session_hash), '') || ' ' || "
                f"COALESCE(NULLIF({alias}.access_browser,''), (SELECT sf.browser_family FROM usage_sessions sf WHERE sf.session_hash={alias}.session_hash), '') || ' ' || "
                f"COALESCE(NULLIF({alias}.access_device,''), (SELECT sf.device_type FROM usage_sessions sf WHERE sf.session_hash={alias}.session_hash), '') || ' ' || "
                f"COALESCE(NULLIF({alias}.access_os,''), (SELECT sf.os_family FROM usage_sessions sf WHERE sf.session_hash={alias}.session_hash), '')"
                ") LIKE ?)"
            )
            params.extend((f"{environment}%", f"%{environment}%"))

        result_code = _clean_text(result_code, 40).upper()
        if result_code:
            # V50.17 grava o identificador em coluna própria e mantém fallback
            # ao JSON apenas para bancos legados que ainda não foram migrados.
            clauses.append(
                f"(upper(COALESCE({alias}.result_code,'')) LIKE ? OR upper({alias}.metadata_json) LIKE ?)"
            )
            params.extend((f"%{result_code}%", f"%\"RESULTADO_CODIGO\":\"%{result_code}%"))

        return (" AND ".join(clauses), params)

    def list_events(
        self,
        *,
        start: str = "",
        end: str = "",
        module: str = "",
        visitor: str = "",
        activity: str = "",
        vehicle: str = "",
        technology: str = "",
        brand: str = "",
        access_location: str = "",
        simulation_location: str = "",
        environment: str = "",
        result_code: str = "",
        offset: int = 0,
        limit: int = 200,
    ) -> dict[str, Any]:
        where, params = self._event_filter_where(
            start=start, end=end, module=module, visitor=visitor, activity=activity,
            vehicle=vehicle, technology=technology, brand=brand,
            access_location=access_location, simulation_location=simulation_location,
            environment=environment, result_code=result_code, alias="e",
        )
        sql_where = f"WHERE {where}" if where else ""
        offset = max(0, int(offset or 0))
        limit = min(1000, max(1, int(limit or 200)))
        with self._connection() as connection:
            rows = connection.execute(
                f"""
                SELECT e.*, s.country AS access_country_legacy, s.browser_family AS access_browser_legacy,
                       s.device_type AS access_device_legacy, s.os_family AS access_os_legacy,
                       s.network_hash AS access_network_legacy,
                       COALESCE(NULLIF(e.access_city,''), s.city, '') AS event_access_city,
                       COALESCE(NULLIF(e.access_region,''), s.region, '') AS event_access_region,
                       COALESCE(NULLIF(e.access_country,''), s.country, '') AS event_access_country,
                       COALESCE(NULLIF(e.access_browser,''), s.browser_family, '') AS event_access_browser,
                       COALESCE(NULLIF(e.access_device,''), s.device_type, '') AS event_access_device,
                       COALESCE(NULLIF(e.access_os,''), s.os_family, '') AS event_access_os,
                       COALESCE(NULLIF(e.access_network,''), s.network_hash, '') AS event_access_network
                FROM usage_events e
                LEFT JOIN usage_sessions s ON s.session_hash=e.session_hash
                {sql_where}
                ORDER BY e.occurred_at DESC, e.id DESC LIMIT ? OFFSET ?
                """,
                (*params, limit, offset),
            ).fetchall()
            total_row = connection.execute(
                f"SELECT COUNT(*) AS total FROM usage_events e {sql_where}", params
            ).fetchone()
            event_ids = [int(row["id"]) for row in rows]
            vehicle_map: dict[int, list[dict[str, Any]]] = {event_id: [] for event_id in event_ids}
            if event_ids:
                placeholders = ",".join("?" for _ in event_ids)
                vrows = connection.execute(
                    f"SELECT * FROM usage_event_vehicles WHERE event_id IN ({placeholders}) ORDER BY event_id, position",
                    event_ids,
                ).fetchall()
                for v in vrows:
                    vehicle_map[int(v["event_id"])].append({
                        "role": str(v["role"] or ""),
                        "vehicle_key": str(v["vehicle_key"] or ""),
                        "vehicle_type": str(v["vehicle_type"] or ""),
                        "codigo_fipe": str(v["codigo_fipe"] or ""),
                        "codigo_marca": str(v["codigo_marca"] or ""),
                        "codigo_modelo": str(v["codigo_modelo"] or ""),
                        "codigo_ano": str(v["codigo_ano"] or ""),
                        "marca": str(v["marca"] or ""),
                        "modelo": str(v["modelo"] or ""),
                        "ano_modelo": str(v["ano_modelo"] or ""),
                        "combustivel": str(v["combustivel"] or ""),
                        "technology": str(v["technology"] or ""),
                    })
        items = []
        for row in rows:
            item = self._serialize_event(row, vehicle_map.get(int(row["id"]), []))
            item.update({
                "access_city": str(row["event_access_city"] or ""),
                "access_region": str(row["event_access_region"] or ""),
                "access_country": str(row["event_access_country"] or ""),
                "browser": str(row["event_access_browser"] or ""),
                "device": str(row["event_access_device"] or ""),
                "os": str(row["event_access_os"] or ""),
                "network": str(row["event_access_network"] or "")[:12],
            })
            items.append(item)
        total = int(total_row["total"] if total_row else 0)
        return {"events": items, "total": total, "offset": offset, "limit": limit, "has_more": offset + len(items) < total}

    def get_event_detail(self, event_id: int) -> dict[str, Any] | None:
        """Retorna um evento administrativo completo sem expor IP bruto.

        O detalhe usa o contexto técnico coarse já persistido na sessão (hash de
        rede, navegador, dispositivo e sistema operacional) e os veículos
        associados ao evento. Nenhum dado novo é coletado por esta consulta.
        """
        try:
            event_id = int(event_id)
        except (TypeError, ValueError):
            return None
        if event_id <= 0:
            return None

        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT e.*,
                       COALESCE(NULLIF(e.access_city,''), s.city, '') AS event_access_city,
                       COALESCE(NULLIF(e.access_region,''), s.region, '') AS event_access_region,
                       COALESCE(NULLIF(e.access_country,''), s.country, '') AS event_access_country,
                       COALESCE(NULLIF(e.access_browser,''), s.browser_family, '') AS event_access_browser,
                       COALESCE(NULLIF(e.access_device,''), s.device_type, '') AS event_access_device,
                       COALESCE(NULLIF(e.access_os,''), s.os_family, '') AS event_access_os,
                       COALESCE(NULLIF(e.access_network,''), s.network_hash, '') AS event_access_network
                FROM usage_events e
                LEFT JOIN usage_sessions s ON s.session_hash=e.session_hash
                WHERE e.id = ?
                """,
                (event_id,),
            ).fetchone()
            if row is None:
                return None
            vrows = connection.execute(
                "SELECT * FROM usage_event_vehicles WHERE event_id = ? ORDER BY position",
                (event_id,),
            ).fetchall()

        vehicles = [{
            "role": str(v["role"] or ""),
            "vehicle_key": str(v["vehicle_key"] or ""),
            "vehicle_type": str(v["vehicle_type"] or ""),
            "codigo_fipe": str(v["codigo_fipe"] or ""),
            "codigo_marca": str(v["codigo_marca"] or ""),
            "codigo_modelo": str(v["codigo_modelo"] or ""),
            "codigo_ano": str(v["codigo_ano"] or ""),
            "marca": str(v["marca"] or ""),
            "modelo": str(v["modelo"] or ""),
            "ano_modelo": str(v["ano_modelo"] or ""),
            "combustivel": str(v["combustivel"] or ""),
            "technology": str(v["technology"] or ""),
        } for v in vrows]
        item = self._serialize_event(row, vehicles)
        item.update({
            "access_city": str(row["event_access_city"] or ""),
            "access_region": str(row["event_access_region"] or ""),
            "access_country": str(row["event_access_country"] or ""),
            "browser": str(row["event_access_browser"] or ""),
            "device": str(row["event_access_device"] or ""),
            "os": str(row["event_access_os"] or ""),
            "network": str(row["event_access_network"] or "")[:12],
        })
        return item

    def list_visitors(
        self,
        *,
        start: str = "", end: str = "",
        activity: str = "", vehicle: str = "", technology: str = "", brand: str = "",
        access_location: str = "", simulation_location: str = "", environment: str = "",
        result_code: str = "", visitor: str = "",
        offset: int = 0, limit: int = 200,
    ) -> dict[str, Any]:
        event_where, event_params = self._event_filter_where(
            start=start, end=end, activity=activity, vehicle=vehicle, technology=technology,
            brand=brand, access_location=access_location, simulation_location=simulation_location,
            environment=environment, result_code=result_code, visitor=visitor, alias="e",
        )
        sql_where = f"WHERE {event_where}" if event_where else ""
        offset = max(0, int(offset or 0))
        limit = min(1000, max(1, int(limit or 200)))
        with self._connection() as connection:
            rows = connection.execute(
                f"""
                WITH filtered AS (
                    SELECT e.* FROM usage_events e {sql_where}
                ), period AS (
                    SELECT e.visitor_hash, COUNT(*) AS period_events,
                           COUNT(DISTINCT e.session_hash) AS period_sessions,
                           MIN(e.occurred_at) AS period_first_seen,
                           MAX(e.occurred_at) AS period_last_seen,
                           SUM(CASE WHEN {self._market_research_predicate('e')} THEN 1 ELSE 0 END) AS period_researches
                    FROM filtered e GROUP BY e.visitor_hash
                ), latest AS (
                    SELECT visitor_hash, access_network, access_city, access_region, access_country,
                           access_browser, access_device, access_os, path,
                           ROW_NUMBER() OVER (PARTITION BY visitor_hash ORDER BY occurred_at DESC, id DESC) AS rn
                    FROM filtered
                )
                SELECT v.*, p.period_events, p.period_sessions,
                       p.period_first_seen, p.period_last_seen, p.period_researches,
                       l.access_network AS period_network, l.access_city AS period_city,
                       l.access_region AS period_region, l.access_country AS period_country,
                       l.access_browser AS period_browser, l.access_device AS period_device,
                       l.access_os AS period_os, l.path AS period_path
                FROM usage_visitors v
                JOIN period p ON p.visitor_hash=v.visitor_hash
                LEFT JOIN latest l ON l.visitor_hash=v.visitor_hash AND l.rn=1
                ORDER BY p.period_last_seen DESC
                LIMIT ? OFFSET ?
                """,
                (*event_params, limit, offset),
            ).fetchall()
            total_row = connection.execute(
                f"SELECT COUNT(DISTINCT e.visitor_hash) AS total FROM usage_events e {sql_where}",
                event_params,
            ).fetchone()
        items = [{
            "visitor": str(row["visitor_hash"] or "")[:12],
            "network": str(row["period_network"] or row["network_hash"] or "")[:12],
            "first_seen_at": str(row["first_seen_at"] or ""),
            "last_seen_at": str(row["last_seen_at"] or ""),
            "sessions": int(row["session_count"] or 0),
            "events": int(row["event_count"] or 0),
            "page_views": int(row["page_view_count"] or 0),
            "period_sessions": int(row["period_sessions"] or 0),
            "period_events": int(row["period_events"] or 0),
            "period_researches": int(row["period_researches"] or 0),
            "period_first_seen": str(row["period_first_seen"] or ""),
            "period_last_seen": str(row["period_last_seen"] or ""),
            "city": str(row["period_city"] or row["city"] or ""),
            "region": str(row["period_region"] or row["region"] or ""),
            "country": str(row["period_country"] or row["country"] or ""),
            "browser": str(row["period_browser"] or row["browser_family"] or ""),
            "device": str(row["period_device"] or row["device_type"] or ""),
            "os": str(row["period_os"] or row["os_family"] or ""),
            "last_path": str(row["period_path"] or row["last_path"] or ""),
        } for row in rows]
        total = int(total_row["total"] if total_row else 0)
        return {"visitors": items, "total": total, "offset": offset, "limit": limit, "has_more": offset + len(items) < total}

    def telemetry_summary(
        self,
        *,
        start: str = "", end: str = "", tz_offset_minutes: int = 0,
        activity: str = "", vehicle: str = "", technology: str = "", brand: str = "",
        access_location: str = "", simulation_location: str = "", environment: str = "",
        result_code: str = "", visitor: str = "",
    ) -> dict[str, Any]:
        where, params = self._event_filter_where(
            start=start, end=end, activity=activity, vehicle=vehicle, technology=technology,
            brand=brand, access_location=access_location, simulation_location=simulation_location,
            environment=environment, result_code=result_code, visitor=visitor, alias="e",
        )
        tz_offset_minutes = self._normalize_tz_offset_minutes(tz_offset_minutes)
        tz_modifier = f"{tz_offset_minutes:+d} minutes"
        event_where = f"WHERE {where}" if where else ""
        research_predicate = self._market_research_predicate("e")
        research_where = f"WHERE {where} AND {research_predicate}" if where else f"WHERE {research_predicate}"
        with self._connection() as connection:
            counts = connection.execute(
                f"""
                SELECT COUNT(*) AS events,
                       COUNT(DISTINCT e.visitor_hash) AS visitors,
                       COUNT(DISTINCT e.session_hash) AS sessions,
                       SUM(CASE WHEN e.event_type='page_view' THEN 1 ELSE 0 END) AS page_views,
                       SUM(CASE WHEN e.module='tco' AND e.action='simulation_completed' THEN 1 ELSE 0 END) AS tco_simulations,
                       SUM(CASE WHEN e.module='depreciacao' AND e.action='consultation_completed' THEN 1 ELSE 0 END) AS depreciation_consultations,
                       SUM(CASE WHEN e.module='fipe_plus' AND e.action='consultation_completed' THEN 1 ELSE 0 END) AS fipe_plus_consultations,
                       SUM(CASE WHEN e.action='pdf_exported' THEN 1 ELSE 0 END) AS pdf_exports,
                       SUM(CASE WHEN e.module='resultado' AND e.action='historical_result_opened' THEN 1 ELSE 0 END) AS historical_result_opens,
                       SUM(CASE WHEN {research_predicate} THEN 1 ELSE 0 END) AS researches
                FROM usage_events e {event_where}
                """, params
            ).fetchone()

            top_vehicles = connection.execute(
                f"""
                SELECT v.vehicle_key, v.codigo_fipe, v.marca, v.modelo, v.ano_modelo,
                       MAX(v.technology) AS technology,
                       COUNT(*) AS uses, COUNT(DISTINCT e.visitor_hash) AS visitors,
                       SUM(CASE WHEN e.module='tco' THEN 1 ELSE 0 END) AS tco,
                       SUM(CASE WHEN e.module='depreciacao' THEN 1 ELSE 0 END) AS depreciacao,
                       SUM(CASE WHEN e.module='fipe_plus' THEN 1 ELSE 0 END) AS fipe_plus
                FROM usage_event_vehicles v
                JOIN usage_events e ON e.id=v.event_id
                {research_where}
                GROUP BY v.vehicle_key, v.codigo_fipe, v.marca, v.modelo, v.ano_modelo
                ORDER BY uses DESC, visitors DESC, v.modelo ASC
                LIMIT 30
                """, params
            ).fetchall()

            trend = connection.execute(
                f"""
                SELECT strftime('%Y-%m-%d', e.occurred_at, ?) AS day,
                       COUNT(DISTINCT e.visitor_hash) AS visitors, COUNT(*) AS events,
                       SUM(CASE WHEN {research_predicate} THEN 1 ELSE 0 END) AS researches,
                       SUM(CASE WHEN e.module='tco' AND e.action='simulation_completed' THEN 1 ELSE 0 END) AS tco,
                       SUM(CASE WHEN e.module='depreciacao' AND e.action='consultation_completed' THEN 1 ELSE 0 END) AS depreciacao,
                       SUM(CASE WHEN e.module='fipe_plus' AND e.action='consultation_completed' THEN 1 ELSE 0 END) AS fipe_plus
                FROM usage_events e {event_where}
                GROUP BY day ORDER BY day ASC
                """, (tz_modifier, *params)
            ).fetchall()

            depreciation_curve_types = connection.execute(
                f"""
                SELECT
                    SUM(CASE WHEN e.module='depreciacao' AND e.action='consultation_completed' AND (
                        e.metadata_json LIKE '%\"tipo_curva\":\"similaridade\"%' OR lower(e.metadata_json) LIKE '%similaridade%'
                    ) THEN 1 ELSE 0 END) AS similaridade,
                    SUM(CASE WHEN e.module='depreciacao' AND e.action='consultation_completed' AND
                        e.metadata_json LIKE '%\"tipo_curva\":\"propria\"%' THEN 1 ELSE 0 END) AS propria,
                    SUM(CASE WHEN e.module='depreciacao' AND e.action='consultation_completed' AND
                        e.metadata_json NOT LIKE '%\"tipo_curva\":\"similaridade\"%' AND
                        e.metadata_json NOT LIKE '%\"tipo_curva\":\"propria\"%' AND
                        lower(e.metadata_json) NOT LIKE '%similaridade%' THEN 1 ELSE 0 END) AS nao_informado
                FROM usage_events e {event_where}
                """, params
            ).fetchone()

            top_pairs = connection.execute(
                f"""
                SELECT v1.vehicle_key AS key1, v1.codigo_fipe AS fipe1, v1.modelo AS modelo1, v1.marca AS marca1,
                       v2.vehicle_key AS key2, v2.codigo_fipe AS fipe2, v2.modelo AS modelo2, v2.marca AS marca2,
                       COUNT(*) AS uses, COUNT(DISTINCT e.visitor_hash) AS visitors
                FROM usage_events e
                JOIN usage_event_vehicles v1 ON v1.event_id=e.id AND v1.position=1
                JOIN usage_event_vehicles v2 ON v2.event_id=e.id AND v2.position=2
                {event_where + (' AND ' if event_where else 'WHERE ')}e.module='tco' AND e.action='simulation_completed'
                GROUP BY v1.vehicle_key, v1.codigo_fipe, v1.modelo, v1.marca, v2.vehicle_key, v2.codigo_fipe, v2.modelo, v2.marca
                ORDER BY uses DESC, visitors DESC, modelo1 ASC, modelo2 ASC
                LIMIT 30
                """, params
            ).fetchall()

            simulation_locations = connection.execute(
                f"""
                SELECT e.simulation_uf AS uf, e.simulation_city AS city, COUNT(*) AS uses,
                       COUNT(DISTINCT e.visitor_hash) AS visitors
                FROM usage_events e
                {research_where + (' AND ' if research_where else 'WHERE ')}e.simulation_city <> ''
                GROUP BY e.simulation_uf, e.simulation_city
                ORDER BY uses DESC, visitors DESC, city ASC LIMIT 30
                """, params
            ).fetchall()

            access_locations = connection.execute(
                f"""
                SELECT e.access_region AS region, e.access_city AS city, e.access_country AS country,
                       COUNT(DISTINCT e.visitor_hash) AS visitors, COUNT(*) AS events,
                       SUM(CASE WHEN {research_predicate} THEN 1 ELSE 0 END) AS researches
                FROM usage_events e
                {event_where + (' AND ' if event_where else 'WHERE ')}(e.access_city <> '' OR e.access_region <> '' OR e.access_country <> '')
                GROUP BY e.access_region, e.access_city, e.access_country
                ORDER BY researches DESC, visitors DESC, events DESC, city ASC LIMIT 30
                """, params
            ).fetchall()

            technology_usage = connection.execute(
                f"""
                SELECT CASE lower(v.technology)
                           WHEN 'ev_puro' THEN 'bev' WHEN 'ev' THEN 'bev' WHEN 'eletrico' THEN 'bev' WHEN 'eletrica' THEN 'bev'
                           WHEN 'plug_in' THEN 'phev' WHEN 'plugin' THEN 'phev'
                           WHEN 'hev_nao_plugin' THEN 'hev' WHEN 'mhev' THEN 'hev'
                           WHEN 'combustao' THEN 'icev' WHEN 'ice' THEN 'icev'
                           ELSE lower(v.technology) END AS technology,
                       COUNT(*) AS uses, COUNT(DISTINCT e.visitor_hash) AS visitors
                FROM usage_event_vehicles v JOIN usage_events e ON e.id=v.event_id
                {research_where + (' AND ' if research_where else 'WHERE ')}v.technology <> ''
                GROUP BY technology ORDER BY uses DESC, visitors DESC, technology ASC LIMIT 20
                """, params
            ).fetchall()

            top_brands = connection.execute(
                f"""
                SELECT v.marca, COUNT(*) AS uses, COUNT(DISTINCT e.visitor_hash) AS visitors,
                       SUM(CASE WHEN e.module='tco' THEN 1 ELSE 0 END) AS tco,
                       SUM(CASE WHEN e.module='depreciacao' THEN 1 ELSE 0 END) AS depreciacao,
                       SUM(CASE WHEN e.module='fipe_plus' THEN 1 ELSE 0 END) AS fipe_plus
                FROM usage_event_vehicles v JOIN usage_events e ON e.id=v.event_id
                {research_where + (' AND ' if research_where else 'WHERE ')}v.marca <> ''
                GROUP BY v.marca ORDER BY uses DESC, visitors DESC, v.marca ASC LIMIT 30
                """, params
            ).fetchall()

            top_active_visitors = connection.execute(
                f"""
                WITH filtered AS (
                    SELECT e.* FROM usage_events e {event_where}
                ), ranked AS (
                    SELECT f.*,
                           ROW_NUMBER() OVER (PARTITION BY f.visitor_hash ORDER BY f.occurred_at DESC, f.id DESC) AS rn
                    FROM filtered f
                ), agg AS (
                    SELECT f.visitor_hash, COUNT(*) AS events,
                           COUNT(DISTINCT f.session_hash) AS sessions,
                           SUM(CASE WHEN {self._market_research_predicate('f')} THEN 1 ELSE 0 END) AS researches,
                           MAX(f.occurred_at) AS last_seen
                    FROM filtered f GROUP BY f.visitor_hash
                )
                SELECT a.visitor_hash, r.access_network AS network_hash, r.access_city AS city,
                       r.access_region AS region, r.access_country AS country,
                       r.access_browser AS browser_family, r.access_device AS device_type,
                       r.access_os AS os_family, a.events, a.sessions, a.researches, a.last_seen
                FROM agg a LEFT JOIN ranked r ON r.visitor_hash=a.visitor_hash AND r.rn=1
                ORDER BY a.researches DESC, a.events DESC, a.sessions DESC, a.last_seen DESC LIMIT 30
                """, params
            ).fetchall()

        return {
            "counts": {
                "events": int(counts["events"] or 0), "visitors": int(counts["visitors"] or 0),
                "sessions": int(counts["sessions"] or 0), "page_views": int(counts["page_views"] or 0),
                "tco_simulations": int(counts["tco_simulations"] or 0),
                "depreciation_consultations": int(counts["depreciation_consultations"] or 0),
                "fipe_plus_consultations": int(counts["fipe_plus_consultations"] or 0),
                "pdf_exports": int(counts["pdf_exports"] or 0),
                "historical_result_opens": int(counts["historical_result_opens"] or 0),
                "researches": int(counts["researches"] or 0),
            },
            "top_vehicles": [{
                "vehicle_key": str(row["vehicle_key"] or ""), "codigo_fipe": str(row["codigo_fipe"] or ""),
                "marca": str(row["marca"] or ""), "modelo": str(row["modelo"] or ""),
                "ano_modelo": str(row["ano_modelo"] or ""), "technology": str(row["technology"] or ""),
                "uses": int(row["uses"] or 0), "visitors": int(row["visitors"] or 0),
                "tco": int(row["tco"] or 0), "depreciacao": int(row["depreciacao"] or 0),
                "fipe_plus": int(row["fipe_plus"] or 0),
            } for row in top_vehicles],
            "daily": [{
                "day": str(row["day"] or ""), "visitors": int(row["visitors"] or 0),
                "events": int(row["events"] or 0), "researches": int(row["researches"] or 0),
                "tco": int(row["tco"] or 0), "depreciacao": int(row["depreciacao"] or 0),
                "fipe_plus": int(row["fipe_plus"] or 0),
            } for row in trend],
            "top_pairs": [{
                "vehicle_1": {"key": str(row["key1"] or ""), "codigo_fipe": str(row["fipe1"] or ""), "marca": str(row["marca1"] or ""), "modelo": str(row["modelo1"] or "")},
                "vehicle_2": {"key": str(row["key2"] or ""), "codigo_fipe": str(row["fipe2"] or ""), "marca": str(row["marca2"] or ""), "modelo": str(row["modelo2"] or "")},
                "uses": int(row["uses"] or 0), "visitors": int(row["visitors"] or 0),
            } for row in top_pairs],
            "simulation_locations": [{"uf": str(row["uf"] or ""), "city": str(row["city"] or ""), "uses": int(row["uses"] or 0), "visitors": int(row["visitors"] or 0)} for row in simulation_locations],
            "access_locations": [{
                "region": str(row["region"] or ""), "city": str(row["city"] or ""), "country": str(row["country"] or ""),
                "visitors": int(row["visitors"] or 0), "events": int(row["events"] or 0), "researches": int(row["researches"] or 0),
            } for row in access_locations],
            "technology_usage": [{"technology": str(row["technology"] or ""), "uses": int(row["uses"] or 0), "visitors": int(row["visitors"] or 0)} for row in technology_usage],
            "top_brands": [{
                "marca": str(row["marca"] or ""), "uses": int(row["uses"] or 0), "visitors": int(row["visitors"] or 0),
                "tco": int(row["tco"] or 0), "depreciacao": int(row["depreciacao"] or 0), "fipe_plus": int(row["fipe_plus"] or 0),
            } for row in top_brands],
            "top_active_visitors": [{
                "visitor": str(row["visitor_hash"] or "")[:12], "network": str(row["network_hash"] or "")[:12],
                "city": str(row["city"] or ""), "region": str(row["region"] or ""), "country": str(row["country"] or ""),
                "browser": str(row["browser_family"] or ""), "device": str(row["device_type"] or ""), "os": str(row["os_family"] or ""),
                "events": int(row["events"] or 0), "sessions": int(row["sessions"] or 0),
                "researches": int(row["researches"] or 0), "last_seen": str(row["last_seen"] or ""),
            } for row in top_active_visitors],
            "depreciation_curve_types": {
                "propria": int((depreciation_curve_types or {})["propria"] or 0),
                "similaridade": int((depreciation_curve_types or {})["similaridade"] or 0),
                "nao_informado": int((depreciation_curve_types or {})["nao_informado"] or 0),
            },
            "active_filters": {
                "activity": activity, "vehicle": vehicle, "technology": technology, "brand": brand,
                "access_location": access_location, "simulation_location": simulation_location,
                "environment": environment, "result_code": result_code, "visitor": visitor,
            },
            "timezone_offset_minutes": tz_offset_minutes,
        }

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
            "ano_modelo": _clean_text(payload.get("ano_modelo") or payload.get("ano_modelo_raw") or payload.get("AnoModelo"), 60),
            "combustivel": _clean_text(payload.get("combustivel") or payload.get("Combustivel"), 80),
        }
        if not vehicle["modelo"] and not vehicle["codigo_modelo"]:
            raise SiteUsageValidationError("Selecione um veículo antes de solicitar a curva.")

        visitor_hash = self.visitor_hash(visitor_id)
        now = _utc_now_iso()
        with self._connection() as connection:
            row = connection.execute(
                "SELECT id, status, request_count FROM curve_requests WHERE request_key = ?", (request_key,)
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
                        request_key, vehicle["vehicle_type"], vehicle["codigo_fipe"], vehicle["codigo_marca"],
                        vehicle["codigo_modelo"], vehicle["codigo_ano"], vehicle["marca"], vehicle["modelo"],
                        vehicle["ano_modelo"], vehicle["combustivel"], now, now, now,
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
                        vehicle["vehicle_type"], vehicle["codigo_fipe"], vehicle["codigo_marca"], vehicle["codigo_modelo"],
                        vehicle["codigo_ano"], vehicle["marca"], vehicle["modelo"], vehicle["ano_modelo"],
                        vehicle["combustivel"], request_id,
                    ),
                )

            cursor = connection.execute(
                "INSERT OR IGNORE INTO curve_request_visitors(request_id, visitor_hash, requested_at) VALUES (?, ?, ?)",
                (request_id, visitor_hash, now),
            )
            added = cursor.rowcount > 0
            if added:
                connection.execute(
                    """
                    UPDATE curve_requests SET
                        request_count = request_count + 1,
                        last_requested_at = ?, status = 'pending',
                        status_updated_at = CASE WHEN status <> 'pending' THEN ? ELSE status_updated_at END
                    WHERE id = ?
                    """,
                    (now, now, request_id),
                )

        return {"received": True, "already_requested": not added, "reopened": bool(added and previous_status != "pending")}

    @staticmethod
    def _serialize_request(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": int(row["id"]), "vehicle_type": str(row["vehicle_type"] or ""),
            "codigo_fipe": str(row["codigo_fipe"] or ""), "codigo_marca": str(row["codigo_marca"] or ""),
            "codigo_modelo": str(row["codigo_modelo"] or ""), "codigo_ano": str(row["codigo_ano"] or ""),
            "marca": str(row["marca"] or ""), "modelo": str(row["modelo"] or ""),
            "ano_modelo": str(row["ano_modelo"] or ""), "combustivel": str(row["combustivel"] or ""),
            "request_count": int(row["request_count"] or 0), "status": str(row["status"] or "pending"),
            "first_requested_at": str(row["first_requested_at"] or ""), "last_requested_at": str(row["last_requested_at"] or ""),
            "status_updated_at": str(row["status_updated_at"] or ""),
        }

    def list_curve_requests(self, *, status: str = "all", offset: int = 0, limit: int = 500) -> dict[str, Any]:
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
                SELECT * FROM curve_requests {where}
                ORDER BY CASE status WHEN 'pending' THEN 0 WHEN 'attended' THEN 1 ELSE 2 END,
                         last_requested_at DESC, id DESC LIMIT ? OFFSET ?
                """, (*params, limit, offset),
            ).fetchall()
            total_row = connection.execute(f"SELECT COUNT(*) AS total FROM curve_requests {where}", params).fetchone()
        items = [self._serialize_request(row) for row in rows]
        total = int(total_row["total"] if total_row else 0)
        return {"requests": items, "total": total, "offset": offset, "limit": limit, "has_more": offset + len(items) < total}

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
            row = connection.execute("SELECT * FROM curve_requests WHERE id = ?", (request_id,)).fetchone()
        return self._serialize_request(row) if row is not None else None


@lru_cache(maxsize=4)
def _cached_site_usage_service(database_path: str) -> SiteUsageService:
    return SiteUsageService(database_path)


def get_site_usage_service() -> SiteUsageService:
    from flask import current_app
    return _cached_site_usage_service(str(current_app.config["ARQUIVO_USO_SITE"]))
