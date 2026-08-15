from __future__ import annotations

from pathlib import Path

from services.result_history_service import (
    build_result_history_view,
    is_valid_result_code,
    normalize_result_code,
)

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def make_record(result_type: str, module: str, payload: dict):
    return {
        "code": f"{result_type}-20260815-23456789AB",
        "result_type": result_type,
        "module": module,
        "created_at_local": "2026-08-15T19:10:00-03:00",
        "schema_version": "curve-result-snapshot-v1",
        "platform_version": "V50.12",
        "payload_sha256": "a" * 64,
        "payload_bytes": 1234,
        "snapshot": {"payload": payload, "result_type": result_type, "module": module},
    }


def test_result_code_normalization_and_validation_is_strict():
    code = "s-20260815-23456789ab"
    assert normalize_result_code(f"  {code}  ") == "S-20260815-23456789AB"
    assert is_valid_result_code(code)
    assert is_valid_result_code("D-20260815-ABCDEFGHJK")
    assert is_valid_result_code("F-20260815-23456789AB")
    assert not is_valid_result_code("S-20260815-123")
    assert not is_valid_result_code("X-20260815-23456789AB")
    assert not is_valid_result_code("S-20260815-OOOOOOOOOO")  # O não faz parte do alfabeto público


def test_tco_history_view_uses_snapshot_values_only():
    payload = {
        "entrada": {"anos": "5", "km_ano": "15000", "preco_ve": "74200"},
        "veiculos": [
            {"role": "veiculo_eletrico", "modelo": "Dolphin", "codigo_fipe": "001234-5"},
            {"role": "veiculo_combustao", "modelo": "Yaris", "codigo_fipe": "009876-5"},
        ],
        "resultado": {
            "tipo_comparacao": "dois_carros_novos",
            "comparacoes": [{
                "titulo": "Comparação direta",
                "detalhes": [
                    {"nome": "Dolphin", "codigo_fipe": "001234-5", "tco_final": "R$ 84.117,58"},
                    {"nome": "Yaris", "codigo_fipe": "009876-5", "tco_final": "R$ 102.143,34"},
                ],
            }],
        },
        "auditoria": {"horizonte": 5},
    }
    view = build_result_history_view(make_record("S", "tco", payload))
    assert view["created_at_display"] == "15/08/2026 às 19:10"
    assert view["module_view"]["vehicles"][0]["codigo_fipe"] == "001234-5"
    assert view["module_view"]["comparisons"][0]["detalhes"][0]["tco_final"] == "R$ 84.117,58"
    assert {item["key"] for item in view["module_view"]["input_items"]} >= {"anos", "km_ano", "preco_ve"}


def test_depreciation_and_fipe_history_views_preserve_original_identity_and_prices():
    dep = build_result_history_view(make_record("D", "depreciacao", {
        "entrada": {"codigo_fipe": "096001-2", "valor_atual": 170000, "horizonte_anos": 5},
        "resultado": {
            "valor_atual": 170000,
            "valor_futuro": 105000,
            "taxa_anual_percentual": 9.18,
            "depreciacao_percentual": 38.24,
            "confianca": "ALTA",
            "tipo_curva_aplicada": "propria",
            "detalhes": {"veiculo": {"modelo": "Haval H6", "codigo_fipe": "096001-2"}},
        },
    }))
    dep_fields = {item["label"]: item["value"] for item in dep["module_view"]["fields"]}
    assert dep_fields["Código FIPE"] == "096001-2"
    assert dep_fields["Valor FIPE na consulta"] == "R$ 170.000,00"
    assert dep_fields["Valor estimado ao final"] == "R$ 105.000,00"
    assert dep_fields["Confiança"] == "ALTA"

    fipe = build_result_history_view(make_record("F", "fipe_plus", {
        "entrada": {"codigo_marca": "23", "codigo_modelo": "999"},
        "resultado": {
            "Marca": "GWM",
            "Modelo": "Haval H6 GT",
            "CodigoFipe": "096999-9",
            "Valor": "R$ 189.900,00",
            "AnoModelo": 2025,
            "MesReferencia": "agosto de 2026",
        },
    }))
    fipe_fields = {item["label"]: item["value"] for item in fipe["module_view"]["fields"]}
    assert fipe_fields["Código FIPE"] == "096999-9"
    assert fipe_fields["Valor FIPE"] == "R$ 189.900,00"
    assert fipe_fields["Mês de referência"] == "agosto de 2026"


def test_recovery_routes_are_snapshot_only_and_do_not_recalculate():
    source = read("routes/main_routes.py")
    assert '@main_bp.route("/resultado")' in source
    assert '@main_bp.route("/resultado/<codigo>")' in source
    assert "get_result_snapshot_service().get_snapshot(codigo, verify_integrity=True)" in source
    assert "build_result_history_view(stored)" in source
    assert 'response.headers["Cache-Control"] = "private, no-store, max-age=0"' in source
    assert 'response.headers["X-Robots-Tag"] = "noindex, nofollow"' in source
    assert "FipeService" not in source
    assert "depreciacao_service" not in source
    assert "calcular_" not in source
    assert "preco_combustivel" not in source
    assert "preco_energia" not in source


def test_historical_template_is_read_only_has_no_runtime_data_fetch_and_exposes_integrity():
    html = read("templates/resultado_historico.html")
    assert "Resultado histórico · leitura imutável" in html
    assert "Nenhuma fonte atual foi consultada e nenhum cálculo foi refeito" in html
    assert "resultado.payload_sha256" in html
    assert "Parâmetros originais armazenados" in html
    assert "Ver payload preservado" in html
    assert "Nova simulação" in html
    assert "fetch(" not in html
    assert "XMLHttpRequest" not in html
    assert "axios" not in html


def test_platform_exposes_search_page_and_version_v50_12():
    base = read("templates/base.html")
    search = read("templates/consultar_resultado.html")
    config = read("config.py")
    assert 'href="/resultado"' in base
    assert ">Consultar resultado</a>" in base
    assert 'action="{{ url_for(\'main.consultar_resultado\') }}"' in search
    assert "Resultado histórico, sem recálculo." in search
    assert 'CURVE_VERSION = "V50.13"' in config
