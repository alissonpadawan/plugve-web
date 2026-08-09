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


class _Decision:
    contexts = ("ve", "icev")
    tipo_plugve = "EV_PURO"

    def as_dict(self):
        return {"contextos": ["ve", "icev"], "tipo_plugve": self.tipo_plugve}


class _Classifier:
    def brand_contexts(self, marca):
        return ("ve", "icev")

    def classify(self, marca, modelo, year=None, fuel=""):
        return _Decision()


class _CatalogProbe(FipeService):
    def __init__(self):
        self.calls: list[str] = []

    def _get_json(self, endpoint: str):
        self.calls.append(endpoint)
        if endpoint == "marcas":
            return [{"code": "13", "name": "BYD"}]
        if endpoint == "marcas/13/modelos":
            return {
                "models": [
                    {"code": "1001", "name": "Dolphin Mini GL"},
                    {"code": "1002", "name": "Dolphin Mini GS (Elétrico)"},
                ]
            }
        if endpoint == "marcas/13/modelos/1002/anos":
            return [
                {"code": "32000-1", "name": "Zero km Elétrico"},
                {"code": "2026-1", "name": "2026 Elétrico"},
            ]
        raise AssertionError(endpoint)

    def _ler_marcas_bloqueadas(self):
        return {}

    def _ler_marcas_varridas(self):
        return {}

    def _estado_varredura_temporal(self):
        return {"pronto": True, "varridas": {"13": {}}}

    def _marca_temporal_permitida(self, codigo_marca, nome_marca="", estrito=True):
        return True

    def _modelo_temporal_permitido(self, codigo_marca, codigo_modelo, nome_marca="", nome_modelo="", estrito=True):
        return True

    def _ler_bloqueados(self):
        return {}

    def _ler_modelos_zero_km(self):
        return {}

    def _ler_modelos_novos(self):
        return {}

    def _catalog_classifier(self):
        return _Classifier()

    def _salvar_decisoes_catalogo_lote(self, **kwargs):
        return None

    def _marcas_com_curvas_eletricas(self):
        return {"BYD"}


def _nomes(data):
    return [item["nome"] for item in data["modelos"]]


def test_carros_fipeplus_e_depreciacao_partem_do_mesmo_catalogo_modelos():
    svc = _CatalogProbe()
    livre = svc.listar_modelos_tipo("carros", "13")
    depreciacao = svc.listar_modelos("13", contexto="depreciacao", nome_marca="BYD")
    assert _nomes(livre) == ["Dolphin Mini GL", "Dolphin Mini GS (Elétrico)"]
    assert _nomes(depreciacao) == _nomes(livre)


def test_simular_ve_filtra_metadados_sem_renomear_modelo_canonico():
    svc = _CatalogProbe()
    livre = svc.listar_modelos_tipo("carros", "13")
    simular = svc.listar_modelos("13", contexto="ve", nome_marca="BYD")
    assert _nomes(simular) == _nomes(livre)
    assert [item["codigo"] for item in simular["modelos"]] == ["1001", "1002"]


def test_anos_carros_fipeplus_usam_mesma_lista_canonica():
    svc = _CatalogProbe()
    canon = svc.listar_anos_canonicos_carros("13", "1002")
    livre = svc.listar_anos_tipo("carros", "13", "1002")
    assert livre == canon
    assert livre[0] == {"codigo": "32000-1", "nome": "Zero km Elétrico"}


def test_simular_nao_le_mais_catalogo_fipe_de_localstorage_ou_sessionstorage():
    html = (ROOT / "templates" / "simular.html").read_text(encoding="utf-8")
    assert "plugve:fipe:v2:" not in html
    assert "FIPE_CACHE_TTL_PLUGVE" not in html
    inicio = html.index("async function fetchJsonFipePlugVE(url)")
    fim = html.index("function normalizarNomeModeloOptionPlugVE", inicio)
    helper = html[inicio:fim]
    assert 'cache: "no-store"' in helper
    assert "localStorage" not in helper
    assert "sessionStorage" not in helper


def test_fipeplus_nao_mantem_catalogo_fipe_independente_no_navegador():
    html = (ROOT / "templates" / "consulta_fipe.html").read_text(encoding="utf-8")
    assert "plugve:fipe-publica:" not in html
    assert "CACHE_TTL_CATALOGO_FIPE" not in html
    assert "cache:'no-store'" in html
    assert "catalogo=v49_04" in html


def test_depreciacao_pede_catalogo_v49_04_sem_cache_do_navegador():
    js = (ROOT / "static" / "js" / "fipe.js").read_text(encoding="utf-8")
    assert "catalogo=v49_04" in js
    assert 'cache: "no-store"' in js
    html = (ROOT / "templates" / "depreciacao.html").read_text(encoding="utf-8")
    assert "20260809_v49_04_catalogo_canonico" in html


def test_backend_desabilita_cache_http_independente_do_cliente():
    source = (ROOT / "routes" / "fipe_routes.py").read_text(encoding="utf-8")
    assert source.count('resp.headers["Cache-Control"] = "no-store, max-age=0"') >= 2
    assert 'resp.headers["X-CurVE-FIPE-Catalog"] = "canonical-v49.04"' in source
