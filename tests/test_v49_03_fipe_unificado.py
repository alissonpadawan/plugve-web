from __future__ import annotations

import sys
import types
from pathlib import Path

try:
    import flask  # type: ignore  # noqa: F401
except ModuleNotFoundError:
    flask_stub = types.ModuleType("flask")
    flask_stub.current_app = None
    sys.modules["flask"] = flask_stub

from services.fipe_service import FipeService


ROOT = Path(__file__).resolve().parents[1]


class _ProbeService(FipeService):
    def __init__(self):
        self.calls: list[tuple] = []

    def _get_json(self, endpoint: str):
        self.calls.append(("canonical", endpoint))
        if endpoint == "marcas":
            return [{"code": "13", "name": "BYD"}]
        return {"probe": "canonical", "endpoint": endpoint}

    def consultar_preco(self, codigo_marca: str, codigo_modelo: str, codigo_ano: str):
        self.calls.append(("consultar_preco", codigo_marca, codigo_modelo, codigo_ano))
        return {
            "Marca": "BYD",
            "Modelo": "Dolphin Mini GS (Elétrico)",
            "AnoModelo": 32000,
            "Combustivel": "Elétrico",
            "Valor": "R$ 118.800,00",
        }

    def _base_url_tipo(self, tipo_veiculo: str | None) -> str:
        self.calls.append(("base_tipo", tipo_veiculo))
        return f"https://example.invalid/api/v2/{tipo_veiculo}"

    def _token(self) -> str:
        return "token-test"

    def _timeout(self) -> int:
        return 15

    def _cache_dir(self) -> Path:
        return ROOT / "data" / "_runtime" / "fipe_cache"

    def _catalog_cache_ttl(self) -> int:
        return 3600

    def _price_cache_ttl(self) -> int:
        return 900

    def _get_json_cached(self, base_url, endpoint, timeout, token, cache_dir, catalog_cache_ttl, price_cache_ttl):
        self.calls.append(("typed", base_url, endpoint))
        return {"probe": "typed", "endpoint": endpoint}


def test_fipe_plus_carros_usa_transporte_canonico_da_simular():
    service = _ProbeService()
    data = service._get_json_tipo("carros", "marcas/13/modelos")
    assert data["probe"] == "canonical"
    assert service.calls == [("canonical", "marcas/13/modelos")]


def test_fipe_plus_motos_mantem_transporte_tipado():
    service = _ProbeService()
    data = service._get_json_tipo("motos", "marcas")
    assert data["probe"] == "typed"
    assert any(call[0] == "base_tipo" and call[1] == "motos" for call in service.calls)
    assert any(call[0] == "typed" for call in service.calls)
    assert not any(call[0] == "canonical" for call in service.calls)


def test_preco_carro_tipado_delega_para_mesma_funcao_da_simular_depreciacao():
    service = _ProbeService()
    data = service.consultar_preco_tipo("carros", "13", "1234", "32000-1")
    assert ("consultar_preco", "13", "1234", "32000-1") in service.calls
    assert data["Valor"] == "R$ 118.800,00"
    assert data["TipoConsulta"] == "carros"


def test_fipe_plus_carros_chama_mesma_rota_de_preco_da_simular():
    html = (ROOT / "templates" / "consulta_fipe.html").read_text(encoding="utf-8")
    assert "tipoAtual === 'carros'" in html
    assert "? `/api/fipe/preco?codigo_marca=${encodeURIComponent(marca)}" in html
    assert ": `/api/fipe/publica/preco?tipo=${encodeURIComponent(tipoAtual)}" in html
    # V49.04 removeu o cache independente do navegador; o preço continua
    # apontando para a mesma rota canônica da Simular/Depreciação.
    assert "cache:'no-store'" in html


def test_depreciacao_usa_mesmo_contrato_http_fipe_da_simular():
    js = (ROOT / "static" / "js" / "fipe.js").read_text(encoding="utf-8")
    inicio = js.index("async function buscarJsonFipeSeguro(url)")
    fim = js.index("async function varrerMarcaAtual", inicio)
    helper = js[inicio:fim]
    assert 'fetch(url, { headers: { Accept: "application/json" }, cache: "no-store" })' in helper
    assert "await carregarUsoFipe();" not in helper
    assert "if (!resp.ok)" in helper


def test_depreciacao_exibe_401_402_403_em_vez_de_falha_silenciosa():
    js = (ROOT / "static" / "js" / "fipe.js").read_text(encoding="utf-8")
    assert "[401, 402, 403].includes(status)" in js
    assert "erroFipeBloqueiaConsulta(e.data, { status: e.status })" in js


def test_cache_bust_fipe_js_depreciacao_v49_04():
    html = (ROOT / "templates" / "depreciacao.html").read_text(encoding="utf-8")
    assert "20260809_v49_04_catalogo_canonico" in html
