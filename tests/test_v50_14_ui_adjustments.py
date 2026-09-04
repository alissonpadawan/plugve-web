from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_platform_version_is_v50_14():
    assert 'CURVE_VERSION = "V50.28"' in read("config.py")


def test_phev_profile_syncs_actual_compact_phev_card_live_and_persisted():
    html = read("templates/simular.html")
    # V50.20: a barra visual que o usuário enxerga no card Híbrido plug-in usa
    # phev_bar_*, não energia_bar_*. A correção anterior cobria a barra errada.
    assert 'id="phev_bar_eletrico"' in html
    assert 'id="phev_bar_combustivel"' in html
    assert 'id="phev_compact_left"' in html
    assert 'id="phev_compact_right"' in html
    assert 'function renderizarCardPhevTCO(eletricoPctOverride = null)' in html
    assert 'Number(eletricoPctOverride ?? valorPersistido)' in html
    assert 'barEle.style.width = `${eletricoPct}%`' in html
    assert 'barComb.style.width = `${combustPct}%`' in html
    assert 'left.textContent = `${eletricoPct}% elétrico${precoEnergiaTexto}`' in html
    assert 'right.textContent = `${combustPct}% combustível${precoCombustivelTexto}`' in html
    # Durante o input, o override temporário redesenha o card sem persistir o hidden.
    assert 'renderizarCardPhevTCO(eletricoPct);' in html
    assert 'setValorPhevTCO("phev_percent_eletrico", String(eletricoPct));' in html  # apenas no salvar


def test_tco_pdf_header_uses_vehicle_vs_vehicle_instead_of_explanatory_paragraph():
    html = read("templates/simular.html")
    assert 'Relatório de Custo Total de Propriedade' in html
    assert '{{ comp.detalhes[0].nome }} <span class="tco-pdf-vs">×</span> {{ comp.detalhes[1].nome }}' in html
    assert 'Comparação entre alternativas veiculares considerando aquisição, energia/combustível' not in html


def test_public_result_lookup_is_search_icon_with_compact_overlay_not_text_nav_item():
    base = read("templates/base.html")
    css = read("static/css/result_search_modal.css")
    js = read("static/js/result_search_modal.js")
    assert 'id="result_search_trigger"' in base
    assert '>Consultar resultado</a>' not in base
    assert 'id="result_search_overlay"' in base
    assert 'placeholder="Digite o código"' in base
    assert 'backdrop-filter:blur(5px)' in css.replace(" ", "")
    assert 'COMPLETE_RE = /^[SDF]-\\d{8}-[23456789ABCDEFGHJKLMNPQRSTUVWXYZ]{10}$/' in js
    assert 'window.location.assign(`/resultado/${encodeURIComponent(code)}`)' in js
    assert 'event.key==="Escape"' in js
    assert 'event.key==="Enter"' in js


def test_result_lookup_mask_formats_only_public_sdf_shape():
    js = read("static/js/result_search_modal.js")
    assert 'const PREFIXES = new Set(["S", "D", "F"]);' in js
    assert 'const SUFFIX_CHARS = new Set("23456789ABCDEFGHJKLMNPQRSTUVWXYZ".split(""));' in js
    assert 'if (!prefix) return "";' in js
    assert 'date = (parts[1] || "").replace(/\\D/g, "").slice(0, 8);' in js
    assert 'return formatted.slice(0, 21);' in js
