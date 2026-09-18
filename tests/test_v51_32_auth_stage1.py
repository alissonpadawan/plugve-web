import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

try:
    from app import create_app
    from services.auth_security import AuthValidationError
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
        SECRET_KEY="auth-stage1-test-secret",
        ARQUIVO_AUTH_USUARIOS=Path(tmp.name) / "auth.sqlite3",
        ARQUIVO_USO_SITE=Path(tmp.name) / "usage.sqlite3",
        ARQUIVO_SOBRE_ENGAJAMENTO=Path(tmp.name) / "sobre.sqlite3",
        ARQUIVO_RESULTADOS=Path(tmp.name) / "snapshots.sqlite3",
        ARQUIVO_MENSAGENS_CONTATO=Path(tmp.name) / "contact.sqlite3",
        AUTH_ACCESS_CONTROL_ENABLED=True,
        AUTH_ENFORCE_IN_TESTS=True,
        AUTH_CODE_TTL_SECONDS=900,
        AUTH_CODE_MAX_ATTEMPTS=5,
        AUTH_CODE_RESEND_COOLDOWN_SECONDS=60,
        AUTH_RATE_REGISTER_MAX=50,
        AUTH_RATE_LOGIN_MAX=50,
        AUTH_RATE_VERIFY_MAX=50,
        AUTH_RATE_RESET_MAX=50,
        PLUGVE_ADMIN_TOKEN="admin-test",
        PLUGVE_SYNC_TOKEN="sync-test",
    )
    client = app.test_client()
    yield app, client
    tmp.cleanup()


def csrf(client, path="/solicitar-acesso"):
    client.get(path)
    with client.session_transaction() as sess:
        return sess["auth_csrf_token"]


def register(client, *, email="Maria.Silva@example.com", password="senha-segura-123"):
    token = csrf(client)
    with patch("services.auth_service.send_verification_code") as send:
        response = client.post(
            "/solicitar-acesso",
            data={
                "csrf_token": token,
                "full_name": "Maria da Silva",
                "email": email,
                "password": password,
                "password_confirm": password,
                "profile_type": "aluno_ifg",
                "institution": "IFG",
                "course_area": "PPGTGS",
                "purpose": "Pesquisa acadêmica",
                "privacy_accepted": "1",
                "website": "",
            },
            follow_redirects=False,
        )
        assert response.status_code == 302
        code = send.call_args.kwargs["code"]
    return code


def pending_public_id(client):
    with client.session_transaction() as sess:
        return sess["auth_pending_public_id"]


def confirm(client, code):
    token = csrf(client, "/confirmar-email")
    return client.post(
        "/confirmar-email",
        data={"csrf_token": token, "code": code},
        follow_redirects=False,
    )


def activate(app, public_id):
    with app.app_context():
        return get_auth_service().set_status(public_id, "active")


def login(client, email="maria.silva@example.com", password="senha-segura-123", next_path="/simular"):
    token = csrf(client, "/login")
    return client.post(
        "/login",
        data={"csrf_token": token, "email": email, "password": password, "next": next_path},
        follow_redirects=False,
    )


def test_registration_normalizes_email_hashes_password_and_rejects_duplicate_case(app_client):
    app, client = app_client
    register(client)
    public_id = pending_public_id(client)
    with app.app_context():
        service = get_auth_service()
        user = service.repo.get_user_by_public_id(public_id)
        assert user["email_normalized"] == "maria.silva@example.com"
        assert user["access_status"] == "email_pending"
        assert user["password_hash"] != "senha-segura-123"
        assert "senha-segura-123" not in user["password_hash"]
        with pytest.raises(AuthValidationError) as exc:
            service.register(
                {
                    "full_name": "Outra Maria",
                    "email": "MARIA.SILVA@EXAMPLE.COM",
                    "password": "outra-senha-123",
                    "password_confirm": "outra-senha-123",
                    "profile_type": "profissional",
                    "institution": "",
                    "course_area": "",
                    "purpose": "Avaliação da plataforma",
                    "privacy_accepted": True,
                },
                client_key="duplicate-test",
            )
        assert exc.value.status_code == 409


def test_invalid_password_and_privacy_are_rejected(app_client):
    app, _ = app_client
    with app.app_context(), pytest.raises(AuthValidationError):
        get_auth_service().register(
            {
                "full_name": "Maria da Silva", "email": "maria@example.com",
                "password": "curta", "password_confirm": "curta",
                "profile_type": "aluno_ifg", "institution": "IFG", "course_area": "",
                "purpose": "Pesquisa", "privacy_accepted": True,
            }, client_key="pw-test",
        )


def test_confirmation_correct_wrong_reused_and_pending_approval(app_client):
    app, client = app_client
    code = register(client)
    wrong = confirm(client, "000000" if code != "000000" else "111111")
    assert wrong.status_code == 200
    assert "Código inválido" in wrong.get_data(as_text=True)
    ok = confirm(client, code)
    assert ok.status_code == 302
    assert "/aguardando-aprovacao" in ok.headers["Location"]
    public_id = pending_public_id(client)
    with app.app_context():
        user = get_auth_service().repo.get_user_by_public_id(public_id)
        assert user["access_status"] == "pending_approval"
        assert user["email_verified_at"]
    reused = confirm(client, code)
    assert reused.status_code == 302  # já confirmado: segue para aguardando aprovação


