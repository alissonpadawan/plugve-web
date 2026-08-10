from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIMULAR = (ROOT / "templates" / "simular.html").read_text(encoding="utf-8")
TCO = (ROOT / "routes" / "tco_routes.py").read_text(encoding="utf-8")
COMBO = (ROOT / "static" / "js" / "fipe_combobox.js").read_text(encoding="utf-8")


def test_edit_refreshes_custom_fipe_combobox_after_programmatic_restore():
    assert 'select.value = valor;' in SIMULAR
    assert 'window.atualizarComboboxesFipeCurVE();' in SIMULAR
    assert 'requestAnimationFrame(() => window.atualizarComboboxesFipeCurVE?.());' in SIMULAR
    assert 'function atualizarBotao(inst)' in COMBO


def test_checkbox_restore_respects_false_instead_of_checkbox_default_on_value():
    assert '(typeof item.checked === "boolean") ? item.checked' in SIMULAR
    assert '!!item.checked || item.value === "on"' not in SIMULAR


def test_footer_is_pushed_to_page_bottom_in_flex_layout():
    assert '.curve-internal-page > .institutional-footer{margin-top:auto' in SIMULAR


def test_result_heading_uses_vehicle_names_instead_of_generic_summary():
    assert '{{ resumo_comp.detalhes[0].nome }} × {{ resumo_comp.detalhes[1].nome }}' in SIMULAR
    assert '<h2 class="plugve-summary-title">Resumo dos Resultados</h2>' not in SIMULAR


def test_pdf_has_five_logical_pages_for_one_two_vehicle_comparison():
    # Resumo, financeiro, componentes anuais, evolução econômica, impacto/revenda.
    assert SIMULAR.count('<article class="tco-pdf-page') == 5
    assert 'tco-pdf-page-combined' in SIMULAR
    assert 'data-tco-chart-copy="dep1-' not in SIMULAR
    assert 'data-tco-chart-copy="dep2-' not in SIMULAR


def test_pdf_annual_charts_are_full_width_stacked_and_not_side_by_side():
    assert 'class="tco-pdf-chart-stack"' in SIMULAR
    assert 'class="tco-pdf-chart annual" data-tco-chart-copy="anuais1-' in SIMULAR
    assert 'class="tco-pdf-chart annual" data-tco-chart-copy="anuais2-' in SIMULAR


def test_pdf_chart_export_replots_with_print_specific_dimensions_and_waits_for_decode():
    assert 'window.Plotly.newPlot(temp, dadosPdf, layoutPdf' in SIMULAR
    assert 'await aguardarImagemPdfTCO(img);' in SIMULAR
    assert 'await document.fonts?.ready;' in SIMULAR
    assert 'requestAnimationFrame(() => requestAnimationFrame(resolve))' in SIMULAR


def test_pdf_report_header_and_footer_are_not_hidden_by_generic_print_rule():
    assert 'header, footer, #form_simulacao_tco' not in SIMULAR
    assert '.curve-header, .curve-footer, .institutional-footer, #form_simulacao_tco' in SIMULAR


def test_new_growth_defaults_are_present_in_ui_and_backend():
    assert 'value="4,60"' in SIMULAR
    assert 'value="5,60"' in SIMULAR
    assert 'Premissa operacional inicial: 4,60% a.a.' in SIMULAR
    assert 'Premissa operacional inicial: 5,60% a.a.' in SIMULAR
    assert 'AUMENTO_ENERGIA_PADRAO_PERCENTUAL = 4.6' in TCO
    assert 'AUMENTO_COMBUSTIVEL_PADRAO_PERCENTUAL = 5.6' in TCO


def test_annual_component_palette_is_explicit_and_muted():
    for hexc in ['#4A78A6', '#C28743', '#3F9075', '#7A8797', '#8A73B8']:
        assert hexc in TCO
    assert 'marker_color=CORES_COMPONENTES_TCO.get(nome_comp' in TCO
