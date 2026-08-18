from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIMULAR = (ROOT / "templates" / "simular.html").read_text(encoding="utf-8")
ROUTES = (ROOT / "routes" / "tco_routes.py").read_text(encoding="utf-8")
CONFIG = (ROOT / "config.py").read_text(encoding="utf-8")


def test_versao_v50_27():
    assert 'CURVE_VERSION = "V50.27"' in CONFIG


def test_fipe_referencia_e_origem_curva_sao_preservadas_no_post():
    for prefixo in ("atual", "ve", "icev"):
        assert f'name="referencia_fipe_{prefixo}"' in SIMULAR
        assert f'name="origem_curva_{prefixo}"' in SIMULAR
        assert f'dados_form.get("referencia_fipe_{prefixo}")' in ROUTES
        assert f'dados_form.get("origem_curva_{prefixo}")' in ROUTES
    assert 'data.MesReferencia || data.referenceMonth || data.mes_referencia' in SIMULAR
    assert 'atualizarRastreabilidadeFipeTCO(prefixo, undefined, campo.dataset.origemDepreciacao)' in SIMULAR


def test_site_e_pdf_exibem_parametros_essenciais_de_rastreabilidade():
    for texto in (
        "Preço energia",
        "Preços combustíveis",
        "Perfil flex",
        "Consumo",
        "Manutenção",
        "Referência FIPE",
        "Origem da curva",
    ):
        assert SIMULAR.count(texto) >= 2
    assert "Não considerada" in ROUTES
    assert "kWh/km" in ROUTES
    assert "km/L" in ROUTES


def test_seguro_exibe_referencia_curta_sem_2021_visivel():
    assert "seguro_referencia_curta" in ROUTES
    assert "seguro_nivel_curto" in ROUTES
    assert "IPSA mai/2026" not in SIMULAR  # valor vem do payload, não hardcode visual
    assert "Nível:" in SIMULAR
    assert "2021A" not in SIMULAR


def test_novos_campos_entram_no_resumo_e_no_snapshot_sem_recalculo_extra():
    for chave in (
        '"preco_energia": preco_unidade',
        '"precos_combustiveis": preco_combustiveis',
        '"perfil_flex": perfil_flex',
        '"consumo_utilizado": consumo_texto',
        '"manutencao_anual":',
        '"referencia_fipe":',
        '"origem_curva":',
    ):
        assert chave in ROUTES
    # O snapshot já persiste resultado.comparacoes e entrada do formulário; não foi criado novo fetch/recalculo.
    assert '"entrada": form.to_dict(flat=True)' in ROUTES
    assert '"comparacoes": resultado_final.get("comparacoes") or []' in ROUTES


def test_snapshots_antigos_nao_ganham_linhas_vazias_de_parametros_novos():
    assert "item.preco_energia is defined" in SIMULAR
    assert "comp.detalhes[0].preco_energia is defined" in SIMULAR
