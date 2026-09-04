from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIMULAR = (ROOT / "templates" / "simular.html").read_text(encoding="utf-8")
ROUTES = (ROOT / "routes" / "tco_routes.py").read_text(encoding="utf-8")
CONFIG = (ROOT / "config.py").read_text(encoding="utf-8")


def test_versao_v50_26():
    assert 'CURVE_VERSION = "V50.28"' in CONFIG


def test_resultado_site_mostra_municipio_e_remove_nota_monetaria():
    assert '<strong>Município:</strong>' in SIMULAR
    assert "resultado.form_values.get('municipio_select')" in SIMULAR
    assert 'TCO acumulado em reais constantes da data-base da simulação (' not in SIMULAR


def test_pdf_mostra_municipio_e_meta_tem_somente_codigo():
    assert '<td><b>Município</b></td>' in SIMULAR
    assert SIMULAR.count('class="tco-pdf-meta">{% if resultado.resultado_codigo %}<strong>Código:</strong>') == 5
    assert '<strong>Resultado gerado em:</strong>' not in SIMULAR
    assert 'Data de emissão: -' not in SIMULAR
    assert '<strong>Relatório TCO</strong><br>Comparativo financeiro' not in SIMULAR


def test_seguro_projetado_site_e_pdf_ficam_curto_sem_2021_visivel():
    assert SIMULAR.count('Fonte: IPSA + AUTOSEG/SUSEP') >= 3
    assert 'seguro_nivel_agregacao' not in SIMULAR
    assert 'seguro_confianca' not in SIMULAR
    assert 'seguro_data_base' not in SIMULAR
    assert 'Estimativa de referência; não representa cotação individual.' not in SIMULAR
    assert 'AUTOSEG: 2021A' not in SIMULAR


def test_variacoes_pdf_tem_rotulos_simplificados():
    assert '<b>Variação da energia</b>' in SIMULAR
    assert '<b>Variação dos combustíveis</b>' in SIMULAR
    assert '<b>Variação real anual da energia</b>' not in SIMULAR
    assert '<b>Variação real anual dos combustíveis</b>' not in SIMULAR


def test_cards_mostram_valor_antes_do_codigo_em_linhas_separadas():
    web_valor = SIMULAR.index('Valor FIPE inicial: <b>{{ item.preco_inicial }}</b>', SIMULAR.index('plugve-vehicle-name-block'))
    web_codigo = SIMULAR.index('Código FIPE: <b>{{ item.codigo_fipe }}</b>', SIMULAR.index('plugve-vehicle-name-block'))
    assert web_valor < web_codigo
    assert '.tco-pdf-vehicle small{display:block;' in SIMULAR


def test_textos_metodologicos_removidos_da_interface_e_pdf():
    assert 'Metodologia operacional: energia elétrica' not in SIMULAR
    assert 'Valores monetários acumulados expressos em reais constantes da data-base da simulação.' not in SIMULAR


def test_co2_sem_legendas_explicativas_nas_tabelas_comparativas():
    assert 'row("CO₂ fóssil operacional", "co2_fossil", tipo="ton")' in ROUTES
    assert 'row("CO₂ biogênico operacional", "co2_biogenico", tipo="ton", informativo=True)' in ROUTES
    assert 'linha_componente("CO₂ fóssil operacional", v1.get("co2_total_t", 0), v2.get("co2_total_t", 0), tipo="co2")' in ROUTES
    assert 'linha_componente("CO₂ biogênico operacional", v1.get("co2_biogenico_total_t", 0), v2.get("co2_biogenico_total_t", 0), tipo="co2")' in ROUTES
