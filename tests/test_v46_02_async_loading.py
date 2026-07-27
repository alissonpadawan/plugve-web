from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = (ROOT / "templates" / "simular.html").read_text(encoding="utf-8")


def test_fipe_and_pbev_loading_indicators_exist_for_all_vehicle_slots():
    for prefix in ("atual", "ve", "icev"):
        assert f'id="fipe_loading_{prefix}"' in TEMPLATE
        assert f'id="pbev_loading_{prefix}"' in TEMPLATE
    assert 'id="pbev_loading_modal_flex"' in TEMPLATE
    assert 'id="pbev_loading_modal_phev"' in TEMPLATE


def test_requests_are_cancellable_and_stale_responses_are_guarded():
    assert "new AbortController()" in TEMPLATE
    assert "signal: consultaFipe.signal" in TEMPLATE
    assert "signal: consulta.signal" in TEMPLATE
    assert "consultaControladaAtualTCO(CONSULTAS_FIPE_TCO" in TEMPLATE
    assert "consultaControladaAtualTCO(CONSULTAS_PBEV_TCO" in TEMPLATE
    assert "cancelarConsultaControladaTCO(CONSULTAS_FIPE_TCO, prefixo)" in TEMPLATE
    assert "cancelarConsultaControladaTCO(CONSULTAS_PBEV_TCO, prefixo)" in TEMPLATE


def test_inputs_are_locked_while_official_queries_are_pending():
    assert "preco.readOnly = !!ativo" in TEMPLATE
    assert "campo.readOnly = bloqueado" in TEMPLATE
    assert 'fuelSlider.disabled = true' in TEMPLATE
    assert 'phevSlider.disabled = true' in TEMPLATE
    assert 'fuelSalvar.disabled = true' in TEMPLATE
    assert 'phevSalvar.disabled = true' in TEMPLATE
    assert "consultaVeiculoPendenteTCO" in TEMPLATE


def test_loading_messages_and_safe_manual_fallback_are_present():
    assert "Consultando valor FIPE…" in TEMPLATE
    assert "Consultando consumo no Inmetro…" in TEMPLATE
    assert "A consulta FIPE demorou demais" in TEMPLATE
    assert "A consulta ao Inmetro demorou demais" in TEMPLATE
    assert "Digite o preço manualmente" in TEMPLATE
    assert "Digite o consumo manualmente" in TEMPLATE


def test_v45_missing_confirmation_functions_did_not_return():
    assert "pbevBotaoConfirmacaoPorPrefixoTCO" not in TEMPLATE
    assert "pbevGarantirModalConfirmacaoTCO" not in TEMPLATE