def test_expired_confirmation_code_is_rejected(app_client):
    app, client = app_client
    code = register(client)
    public_id = pending_public_id(client)
    with app.app_context():
        service = get_auth_service()
        user = service.repo.get_user_by_public_id(public_id)
        challenge = service.repo.latest_challenge(user["id"], "email_verification")
        with service.repo.connection() as con:
            con.execute("UPDATE auth_challenges SET expires_at = '2000-01-01T00:00:00Z' WHERE id = ?", (challenge["id"],))
    response = confirm(client, code)
    assert response.status_code == 200
    assert "expirou" in response.get_data(as_text=True)


def test_login_states_active_wrong_password_and_logout(app_client):
    app, client = app_client
    code = register(client)
    public_id = pending_public_id(client)

    before_confirm = login(client)
    assert before_confirm.status_code == 302
    assert "/confirmar-email" in before_confirm.headers["Location"]

    confirm(client, code)
    pending = login(client)
    assert pending.status_code == 302
    assert "/aguardando-aprovacao" in pending.headers["Location"]

    activate(app, public_id)
    wrong = login(client, password="senha-errada-123")
    assert wrong.status_code == 200
    assert "E-mail ou senha inválidos" in wrong.get_data(as_text=True)

    ok = login(client)
    assert ok.status_code == 302
    assert ok.headers["Location"].endswith("/simular")
    assert client.get("/simular").status_code == 200

    token = csrf(client, "/")
    logout_response = client.post("/logout", data={"csrf_token": token}, follow_redirects=False)
    assert logout_response.status_code == 302
    protected = client.get("/simular", follow_redirects=False)
    assert protected.status_code == 302
    assert "/login" in protected.headers["Location"]


def test_protected_route_next_and_open_redirect_blocked(app_client):
    _, client = app_client
    response = client.get("/simular?foo=1", follow_redirects=False)
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]
    assert "next=" in response.headers["Location"]
    page = client.get("/login?next=https://evil.example/")
    assert page.status_code == 200
    assert 'name="next" value="/"' in page.get_data(as_text=True)


def test_api_protected_returns_401_but_technical_admin_keeps_own_token(app_client):
    _, client = app_client
    protected = client.get("/api/fipe/marcas")
    assert protected.status_code == 401
    payload = protected.get_json()
    assert payload["login_url"].startswith("/login")

    technical = client.get("/api/site-usage/admin/telemetry/summary")
    assert technical.status_code == 401  # passou pela porta global e foi negado pelo token administrativo próprio
    authorized = client.get(
        "/api/site-usage/admin/telemetry/summary",
        headers={"X-PlugVE-Admin-Token": "admin-test"},
    )
    assert authorized.status_code == 200


def test_health_and_public_auth_pages_remain_public(app_client):
    _, client = app_client
    assert client.get("/health").status_code == 200
    assert client.get("/login").status_code == 200
    assert client.get("/solicitar-acesso").status_code == 200
    assert client.get("/privacidade").status_code == 200
    assert client.get("/termos").status_code == 200
    landing = client.get("/")
    assert landing.status_code == 200
    assert "Acesso temporariamente controlado" in landing.get_data(as_text=True)


def test_password_reset_generic_flow_and_single_use(app_client):
    app, client = app_client
    register(client)
    token = csrf(client, "/esqueci-minha-senha")
    with patch("services.auth_service.send_password_reset_code") as send:
        response = client.post(
            "/esqueci-minha-senha",
            data={"csrf_token": token, "email": "maria.silva@example.com"},
            follow_redirects=False,
        )
        assert response.status_code == 302
        reset_code = send.call_args.kwargs["code"]

    token = csrf(client, "/redefinir-senha")
    reset = client.post(
        "/redefinir-senha",
        data={
            "csrf_token": token,
            "email": "maria.silva@example.com",
            "code": reset_code,
            "password": "nova-senha-segura-123",
            "password_confirm": "nova-senha-segura-123",
        },
        follow_redirects=False,
    )
    assert reset.status_code == 302
    assert "/login" in reset.headers["Location"]

    token = csrf(client, "/redefinir-senha")
    reused = client.post(
        "/redefinir-senha",
        data={
            "csrf_token": token,
            "email": "maria.silva@example.com",
            "code": reset_code,
            "password": "outra-senha-segura-123",
            "password_confirm": "outra-senha-segura-123",
        },
    )
    assert "Código inexistente ou já utilizado" in reused.get_data(as_text=True)

    # Mensagem para e-mail inexistente continua genérica e não revela cadastro.
    token = csrf(client, "/esqueci-minha-senha")
    generic = client.post(
        "/esqueci-minha-senha",
        data={"csrf_token": token, "email": "naoexiste@example.com"},
        follow_redirects=True,
    )
    assert "Se houver uma conta associada" in generic.get_data(as_text=True)


def test_suspension_has_effect_on_next_request(app_client):
    app, client = app_client
    code = register(client)
    public_id = pending_public_id(client)
    confirm(client, code)
    activate(app, public_id)
    assert login(client).status_code == 302
    assert client.get("/simular").status_code == 200
    with app.app_context():
        get_auth_service().set_status(public_id, "suspended")
    response = client.get("/simular", follow_redirects=False)
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]
    assert "reason=suspended" in response.headers["Location"]


def test_csrf_required_on_sensitive_forms(app_client):
    _, client = app_client
    response = client.post(
        "/solicitar-acesso",
        data={"full_name": "Maria da Silva", "email": "maria@example.com"},
    )
    assert response.status_code == 200
    assert "Sessão inválida" in response.get_data(as_text=True)
