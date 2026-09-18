from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_version_and_home_use_modal_gate():
    assert 'CURVE_VERSION = "V51.37"' in read("config.py")
    route = read("routes/main_routes.py")
    assert 'render_template("auth/access_landing.html")' not in route
    index = read("templates/index.html")
    assert 'access-gate-overlay' in index
    assert 'Acesso temporariamente controlado' in index
    assert "url_for('auth.login')" in index
    assert "url_for('auth.register')" in index
    assert 'inert aria-hidden="true"' in index


def test_auth_pages_share_same_alignment_axis():
    css = read("static/css/auth.css")
    assert '--auth-panel-width:740px' in css
    assert 'width:min(var(--auth-panel-width),calc(100% - 32px))' in css
    assert 'width:min(var(--auth-panel-width),calc(100vw - 32px))' in css


def test_cache_buster_updated():
    assert '?v=51_37' in read("templates/auth/_base.html")
    assert '?v=51_37' in read("templates/index.html")
