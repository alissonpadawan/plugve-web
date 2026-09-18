from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_version_is_51_37():
    assert 'CURVE_VERSION = "V51.37"' in read("config.py")


def test_successful_login_is_silent_on_the_application():
    route = read("routes/auth_routes.py")
    assert 'flash("Acesso realizado com sucesso.", "success")' not in route
    assert 'rotate_session_with_auth_token(result.session_token)' in route
    assert 'return redirect(next_path)' in route


def test_auth_grid_fields_align_from_the_top():
    css = read("static/css/auth.css")
    assert 'align-self:start' in css
    assert 'align-content:start' in css


def test_auth_assets_use_51_37_cache_buster():
    assert '?v=51_37' in read("templates/auth/_base.html")
    assert '?v=51_37' in read("templates/index.html")
    assert '?v=51_37' in read("templates/base.html")
