from __future__ import annotations

import json
import sys
import types
from pathlib import Path

try:
    import flask  # type: ignore  # noqa: F401
except ModuleNotFoundError:
    flask_stub = types.ModuleType("flask")
    flask_stub.current_app = None
    sys.modules["flask"] = flask_stub

import services.fipe_service as fipe_module
from services.fipe_service import FipeApiError, FipeService

ROOT = Path(__file__).resolve().parents[1]


class _FakeCurrentApp:
    def __init__(self, cache_dir: Path, root: Path):
        self.config = {
            "FIPE_CACHE_DIR": cache_dir,
            "PERSISTENT_DIR": root,
            "DATA_DIR": ROOT / "data",
            "ARQUIVO_PBEV_BASE": ROOT / "data" / "pbev" / "pbev_base_saneada_v1.json",
            "ARQUIVO_PBEV_MANIFEST": ROOT / "data" / "pbev" / "pbev_manifest_validacao_v1.json",
            "ARQUIVO_CURVAS_ELETRICO": ROOT / "data" / "eletrico" / "curvas_depreciacao_ev_v20.csv",
            "ARQUIVO_CURVAS_ELETRICO_BASE": ROOT / "data" / "eletrico" / "curvas_depreciacao_ev_v20.csv",
            "FIPE_FILTERED_MODEL_CACHE_TTL_SECONDS": 300,
            "FIPE_TEMPORAL_VERIFY_WORKERS": 2,
        }


class _Decision:
    contexts = frozenset({"icev"})
    tipo_plugve = "COMBUSTAO"

    def as_dict(self):
        return {
            "contextos": ["icev"],
            "tipo_plugve": "COMBUSTAO",
            "origem_classificacao": "teste",
            "confianca_classificacao": 0.99,
            "score_pbev": 0.99,
            "margem_pbev": 0.8,
        }


class _Classifier:
    def __init__(self):
        self.calls = 0

    def classify(self, *_args, **_kwargs):
        self.calls += 1
        return _Decision()

    def brand_contexts(self, _brand):
        return frozenset({"icev"})


class _Probe(FipeService):
    def __init__(self, responses: dict[str, object]):
        self.responses = responses
        self.calls: list[str] = []
        self.classifier = _Classifier()

    def _get_json(self, endpoint: str):
        self.calls.append(endpoint)
        valor = self.responses[endpoint]
        if isinstance(valor, Exception):
            raise valor
        return valor

    def _catalog_classifier(self):
        return self.classifier


