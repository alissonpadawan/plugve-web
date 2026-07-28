from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = (ROOT / "templates" / "simular.html").read_text(encoding="utf-8")


def test_phev_slider_follows_loading_state_in_both_directions():
    assert "phevSlider.disabled = phevCarregando;" in TEMPLATE
    assert 'phevSlider.setAttribute("aria-busy", phevCarregando ? "true" : "false")' in TEMPLATE


def test_flex_slider_is_released_after_loading_except_consumption_only_mode():
    assert "fuelSlider.disabled = combustaoCarregando || !!modoEdicaoSomenteConsumoFlexTCO;" in TEMPLATE
    assert 'fuelSlider.setAttribute("aria-busy", combustaoCarregando ? "true" : "false")' in TEMPLATE


def test_zero_percent_participation_does_not_disable_phev_fields():
    assert "[precoEle, consEle, precoComb, consComb].forEach(el => { if (el) el.disabled = false; });" in TEMPLATE
    assert "[precoEle, consEle].forEach(el => { if (el) el.disabled = !usaEle; });" not in TEMPLATE
    assert "[precoComb, consComb].forEach(el => { if (el) el.disabled = !usaComb; });" not in TEMPLATE


def test_zero_percent_participation_does_not_disable_flex_fields():
    assert "[precoEta, consEta, precoGas, consGas].forEach(el => { if (el) el.disabled = false; });" in TEMPLATE
    assert "[precoEta, consEta].forEach(el => { if (el) el.disabled = !usaEta; });" not in TEMPLATE
    assert "[precoGas, consGas].forEach(el => { if (el) el.disabled = !usaGas; });" not in TEMPLATE


def test_loading_still_disables_save_buttons_while_request_is_active():
    assert "if (combustaoCarregando && fuelSalvar)" in TEMPLATE
    assert "if (phevCarregando && phevSalvar)" in TEMPLATE
