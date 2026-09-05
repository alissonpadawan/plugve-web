from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_platform_version_is_v50_13():
    assert 'CURVE_VERSION = "V50.30"' in read("config.py")


def test_tco_pdf_contains_original_result_identity_and_filename():
    html = read("templates/simular.html")
    assert "resultado.resultado_codigo" in html
    assert "resultado.resultado_gerado_em_texto" in html
    # V50.26 deixa no canto do PDF somente o código; a data segue disponível no resultado/snapshot.
    assert 'class="tco-pdf-meta">{% if resultado.resultado_codigo %}<strong>Código:</strong>' in html
    assert "Resultado gerado em:" not in html
    assert "codigoResultadoTCO" in html
    assert "CurVE_Simulacao_${codigoResultadoTCO}" in html
    assert 'metadata: {resultado_codigo: codigoResultadoTCO || ""}' in html


def test_depreciation_pdf_contains_original_result_identity_and_filename():
    html = read("templates/depreciacao.html")
    js = read("static/js/depreciacao.js")
    assert 'id="pdf_codigo_resultado"' in html
    assert 'id="pdf_resultado_gerado_em"' in html
    assert 'id="res_resultado_gerado"' in html
    assert "ultimoResumoDepreciacao?.resultado_gerado_em_texto" in js
    assert "CurVE_Depreciacao_${codigoResultado}" in js
    assert "metadata: {resultado_codigo: ultimoResumoDepreciacao?.resultado_codigo || ''}" in js


def test_fipe_plus_pdf_uses_result_code_date_and_filename_without_false_export_event():
    html = read("templates/consulta_fipe.html")
    assert '>Exportar PDF</button>' in html
    assert "['Código do resultado', veiculoAtual.resultado_codigo || '—']" in html
    assert "['Gerado em', veiculoAtual.resultado_gerado_em_texto || '—']" in html
    assert "CurVE_FIPE_${codigoResultado}" in html
    assert "if (veiculoAtual) {" in html
    assert "metadata:{resultado_codigo:veiculoAtual.resultado_codigo || ''}" in html


def test_admin_timeline_exposes_result_code_as_historical_snapshot_link():
    service = read("services/site_usage_service.py")
    js = read("static/js/admin_usage.js")
    html = read("templates/admin_usage.html")
    css = read("static/css/admin_usage.css")
    assert '"result_code": stored_result_code or str(metadata.get("resultado_codigo") or "").strip().upper()' in service
    assert "event?.result_code || event?.metadata?.resultado_codigo" in js
    assert 'href="/resultado/${encodeURIComponent(code)}"' in js
    assert "admin-result-link" in js
    assert ".admin-result-link" in css
    assert "Inteligência V50.17" in html


def test_admin_only_links_codes_in_public_sdf_format():
    js = read("static/js/admin_usage.js")
    assert r"/^[SDF]-\d{8}-[23456789ABCDEFGHJKLMNPQRSTUVWXYZ]{10}$/" in js