def _write(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _svc(tmp_path: Path) -> _Probe:
    cache = tmp_path / "fipe_cache"
    cache.mkdir(parents=True, exist_ok=True)
    fipe_module.current_app = _FakeCurrentApp(cache, tmp_path)
    for name in (
        "marcas_varridas.json", "marcas_bloqueadas.json", "modelos_bloqueados.json",
        "modelos_zero_km.json", "modelos_novos.json", "progresso_varredura.json",
    ):
        _write(cache / name, {})
    _write(cache / "catalogo_elegibilidade_fipe_v1.json", {
        "schema_version": "catalogo_elegibilidade_fipe_v1",
        "modelos": {}, "anos": {}, "atualizado_em": None,
    })
    return _Probe({
        "marcas/21/modelos": {"modelos": [
            {"codigo": "100", "nome": "Fiesta Class 1.0 2p"},
            {"codigo": "101", "nome": "New Fiesta 1.6 Flex"},
            {"codigo": "102", "nome": "Modelo Fronteira 2012"},
            {"codigo": "103", "nome": "Modelo Zero km"},
        ]},
        "marcas/21/modelos/100/anos": [{"codigo": "2011-1", "nome": "2011 Gasolina"}],
        "marcas/21/modelos/101/anos": [{"codigo": "2014-3", "nome": "2014 Flex"}],
        "marcas/21/modelos/102/anos": [{"codigo": "2012-3", "nome": "2012 Flex"}],
        "marcas/21/modelos/103/anos": [{"codigo": "32000-3", "nome": "Zero km Flex"}],
    })


def test_primeira_resposta_nao_varre_anos_e_nao_libera_desconhecidos(tmp_path: Path):
    svc = _svc(tmp_path)
    data = svc.listar_modelos(
        "21", contexto="icev", nome_marca="Ford",
        verificar_pendentes=False, limite_verificacao=2,
    )
    assert data["modelos"] == []
    assert data["catalogo_incompleto"] is True
    assert data["modelos_temporais_pendentes"] == 4
    assert [c for c in svc.calls if c.endswith("/anos")] == []
    assert svc.classifier.calls == 4


def test_verificacao_em_lotes_de_dois_preserva_regra_2012(tmp_path: Path):
    svc = _svc(tmp_path)
    svc.listar_modelos("21", contexto="icev", nome_marca="Ford", verificar_pendentes=False)

    lote1 = svc.listar_modelos(
        "21", contexto="icev", nome_marca="Ford",
        verificar_pendentes=True, limite_verificacao=2,
    )
    assert [m["codigo"] for m in lote1["modelos"]] == ["101"]
    assert lote1["modelos_temporais_pendentes"] == 2
    assert lote1["modelos_temporais_verificados_nesta_requisicao"] == 2

    lote2 = svc.listar_modelos(
        "21", contexto="icev", nome_marca="Ford",
        verificar_pendentes=True, limite_verificacao=2,
    )
    assert [m["codigo"] for m in lote2["modelos"]] == ["101", "102", "103"]
    assert lote2["modelos_temporais_pendentes"] == 0
    assert lote2["catalogo_incompleto"] is False
    assert len([c for c in svc.calls if c.endswith("/anos")]) == 4


def test_decisao_concluida_e_persistida_mesmo_quando_outro_modelo_falha(tmp_path: Path):
    svc = _svc(tmp_path)
    svc.responses["marcas/21/modelos/101/anos"] = FipeApiError("timeout simulado", None, "years")
    data = svc.listar_modelos(
        "21", contexto="icev", nome_marca="Ford",
        verificar_pendentes=True, limite_verificacao=2,
    )
    assert data["modelos"] == []
    cache = Path(fipe_module.current_app.config["FIPE_CACHE_DIR"])
    indice = json.loads((cache / "catalogo_elegibilidade_fipe_v1.json").read_text(encoding="utf-8"))
    assert indice["modelos"]["21"]["100"]["temporal_verificado"] is True
    assert indice["modelos"]["21"]["100"]["elegivel_2012_ou_zero_km"] is False
    assert indice["modelos"]["21"]["101"].get("temporal_verificado") is not True
    assert data["modelos_temporais_pendentes"] == 3


def test_frontend_usa_resposta_inicial_rapida_e_lotes_progressivos():
    simular = (ROOT / "templates" / "simular.html").read_text(encoding="utf-8")
    depreciacao = (ROOT / "static" / "js" / "fipe.js").read_text(encoding="utf-8")
    for texto in (simular, depreciacao):
        assert 'paramsLote.set("verificar_temporais", "1")' in texto
        assert 'paramsLote.set("limite_verificacao", "2")' in texto
        assert "Atualizando catálogo FIPE..." in texto
        assert "Catálogo FIPE temporariamente incompleto" in texto
    # O endpoint inicial usa os parâmetros-base sem pedir varredura síncrona.
    assert 'fetchJsonFipePlugVE(`/api/fipe/modelos?${paramsBase.toString()}`)' in simular
    assert 'buscarJsonFipeSeguro(`/api/fipe/modelos?${paramsBase.toString()}`)' in depreciacao


def test_versao_v50_28():
    assert 'CURVE_VERSION = "V50.28"' in (ROOT / "config.py").read_text(encoding="utf-8")
