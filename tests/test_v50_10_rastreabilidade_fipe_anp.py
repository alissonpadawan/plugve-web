from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANP_URL = (
    "https://www.gov.br/anp/pt-br/assuntos/precos-e-defesa-da-concorrencia/"
    "precos/levantamento-de-precos-de-combustiveis-ultimas-semanas-pesquisadas"
)


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_simular_exibe_e_persiste_codigo_fipe_nos_tres_veiculos():
    html = read("templates/simular.html")
    for prefixo in ("atual", "ve", "icev"):
        assert f'id="codigo_fipe_{prefixo}_label"' in html
        assert f'name="codigo_fipe_{prefixo}"' in html
        assert f'id="codigo_fipe_{prefixo}"' in html
    assert "function atualizarCodigoFipeTCO(prefixo, codigo)" in html
    assert "atualizarCodigoFipeTCO(prefixo, codigoFipeSelecionado);" in html
    assert "Código FIPE: <b>{{ item.codigo_fipe }}</b>" in html


def test_tco_backend_transporta_codigo_fipe_ate_resultado_auditoria_e_telemetria():
    py = read("routes/tco_routes.py")
    assert '"codigo_fipe": str(dados_form.get("codigo_fipe_ve") or "").strip()' in py
    assert '"codigo_fipe": str(dados_form.get("codigo_fipe_icev") or "").strip()' in py
    assert '"codigo_fipe": str(dados_form.get("codigo_fipe_atual") or "").strip()' in py
    assert '"codigo_fipe": codigo_fipe' in py
    assert '"codigo_fipe": str(v.get("codigo_fipe") or "").strip()' in py
    assert '"codigo_fipe": form.get(f"codigo_fipe_{prefixo}") or ""' in py

    audit = read("templates/auditoria_tco.html")
    assert "<dt>Código FIPE</dt><dd>{{ item.codigo_fipe or '—' }}</dd>" in audit
    assert "Código FIPE: <strong>{{ veic.codigo_fipe }}</strong>" in audit


def test_depreciacao_exibe_codigo_fipe_na_selecao_no_resumo_e_no_relatorio_pdf():
    template = read("templates/depreciacao.html")
    fipe_js = read("static/js/fipe.js")
    dep_js = read("static/js/depreciacao.js")

    assert 'id="fipe_codigo_selecionado"' in template
    assert 'id="res_codigo_fipe_linha"' in template
    assert 'id="res_codigo_fipe"' in template
    assert "function atualizarCodigoFipeSelecionadoDepreciacao(codigo)" in fipe_js
    assert "atualizarCodigoFipeSelecionadoDepreciacao(detalhe.codigo_fipe || \"\")" in fipe_js
    assert 'linhaCodigo.classList.toggle("hidden", !info.codigoFipe)' in dep_js
    assert 'report-vehicle-code' in dep_js
    assert 'Código FIPE: <strong>${escaparHtml(info.codigoFipe)}</strong>' in dep_js
    assert 'Código FIPE", info.codigoFipe' in dep_js


def test_fipe_plus_ja_exibe_codigo_e_o_mantem_na_impressao():
    html = read("templates/consulta_fipe.html")
    assert "['Código FIPE', veiculoAtual.codigo_fipe || '—']" in html
    assert "function exportarPdfFipePlus()" in html
    assert "window.print();" in html
    # O bloco de chave/valor do resultado não é ocultado pela regra @media print.
    print_css = html.split("@media print", 1)[1].split("}", 1)[0]
    assert "fipe_result_kv" not in print_css


def test_logos_anp_apontam_para_fonte_oficial_em_nova_guia():
    html = read("templates/simular.html")
    assert html.count(f'href="{ANP_URL}"') == 4
    assert html.count('target="_blank" rel="noopener noreferrer"') >= 4
    assert 'ev.target?.closest?.(".plugve-source-logo--anp")' in html
    assert '<span class="plugve-field-source plugve-source-logo plugve-source-logo--anp hidden"' not in html
