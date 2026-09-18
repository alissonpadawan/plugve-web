from __future__ import annotations

import importlib.util
import sqlite3
import sys
import types
from pathlib import Path

from services.auth_repository import AuthRepository, iso_utc
from services.sqlite_migration_backup import create_sqlite_backup_once, verify_sqlite_integrity


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _load_auth_security_without_flask():
    """Carrega apenas helpers puros mesmo no validador sem Flask/Werkzeug."""
    flask_mod = types.ModuleType("flask")
    flask_mod.session = {}
    werkzeug_mod = types.ModuleType("werkzeug")
    werkzeug_security = types.ModuleType("werkzeug.security")
    werkzeug_security.check_password_hash = lambda _hash, _password: False
    werkzeug_security.generate_password_hash = lambda password: f"hash:{password}"
    old = {name: sys.modules.get(name) for name in ("flask", "werkzeug", "werkzeug.security")}
    try:
        sys.modules["flask"] = flask_mod
        sys.modules["werkzeug"] = werkzeug_mod
        sys.modules["werkzeug.security"] = werkzeug_security
        spec = importlib.util.spec_from_file_location("auth_security_v5135_test", ROOT / "services" / "auth_security.py")
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        return module
    finally:
        for name, value in old.items():
            if value is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = value


def test_safe_next_rejects_external_encoded_and_backslash_redirects():
    security = _load_auth_security_without_flask()
    assert security.safe_next_path("/simular?x=1") == "/simular?x=1"
    for unsafe in (
        "https://evil.example/",
        "//evil.example/",
        "/%2f%2fevil.example/",
        "/%255c%255cevil.example/",
        "/\\evil.example",
        "/ok%0d%0aLocation:%20https://evil.example",
    ):
        assert security.safe_next_path(unsafe, fallback="/") == "/"


def _create_user(repo: AuthRepository, *, public_id: str = "u-1", email: str = "u@example.com") -> dict:
    return repo.create_user(
        public_id=public_id,
        full_name="Usuário Teste",
        email_normalized=email,
        password_hash="hash",
        profile_type="profissional",
        institution="",
        course_area="",
        purpose="Teste",
        access_status="email_pending",
        privacy_version="2026-09",
    )


def test_challenge_is_single_use_and_expired_code_cannot_be_consumed(tmp_path: Path):
    repo = AuthRepository(tmp_path / "auth.sqlite3")
    user = _create_user(repo)
    current = repo.create_challenge(
        user_id=user["id"], purpose="email_verification", token_hash="digest",
        ttl_seconds=120, max_attempts=5,
    )
    assert repo.consume_challenge(current["id"]) is True
    assert repo.consume_challenge(current["id"]) is False

    expired = repo.create_challenge(
        user_id=user["id"], purpose="password_reset", token_hash="digest2",
        ttl_seconds=120, max_attempts=5,
    )
    with repo.connection() as con:
        con.execute(
            "UPDATE auth_challenges SET expires_at='2000-01-01T00:00:00Z' WHERE id=?",
            (expired["id"],),
        )
    assert repo.consume_challenge(expired["id"]) is False


def test_rate_limit_and_status_change_are_effective_without_cookie_state(tmp_path: Path):
    repo = AuthRepository(tmp_path / "auth.sqlite3")
    user = _create_user(repo)
    repo.set_status(user["id"], "active")
    repo.create_session(token_hash="tokenhash", user_id=user["id"], ttl_seconds=3600)
    before = repo.get_session_user("tokenhash")
    assert before and before[1]["access_status"] == "active"
    repo.set_status(user["id"], "suspended")
    after = repo.get_session_user("tokenhash")
    assert after and after[1]["access_status"] == "suspended"

    assert repo.rate_limit_hit(scope="login", subject_hash="subject", window_seconds=3600, max_events=2)[0]
    assert repo.rate_limit_hit(scope="login", subject_hash="subject", window_seconds=3600, max_events=2)[0]
    allowed, retry = repo.rate_limit_hit(scope="login", subject_hash="subject", window_seconds=3600, max_events=2)
    assert allowed is False and retry >= 1


def test_sqlite_pre_migration_backup_is_consistent_and_idempotent(tmp_path: Path):
    db = tmp_path / "legacy.sqlite3"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE sample(id INTEGER PRIMARY KEY, value TEXT)")
    con.execute("INSERT INTO sample(value) VALUES ('patrimonio')")
    con.commit()
    con.close()

    first = create_sqlite_backup_once(db, migration_label="v51_35_test")
    second = create_sqlite_backup_once(db, migration_label="v51_35_test")
    assert first == second and first and first.exists()
    verify_sqlite_integrity(first)
    with sqlite3.connect(first) as check:
        assert check.execute("SELECT value FROM sample").fetchone()[0] == "patrimonio"


