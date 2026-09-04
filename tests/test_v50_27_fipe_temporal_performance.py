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
from services.fipe_service import FipeService


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
            "FIPE_TEMPORAL_VERIFY_WORKERS": 4,
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


class _ClassifierProbe:
    def __init__(self):
        self.classify_calls = 0
        self.model_evidence_calls = 0

    def brand_contexts(self, _brand):
        return frozenset({"icev"})

    def classify(self, _brand, _model, year=None, fuel=""):
        self.classify_calls += 1
        return _Decision()

    def model_evidence(self, *_args, **_kwargs):
        self.model_evidence_calls += 1
        return {"found": True, "score": 0.99}


class _TemporalProbe(FipeService):
    def __init__(self, responses: dict[str, object]):
        self.responses = responses
        self.calls: list[str] = []
        self.classifier = _ClassifierProbe()
        self.catalog_writes = 0

    def _get_json(self, endpoint: str):
        self.calls.append(endpoint)
        if endpoint not in self.responses:
            raise AssertionError(f"Endpoint não mapeado: {endpoint}")
        return self.responses[endpoint]

    def _catalog_classifier(self):
        return self.classifier

    def _salvar_decisoes_catalogo_lote(self, **kwargs):
        self.catalog_writes += 1
        return super()._salvar_decisoes_catalogo_lote(**kwargs)


