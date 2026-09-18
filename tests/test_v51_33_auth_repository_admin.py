import tempfile
from pathlib import Path

from services.auth_repository import AuthRepository


def create(repo, public_id, email, status="pending_approval"):
    user = repo.create_user(
        public_id=public_id, full_name="Teste Usuário", email_normalized=email,
        password_hash="hash", profile_type="profissional", institution="Empresa X",
        course_area="Engenharia", purpose="Teste", access_status="email_pending",
        privacy_version="2026-09",
    )
    if status == "pending_approval":
        user = repo.set_email_verified(user["id"])
    elif status != "email_pending":
        user = repo.set_status(user["id"], status)
    return user


def test_admin_repository_listing_atomic_transition_and_notifications():
    with tempfile.TemporaryDirectory() as tmp:
        repo = AuthRepository(Path(tmp) / "auth.sqlite3")
        user = create(repo, "u-1", "user@example.com")
        page = repo.list_users(status="pending_approval")
        assert page["total"] == 1
        assert page["items"][0]["email_normalized"] == "user@example.com"
        updated, changed = repo.transition_status(user["id"], from_statuses=("pending_approval",), to_status="active")
        assert changed is True and updated["access_status"] == "active"
        updated2, changed2 = repo.transition_status(user["id"], from_statuses=("pending_approval",), to_status="active")
        assert changed2 is False and updated2["access_status"] == "active"
        repo.record_notification(user_id=user["id"], notification_type="access_approved", status="failed", error_message="smtp")
        notes = repo.list_notifications(user["id"])
        assert notes[0]["status"] == "failed"
        repo.audit(user_id=user["id"], action="access_approved", metadata={"source": "painel_local"})
        audit = repo.list_audit_log(user["id"])
        assert audit[0]["metadata"]["source"] == "painel_local"
