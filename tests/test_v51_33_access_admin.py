import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

try:
    from app import create_app
    from services.auth_service import get_auth_service
except (ModuleNotFoundError, ImportError) as exc:
    detail = f"{getattr(exc, 'name', '')} {exc}".lower()
    if "flask" in detail or "werkzeug" in detail:
        pytest.skip("Flask/Werkzeug indisponível no ambiente de validação", allow_module_level=True)
    raise


@pytest.fixture()
def app_client():
    tmp = tempfile.TemporaryDirectory()
    app = create_app()
    app.config.update(
        TESTING=True,
        SECRET_KEY="stage2-test-secret",
        ARQUIVO_AUTH_USUARIOS=Path(tmp.name) / "auth.sqlite3",
        ARQUIVO_USO_SITE=Path(tmp.name) / "usage.sqlite3",
        ARQUIVO_SOBRE_ENGAJAMENTO=Path(tmp.name) / "sobre.sqlite3",
        ARQUIVO_RESULTADOS=Path(tmp.name) / "snapshots.sqlite3",
        ARQUIVO_MENSAGENS_CONTATO=Path(tmp.name) / "contact.sqlite3",
        AUTH_ACCESS_CONTROL_ENABLED=True,
        AUTH_ENFORCE_IN_TESTS=True,
        AUTH_RATE_REGISTER_MAX=50,
        AUTH_RATE_LOGIN_MAX=50,
        AUTH_RATE_VERIFY_MAX=50,
        AUTH_RATE_RESET_MAX=50,
        PLUGVE_ADMIN_TOKEN="admin-test",
    )
    client = app.test_client()
    yield app, client
    tmp.cleanup()


def _make_pending(app, email="joao@example.com"):
    with app.app_context(), patch("services.auth_service.send_verification_code"):
        service = get_auth_service()
        user, _ = service.register({
            "full_name": "João da Silva", "email": email,
            "password": "senha-segura-123", "password_confirm": "senha-segura-123",
            "profile_type": "professor_ifg", "institution": "IFG", "course_area": "PPGTGS",
            "purpose": "Pesquisa", "privacy_accepted": True,
        }, client_key="admin-stage2")
        return service.repo.set_email_verified(user["id"])


def _headers():
    return {"X-PlugVE-Admin-Token": "admin-test"}


def test_admin_endpoints_require_technical_auth(app_client):
    _, client = app_client
    assert client.get("/api/access/admin/requests").status_code == 401
    assert client.get("/api/access/admin/requests", headers=_headers()).status_code == 200


def test_pending_approval_and_approve_with_email_failure_persists_active(app_client):
    app, client = app_client
    user = _make_pending(app)
    pending = client.get("/api/access/admin/requests", headers=_headers()).get_json()
    assert pending["total"] == 1
    assert pending["items"][0]["access_status"] == "pending_approval"

    with patch("services.auth_admin_service.send_access_approved", side_effect=Exception("smtp down")):
        # Exception genérica não é capturada pelo serviço; usamos erro tipado no teste real abaixo.
        pass
    from services.auth_email_service import AuthEmailDeliveryError
    with patch("services.auth_admin_service.send_access_approved", side_effect=AuthEmailDeliveryError("smtp down")):
        response = client.post(f"/api/access/admin/users/{user['public_id']}/approve", json={}, headers=_headers())
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["user"]["access_status"] == "active"
    assert payload["notification_sent"] is False
    detail = client.get(f"/api/access/admin/users/{user['public_id']}", headers=_headers()).get_json()
    assert detail["user"]["access_status"] == "active"
    assert detail["notifications"][0]["status"] == "failed"


def test_reject_suspend_reactivate_transitions_and_double_approval_safe(app_client):
    app, client = app_client
    user = _make_pending(app, "maria@example.com")
    with patch("services.auth_admin_service.send_access_approved"):
        first = client.post(f"/api/access/admin/users/{user['public_id']}/approve", json={}, headers=_headers())
        second = client.post(f"/api/access/admin/users/{user['public_id']}/approve", json={}, headers=_headers())
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.get_json()["changed"] is False

    suspended = client.post(f"/api/access/admin/users/{user['public_id']}/suspend", json={"note": "teste"}, headers=_headers())
    assert suspended.get_json()["user"]["access_status"] == "suspended"
    reactivated = client.post(f"/api/access/admin/users/{user['public_id']}/reactivate", json={}, headers=_headers())
    assert reactivated.get_json()["user"]["access_status"] == "active"

    rejected_user = _make_pending(app, "ana@example.com")
    with patch("services.auth_admin_service.send_access_rejected"):
        rejected = client.post(f"/api/access/admin/users/{rejected_user['public_id']}/reject", json={}, headers=_headers())
    assert rejected.get_json()["user"]["access_status"] == "rejected"
    invalid = client.post(f"/api/access/admin/users/{rejected_user['public_id']}/reactivate", json={}, headers=_headers())
    assert invalid.status_code == 409