def test_final_access_control_is_fail_closed_in_production_and_render():
    config = _read("config.py")
    render = _read("render.yaml")
    env = _read(".env.example")
    assert 'CURVE_VERSION = "V51.37"' in config
    assert '_AUTH_DEFAULT = "1" if _is_production_runtime() else "0"' in config
    assert 'key: AUTH_ACCESS_CONTROL_ENABLED' in render and 'value: "1"' in render
    assert 'AUTH_ACCESS_CONTROL_ENABLED=1' in env


def test_global_gate_keeps_only_minimal_public_surface_and_technical_token_surface():
    access = _read("services/auth_access.py")
    assert '"main.index"' in access and '"main.health"' in access
    for protected in (
        "main.consulta_fipe", "main.depreciacao", "tco.simular",
        "main.consultar_resultado", "main.resultado_historico",
        "site_usage.record_public_event", "site_usage.submit_curve_request",
    ):
        assert f'"{protected}"' not in access.split("PUBLIC_ENDPOINTS", 1)[1].split("}", 1)[0]
    for technical in (
        "depreciacao.sincronizar_snapshot_curvas", "fipe.catalogo_estado",
        "site_usage.admin_telemetry_summary", "access_admin.approve_access",
        "tco.contato_admin_messages",
    ):
        assert f'"{technical}"' in access.split("TECHNICAL_ENDPOINTS", 1)[1].split("}", 1)[0]


def test_technical_endpoints_keep_their_own_token_checks():
    auth_admin = _read("routes/auth_admin_routes.py")
    usage = _read("routes/usage_routes.py")
    fipe = _read("routes/fipe_routes.py")
    dep = _read("routes/depreciacao_routes.py")
    tco = _read("routes/tco_routes.py")
    assert "_admin_token_valid" in auth_admin and "X-PlugVE-Admin-Token" in auth_admin
    assert "_admin_token_valid" in usage and "X-PlugVE-Admin-Token" in usage
    assert "_sync_token_valido" in fipe and "X-PlugVE-Sync-Token" in fipe
    assert "_sync_token_valido" in dep and "X-PlugVE-Sync-Token" in dep
    assert "_sobre_admin_token_valido" in tco and "X-PlugVE-Admin-Token" in tco


def test_security_headers_no_store_and_technical_requests_are_stateless():
    app = _read("app.py")
    for header in (
        "X-Content-Type-Options", "X-Frame-Options", "Referrer-Policy",
        "Permissions-Policy", "Strict-Transport-Security",
    ):
        assert header in app
    assert 'response.headers["Cache-Control"] = "private, no-store, max-age=0"' in app
    assert 'response.headers["Vary"]' in app and '"Cookie"' in app
    assert "not endpoint_is_technical()" in app


def test_snapshot_ownership_and_legacy_compatibility_remain_enforced():
    main = _read("routes/main_routes.py")
    snapshots = _read("services/result_snapshot_service.py")
    assert "requester_user_id != owner_user_id" in main
    assert "owner_user_id TEXT" in snapshots
    assert 'str(row["owner_user_id"] or "")' in snapshots
    assert 'migration_label="v51_35_snapshot_owner"' in snapshots


def test_usage_migration_has_backup_and_does_not_infer_legacy_identity():
    usage = _read("services/site_usage_service.py")
    assert 'migration_label="v51_35_usage_schema"' in usage
    assert "nenhuma identidade é inferida" in usage
    assert "ALTER TABLE usage_events ADD COLUMN user_id TEXT" in usage


def test_auth_templates_are_mobile_ready_and_sensitive_forms_have_csrf():
    base = _read("templates/auth/_base.html")
    css = _read("static/css/auth.css")
    assert 'name="viewport" content="width=device-width, initial-scale=1.0"' in base
    assert "@media(max-width:640px)" in css
    for path in (
        "templates/auth/login.html", "templates/auth/register.html",
        "templates/auth/verify_email.html", "templates/auth/forgot_password.html",
        "templates/auth/reset_password.html",
    ):
        assert 'name="csrf_token"' in _read(path)


def test_passwords_and_codes_are_not_written_to_admin_payload_or_audit_schema():
    admin = _read("services/auth_admin_service.py")
    repo = _read("services/auth_repository.py")
    visible = admin.split("ADMIN_VISIBLE_FIELDS", 1)[1].split("}", 1)[0]
    assert "password_hash" not in visible
    assert "token_hash" not in visible
    assert "metadata_json" in repo
