from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_v50_18_version():
    assert 'CURVE_VERSION = "V50.26"' in read("config.py")


def test_search_lens_exists_in_every_current_public_header_and_is_last_item():
    for name in ("base.html", "index.html", "home.html", "simular.html"):
        html = read(f"templates/{name}")
        assert html.count('id="result_search_trigger"') == 1, name
        assert html.count('id="result_search_overlay"') == 1, name
        nav_start = html.find('<nav class="site-nav"')
        if nav_start < 0:
            nav_start = html.find('<nav class="curve-nav"')
        nav_end = html.find("</nav>", nav_start)
        nav = html[nav_start:nav_end]
        assert nav.find(">Contato</a>") < nav.find('id="result_search_trigger"'), name
        assert 'css/result_search_modal.css' in html, name
        assert 'js/result_search_modal.js' in html, name


def test_search_mask_supports_editing_and_deleting_auto_separators():
    js = read("static/js/result_search_modal.js")
    assert 'function applyMaskPreservingCaret()' in js
    assert 'function deleteAcrossSeparator(direction)' in js
    assert 'event.key==="Backspace" && deleteAcrossSeparator("backward")' in js
    assert 'event.key==="Delete" && deleteAcrossSeparator("forward")' in js
    assert 'input.setSelectionRange' in js
    assert 'input.value="";' in js  # modal reopens clean after close
    assert 'requestAnimationFrame(()=>{ input.focus(); input.select(); });' in js


def test_result_search_styles_work_with_both_header_systems():
    css = read("static/css/result_search_modal.css")
    assert '.result-search-trigger' in css
    assert '.curve-nav .result-search-trigger' in css
    assert 'z-index:9000' in css.replace(" ", "")