def _write(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _svc(tmp_path: Path) -> _TemporalProbe:
    cache = tmp_path / "fipe_cache"
    cache.mkdir(parents=True, exist_ok=True)
    fipe_module.current_app = _FakeCurrentApp(cache, tmp_path)
    for name in (
        "marcas_varridas.json",
        "marcas_bloqueadas.json",
        "modelos_bloqueados.json",
        "modelos_zero_km.json",
        "modelos_novos.json",
        "progresso_varredura.json",
    ):
        _write(cache / name, {})
    _write(cache / "catalogo_elegibilidade_fipe_v1.json", {
        "schema_version": "catalogo_elegibilidade_fipe_v1",
        "modelos": {},
        "anos": {},
        "atualizado_em": None,
    })
    return _TemporalProbe({
        "marcas": [{"codigo": "21", "nome": "Ford"}],
        "marcas/21/modelos": {"modelos": [
            {"codigo": "100", "nome": "Fiesta Class 1.0 2p"},
            {"codigo": "101", "nome": "New Fiesta 1.6 Flex"},
            {"codigo": "102", "nome": "Modelo Fronteira 2012"},
            {"codigo": "103", "nome": "Modelo Zero km"},
        ]},
        "marcas/21/modelos/100/anos": [
            {"codigo": "2011-1", "nome": "2011 Gasolina"},
            {"codigo": "2010-1", "nome": "2010 Gasolina"},
        ],
        "marcas/21/modelos/101/anos": [
            {"codigo": "2014-3", "nome": "2014 Flex"},
            {"codigo": "2013-3", "nome": "2013 Flex"},
        ],
        "marcas/21/modelos/102/anos": [
            {"codigo": "2012-3", "nome": "2012 Flex"},
            {"codigo": "2011-3", "nome": "2011 Flex"},
        ],
        "marcas/21/modelos/103/anos": [
            {"codigo": "32000-3", "nome": "Zero km Flex"},
            {"codigo": "2026-3", "nome": "2026 Flex"},
        ],
    })


def test_fiesta_antigo_nao_escapa_por_pbev_ou_marca_varrida(tmp_path: Path):
    svc = _svc(tmp_path)
    cache = Path(fipe_module.current_app.config["FIPE_CACHE_DIR"])
    # Reproduz a fragilidade antiga: marca constava como varrida e o PBEV
    # consideraria o nome Fiesta uma evidência contemporânea.
    _write(cache / "marcas_varridas.json", {
        "21": {"codigo_marca": "21", "marca": "Ford", "modelos_validos": 3, "modelos_bloqueados": 0}
    })

    data = svc.listar_modelos("21", contexto="icev", nome_marca="Ford")
    nomes = [item["nome"] for item in data["modelos"]]
    assert "Fiesta Class 1.0 2p" not in nomes
    assert "New Fiesta 1.6 Flex" in nomes
    assert "Modelo Fronteira 2012" in nomes
    assert "Modelo Zero km" in nomes
    assert svc.classifier.model_evidence_calls == 0

    indice = json.loads((cache / "catalogo_elegibilidade_fipe_v1.json").read_text(encoding="utf-8"))
    old = indice["modelos"]["21"]["100"]
    assert old["temporal_verificado"] is True
    assert old["elegivel_2012_ou_zero_km"] is False
    assert old["origem_temporal"] == "fipe_anos_exato"


def test_cache_backend_evitar_reprocessar_marca_e_pbev(tmp_path: Path):
    svc = _svc(tmp_path)
    primeiro = svc.listar_modelos("21", contexto="icev", nome_marca="Ford")
    calls_apos_primeiro = list(svc.calls)
    classify_apos_primeiro = svc.classifier.classify_calls
    writes_apos_primeiro = svc.catalog_writes

    segundo = svc.listar_modelos("21", contexto="icev", nome_marca="Ford")
    assert [x["codigo"] for x in segundo["modelos"]] == [x["codigo"] for x in primeiro["modelos"]]
    assert segundo["cache_modelos_filtrados"] is True
    assert svc.calls == calls_apos_primeiro
    assert svc.classifier.classify_calls == classify_apos_primeiro
    assert svc.catalog_writes == writes_apos_primeiro


def test_estado_temporal_persistido_evitar_novas_consultas_de_anos(tmp_path: Path):
    svc = _svc(tmp_path)
    svc.listar_modelos("21", contexto="depreciacao", nome_marca="Ford")
    chamadas_anos_primeira = [c for c in svc.calls if c.endswith("/anos")]
    assert len(chamadas_anos_primeira) == 4

    # Simula novo processo: descarta cache final em memória, mas mantém o índice
    # persistido. A lista volta sem consultar /anos novamente.
    svc._filtered_model_cache = {}
    svc.calls.clear()
    data = svc.listar_modelos("21", contexto="depreciacao", nome_marca="Ford")
    assert [x["codigo"] for x in data["modelos"]] == ["101", "102", "103"]
    assert [c for c in svc.calls if c.endswith("/anos")] == []


def test_fipeplus_continua_integral_com_modelo_pre_2012(tmp_path: Path):
    svc = _svc(tmp_path)
    modelos = svc.listar_modelos_tipo("carros", "21")
    assert any(item["nome"] == "Fiesta Class 1.0 2p" for item in modelos["modelos"])
    anos = svc.listar_anos_tipo("carros", "21", "100")
    assert [item["codigo"] for item in anos] == ["2011-1", "2010-1"]


def test_varredura_sem_contexto_tambem_grava_decisao_temporal_exata(tmp_path: Path):
    svc = _svc(tmp_path)
    anos = svc.listar_anos("21", "100", contexto="")
    assert [item["codigo"] for item in anos] == ["2011-1", "2010-1"]
    cache = Path(fipe_module.current_app.config["FIPE_CACHE_DIR"])
    indice = json.loads((cache / "catalogo_elegibilidade_fipe_v1.json").read_text(encoding="utf-8"))
    assert indice["modelos"]["21"]["100"]["elegivel_2012_ou_zero_km"] is False


def test_protecao_nominal_nao_pode_vencer_resposta_fipe_valida():
    js = (ROOT / "static" / "js" / "fipe.js").read_text(encoding="utf-8")
    assert "modeloProtegidoContraBloqueioAutomatico" not in js
    assert "const podeBloquearComSeguranca = listaAnos.length > 0;" in js
    assert "if (!Array.isArray(anosOriginais) || !anosOriginais.length)" in js


def test_marcadores_curvas_permanecem_desacoplados_do_filtro_temporal():
    simular = (ROOT / "templates" / "simular.html").read_text(encoding="utf-8")
    depreciacao = (ROOT / "static" / "js" / "depreciacao.js").read_text(encoding="utf-8")
    marker_js = (ROOT / "static" / "js" / "curve_marcadores_curvas.js").read_text(encoding="utf-8")
    assert "/api/depreciacao/marcadores_curvas" in simular
    assert "aplicarMarcadorCurvaOptionPlugVE" in simular
    assert "✓" in simular
    assert "/api/depreciacao/marcadores_curvas" in depreciacao
    assert "aplicarChecksModelosFipe" in depreciacao
    assert "aplicarNoOption" in marker_js
