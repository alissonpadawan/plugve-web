from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTES = (ROOT / "routes" / "auth_admin_routes.py").read_text(encoding="utf-8")
ACCESS = (ROOT / "services" / "auth_access.py").read_text(encoding="utf-8")
SERVICE = (ROOT / "services" / "auth_admin_service.py").read_text(encoding="utf-8")
REPO = (ROOT / "services" / "auth_repository.py").read_text(encoding="utf-8")


def test_admin_routes_cover_stage2_actions():
    for fragment in (
        "/api/access/admin/requests", "/api/access/admin/users",
        "/approve", "/reject", "/suspend", "/reactivate", "/resend-notification",
    ):
        assert fragment in ROUTES


def test_admin_routes_are_exempt_only_for_technical_auth_layer():
    for endpoint in (
        "access_admin.list_access_requests", "access_admin.list_access_users",
        "access_admin.access_user_detail", "access_admin.approve_access",
        "access_admin.reject_access", "access_admin.suspend_access",
        "access_admin.reactivate_access", "access_admin.resend_access_notification",
    ):
        assert endpoint in ACCESS


def test_admin_payload_never_exposes_password_hash():
    assert '"password_hash"' not in SERVICE.split("ADMIN_VISIBLE_FIELDS", 1)[1].split("}", 1)[0]
    assert "auth_notifications" in REPO
    assert "transition_status" in REPO
