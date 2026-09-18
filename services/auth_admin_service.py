from __future__ import annotations

from functools import lru_cache
from typing import Any, Mapping

from flask import current_app

from services.auth_email_service import (
    AuthEmailDeliveryError,
    send_access_approved,
    send_access_rejected,
)
from services.auth_repository import AuthRepository
from services.auth_security import AuthValidationError, clean_single_line
from services.auth_service import ACCESS_STATUSES, PROFILE_TYPES
from services.site_usage_service import SiteUsageService


ADMIN_VISIBLE_FIELDS = {
    "public_id", "full_name", "email_normalized", "profile_type", "institution",
    "course_area", "purpose", "access_status", "email_verified_at", "created_at",
    "requested_at", "approved_at", "rejected_at", "suspended_at", "disabled_at",
    "last_login_at", "privacy_accepted_at", "privacy_version",
}


class AuthAdminService:
    def __init__(self, database_path: str, usage_database_path: str, config: Mapping[str, Any]):
        self.repo = AuthRepository(database_path)
        self.usage = SiteUsageService(usage_database_path)
        self.config = config

    @staticmethod
    def _public_user(user: dict[str, Any] | None) -> dict[str, Any] | None:
        if not user:
            return None
        item = {key: user.get(key) for key in ADMIN_VISIBLE_FIELDS}
        item["profile_label"] = PROFILE_TYPES.get(str(item.get("profile_type") or ""), str(item.get("profile_type") or ""))
        item["email_confirmed"] = bool(item.get("email_verified_at"))
        return item

    def list_users(
        self, *, status: str = "all", query: str = "", profile_type: str = "",
        institution: str = "", offset: int = 0, limit: int = 200,
    ) -> dict[str, Any]:
        page = self.repo.list_users(
            status=status, query=query, profile_type=profile_type, institution=institution,
            offset=offset, limit=limit,
        )
        public_items = [self._public_user(item) for item in page.get("items", [])]
        overview = self.usage.get_user_activity_overview([str((item or {}).get("public_id") or "") for item in public_items])
        for item in public_items:
            if not item:
                continue
            item["activity"] = overview.get(str(item.get("public_id") or ""), {
                "events": 0, "sessions": 0, "last_activity": "", "tco": 0,
                "depreciation": 0, "fipe_plus": 0, "pdf_exports": 0,
            })
        return {**page, "items": public_items}

    def get_user_detail(self, public_id: str) -> dict[str, Any]:
        user = self.repo.get_user_by_public_id(str(public_id or "").strip())
        if not user:
            raise AuthValidationError("Usuário não localizado.", 404)
        public_id = str(user.get("public_id") or "")
        return {
            "user": self._public_user(user),
            "active_sessions": self.repo.count_active_sessions(int(user["id"])),
            "audit_log": self.repo.list_audit_log(int(user["id"]), limit=100),
            "notifications": self.repo.list_notifications(int(user["id"]), limit=30),
            "usage": self.usage.get_user_activity_summary(public_id, timeline_limit=120, top_limit=12),
        }

    def _notification(self, user: dict[str, Any], notification_type: str) -> bool:
        try:
            if notification_type == "access_approved":
                send_access_approved(
                    recipient=str(user["email_normalized"]), full_name=str(user["full_name"]), config=self.config
                )
            elif notification_type == "access_rejected":
                send_access_rejected(
                    recipient=str(user["email_normalized"]), full_name=str(user["full_name"]), config=self.config
                )
            else:
                raise AuthValidationError("Tipo de notificação administrativa inválido.")
        except AuthEmailDeliveryError as exc:
            self.repo.record_notification(
                user_id=int(user["id"]), notification_type=notification_type, status="failed", error_message=str(exc)
            )
            self.repo.audit(
                user_id=int(user["id"]), action=f"{notification_type}_email_failed",
                metadata={"error": str(exc)[:500]},
            )
            return False
        self.repo.record_notification(user_id=int(user["id"]), notification_type=notification_type, status="sent")
        self.repo.audit(user_id=int(user["id"]), action=f"{notification_type}_email_sent")
        return True

    def _transition(
        self, public_id: str, *, expected: tuple[str, ...], target: str, action: str,
        note: str = "", idempotent_target: bool = True,
    ) -> tuple[dict[str, Any], bool]:
        if target not in ACCESS_STATUSES:
            raise AuthValidationError("Status administrativo inválido.")
        user = self.repo.get_user_by_public_id(str(public_id or "").strip())
        if not user:
            raise AuthValidationError("Usuário não localizado.", 404)
        current = str(user.get("access_status") or "")
        if current == target and idempotent_target:
            return user, False
        if current not in expected:
            raise AuthValidationError(
                f"Ação incompatível com o estado atual da conta ({current or 'desconhecido'}).", 409
            )
        updated, changed = self.repo.transition_status(
            int(user["id"]), from_statuses=expected, to_status=target
        )
        if not changed:
            fresh = self.repo.get_user_by_id(int(user["id"]))
            if fresh and str(fresh.get("access_status") or "") == target and idempotent_target:
                return fresh, False
            raise AuthValidationError("A conta foi alterada por outra operação. Atualize a lista e tente novamente.", 409)
        metadata: dict[str, Any] = {"source": "painel_local", "from": current, "to": target}
        note_value = clean_single_line(note, field="Observação administrativa", max_length=500, required=False)
        if note_value:
            metadata["admin_note"] = note_value
        self.repo.audit(user_id=int(user["id"]), action=action, metadata=metadata)
        return updated or self.repo.get_user_by_id(int(user["id"])), True

    def approve(self, public_id: str, *, note: str = "") -> dict[str, Any]:
        user, changed = self._transition(
            public_id, expected=("pending_approval",), target="active", action="access_approved", note=note
        )
        notification_sent = self._notification(user, "access_approved") if changed else None
        return {"user": self._public_user(user), "changed": changed, "notification_sent": notification_sent}

    def reject(self, public_id: str, *, note: str = "") -> dict[str, Any]:
        user, changed = self._transition(
            public_id, expected=("pending_approval",), target="rejected", action="access_rejected", note=note
        )
        notification_sent = self._notification(user, "access_rejected") if changed else None
        return {"user": self._public_user(user), "changed": changed, "notification_sent": notification_sent}

    def suspend(self, public_id: str, *, note: str = "") -> dict[str, Any]:
        user, changed = self._transition(
            public_id, expected=("active",), target="suspended", action="access_suspended", note=note
        )
        return {"user": self._public_user(user), "changed": changed}

    def reactivate(self, public_id: str, *, note: str = "") -> dict[str, Any]:
        user, changed = self._transition(
            public_id, expected=("suspended",), target="active", action="access_reactivated", note=note
        )
        return {"user": self._public_user(user), "changed": changed}

    def resend_notification(self, public_id: str) -> dict[str, Any]:
        user = self.repo.get_user_by_public_id(str(public_id or "").strip())
        if not user:
            raise AuthValidationError("Usuário não localizado.", 404)
        status = str(user.get("access_status") or "")
        if status == "active":
            notification_type = "access_approved"
        elif status == "rejected":
            notification_type = "access_rejected"
        else:
            raise AuthValidationError("Não há notificação administrativa aplicável ao estado atual.", 409)
        sent = self._notification(user, notification_type)
        return {"user": self._public_user(user), "notification_sent": sent, "notification_type": notification_type}


@lru_cache(maxsize=8)
def _cached_admin_service(
    database_path: str, usage_database_path: str, config_fingerprint: tuple[tuple[str, str], ...]
) -> AuthAdminService:
    return AuthAdminService(database_path, usage_database_path, dict(config_fingerprint))


def get_auth_admin_service() -> AuthAdminService:
    keys = (
        "CONTACT_SMTP_HOST", "CONTACT_SMTP_PORT", "CONTACT_SMTP_USERNAME", "CONTACT_SMTP_PASSWORD",
        "CONTACT_FROM_EMAIL", "CONTACT_SMTP_USE_TLS", "CONTACT_SMTP_USE_SSL", "CONTACT_SMTP_TIMEOUT",
    )
    fingerprint = tuple((key, str(current_app.config.get(key, ""))) for key in keys)
    return _cached_admin_service(
        str(current_app.config["ARQUIVO_AUTH_USUARIOS"]),
        str(current_app.config["ARQUIVO_USO_SITE"]),
        fingerprint,
    )
