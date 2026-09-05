from pathlib import Path

from services.result_history_service import build_result_history_view

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _record(payload: dict):
    return {
        "code": "S-20260816-23456789AB",
        "result_type": "S",
        "module": "tco",
        "created_at_local": "2026-08-16T00:20:00-03:00",
        "schema_version": "curve-result-snapshot-v1",
        "platform_version": "V50.19",
        "payload_sha256": "a" * 64,
        "payload_bytes": 999,
        "snapshot": {"payload": payload, "result_type": "S", "module": "tco"},
    }


def test_public_history_removes_snapshot_notice_and_raw_integrity_payload():
    html = read("templates/resultado_historico.html")
    assert "Snapshot preservado" not in html
    assert "Integridade e dados técnicos do snapshot" not in html
    assert "Ver payload preservado" not in html
    assert "resultado.payload | tojson" not in html
    assert "resultado.payload_sha256" not in html
    assert "Nenhuma fonte atual foi consultada" not in html
    assert "Resultado originalmente gerado em" in html


def test_parameters_use_human_labels_and_zero_is_not_exposed_as_raw_numeric_zero():
    view = build_result_history_view(_record({
        "entrada": {
            "estado_uf": "GO",
            "fin_atual_ativo": "0",
            "fin_atual_entrada": "0",
            "fin_atual_juros_mensal": "0",
            "fin_icev_parcela": "0",
            "fin_ve_entrada_pct": "20",
            "ve_modelo_codigo": "123",
            "pbev_ve_id_pbev": "999",
        },
        "veiculos": [],
        "resultado": {"comparacoes": []},
    }))
    items = view["module_view"]["input_items"]
    labels = {item["label"]: item["value"] for item in items}
    assert labels["UF"] == "GO"
    assert labels["Financiamento ativo — Veículo atual"] == "Não"
    assert labels["Entrada — Veículo atual"] == "—"
    assert labels["Juros mensais — Veículo atual"] == "—"
    assert labels["Parcela mensal — ICEV"] == "—"
    assert labels["Entrada (%) — VE"] == "20"
    assert not any("fin_atual" in item["label"] for item in items)
    assert not any("pbev" in item["label"].lower() for item in items)
    assert not any(item["key"] == "ve_modelo_codigo" for item in items)


def test_v50_19_version_is_declared():
    assert 'CURVE_VERSION = "V50.30"' in read("config.py")
