from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

from services.result_snapshot_service import ResultSnapshotService

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_snapshot_is_immutable_and_keeps_original_payload_exactly():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "results.sqlite3"
        service = ResultSnapshotService(db, platform_version="V50.11")
        original = {
            "entrada": {"codigo_fipe": "001234-5", "valor_fipe": 74200.0, "ipca": 4.83},
            "resultado": {"tco": 84117.58, "horizonte": 5, "cidade": "Goiânia"},
        }
        meta = service.create_snapshot(result_type="S", module="tco", payload=original)
        assert meta["code"].startswith("S-")
        assert len(meta["code"].split("-")[-1]) == 10

        # Alterar o objeto Python original depois da gravação não pode alterar o histórico.
        original["entrada"]["valor_fipe"] = 999999.0
        stored = service.get_snapshot(meta["code"])
        assert stored is not None
        assert stored["snapshot"]["payload"]["entrada"]["valor_fipe"] == 74200.0
        assert stored["snapshot"]["payload"]["resultado"]["tco"] == 84117.58
        assert stored["platform_version"] == "V50.11"

        # UPDATE e DELETE são bloqueados no próprio SQLite, não apenas na aplicação.
        conn = sqlite3.connect(db)
        try:
            with pytest.raises(sqlite3.IntegrityError, match="result_snapshot_immutable"):
                conn.execute("UPDATE result_snapshots SET module='x' WHERE result_code=?", (meta["code"],))
            conn.rollback()
            with pytest.raises(sqlite3.IntegrityError, match="result_snapshot_immutable"):
                conn.execute("DELETE FROM result_snapshots WHERE result_code=?", (meta["code"],))
        finally:
            conn.close()


def test_result_prefixes_are_separate_and_hash_is_verified():
    with tempfile.TemporaryDirectory() as tmp:
        service = ResultSnapshotService(Path(tmp) / "results.sqlite3", platform_version="V50.11")
        pairs = [("S", "tco"), ("D", "depreciacao"), ("F", "fipe_plus")]
        codes = []
        for result_type, module in pairs:
            meta = service.create_snapshot(
                result_type=result_type,
                module=module,
                payload={"entrada": {"codigo_fipe": "001234-5"}, "resultado": {"valor": 1}},
            )
            codes.append(meta["code"])
            stored = service.get_snapshot(meta["code"], verify_integrity=True)
            assert stored["payload_sha256"] == meta["payload_sha256"]
            assert stored["snapshot"]["result_type"] == result_type
            assert stored["snapshot"]["module"] == module
        assert len(set(codes)) == 3
        assert service.count() == 3
        assert service.count("S") == 1
        assert service.count("D") == 1
        assert service.count("F") == 1


def test_tco_creates_snapshot_before_telemetry_and_drops_plotly_html_only():
    source = read("routes/tco_routes.py")
    assert 'result_type="S"' in source
    assert 'module="tco"' in source
    assert 'resultado_final["resultado_codigo"] = snapshot_meta["code"]' in source
    assert '"resultado_codigo": resultado_final.get("resultado_codigo") or ""' in source
    assert 'if chave_txt == "graficos" or chave_txt.startswith("grafico")' in source
    assert '"memoria_anual_comparativa"' in source  # memória numérica continua disponível no resultado


def test_depreciation_snapshots_only_direct_user_result_not_internal_tco_or_fipe_plus():
    source = read("routes/depreciacao_routes.py")
    assert 'result_type="D"' in source
    assert 'module="depreciacao"' in source
    assert 'is_internal_usage = bool(payload.get("origem_tco"))' in source
    snapshot_pos = source.index('snapshot_meta = get_result_snapshot_service().create_snapshot')
    internal_guard_pos = source.index('if resultado.get("encontrado") and not is_internal_usage')
    assert internal_guard_pos < snapshot_pos
    template = read("templates/depreciacao.html")
    js = read("static/js/depreciacao.js")
    assert 'id="res_codigo_resultado"' in template
    assert 'data?.resultado_codigo' in js


def test_fipe_plus_requests_snapshot_context_without_affecting_other_fipe_consumers():
    routes = read("routes/fipe_routes.py")
    html = read("templates/consulta_fipe.html")
    assert 'contexto = str(request.args.get("contexto_resultado") or "").strip().lower()' in routes
    assert 'if contexto != "fipe_plus"' in routes
    assert 'result_type="F"' in routes
    assert 'module="fipe_plus"' in routes
    assert html.count("contexto_resultado=fipe_plus") == 2
    assert "['Código do resultado', veiculoAtual.resultado_codigo || '—']" in html
    assert "resultado_codigo:data.resultado_codigo || ''" in html


def test_snapshot_database_is_persistent_and_separate_from_usage_database():
    config = read("config.py")
    assert 'ARQUIVO_RESULTADOS = PERSISTENT_DIR / "institucional" / "result_snapshots.sqlite3"' in config
    assert 'ARQUIVO_USO_SITE = PERSISTENT_DIR / "institucional" / "site_usage.sqlite3"' in config
    assert 'CURVE_VERSION = "V50.27"' in config
