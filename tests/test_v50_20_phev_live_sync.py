from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _function_body(html: str, name: str) -> str:
    marker = f"function {name}("
    start = html.index(marker)
    brace = html.index("{", start)
    depth = 0
    for i in range(brace, len(html)):
        if html[i] == "{":
            depth += 1
        elif html[i] == "}":
            depth -= 1
            if depth == 0:
                return html[start:i + 1]
    raise AssertionError(f"função {name} sem fechamento")


def test_v50_20_declared():
    assert 'CURVE_VERSION = "V50.26"' in read("config.py")


def test_slider_phev_targets_the_actual_visible_compact_card():
    html = read("templates/simular.html")
    state = _function_body(html, "atualizarEstadoModalPhevTCO")
    card = _function_body(html, "renderizarCardPhevTCO")

    assert 'renderizarCardPhevTCO(eletricoPct);' in state
    assert 'function renderizarCardPhevTCO(eletricoPctOverride = null)' in card
    assert 'Number(eletricoPctOverride ?? valorPersistido)' in card
    assert 'document.getElementById("phev_bar_eletrico")' in card
    assert 'document.getElementById("phev_bar_combustivel")' in card
    assert 'document.getElementById("phev_compact_left")' in card
    assert 'document.getElementById("phev_compact_right")' in card


def test_live_drag_does_not_persist_hidden_before_save():
    html = read("templates/simular.html")
    state = _function_body(html, "atualizarEstadoModalPhevTCO")
    save = _function_body(html, "salvarModalPhevTCO")

    assert 'setValorPhevTCO("phev_percent_eletrico"' not in state
    assert 'setValorPhevTCO("phev_percent_eletrico", String(eletricoPct));' in save


def test_cancel_configured_phev_restores_persisted_visual_state():
    html = read("templates/simular.html")
    cancel = _function_body(html, "cancelarModalPhevTCO")
    assert 'prepararModalPhevTCO();' in cancel
    assert 'renderizarCardPhevTCO();' in cancel


def test_flex_and_phev_both_redraw_compact_card_on_input():
    html = read("templates/simular.html")
    fuel_events = _function_body(html, "inicializarEventosCombustivelTCO")
    phev_events = _function_body(html, "inicializarEventosPhevTCO")
    state = _function_body(html, "atualizarEstadoModalPhevTCO")

    assert 'slider?.addEventListener("input"' in fuel_events
    assert 'renderizarCardCombustivelTCO();' in fuel_events
    assert 'slider?.addEventListener("input"' in phev_events
    assert 'atualizarEstadoModalPhevTCO();' in phev_events
    assert 'renderizarCardPhevTCO(eletricoPct);' in state
