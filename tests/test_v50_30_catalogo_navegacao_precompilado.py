from __future__ import annotations

import json
import shutil
import sys
import time
import types
from pathlib import Path

if "flask" not in sys.modules:
    flask_stub = types.ModuleType("flask")
    flask_stub.current_app = None
    sys.modules["flask"] = flask_stub

import services.fipe_service as fipe_module
from services.fipe_service import FipeService

ROOT = Path(__file__).resolve().parents[1]
CATALOGO = ROOT / "data" / "fipe_cache" / "catalogo_navegacao_fipe_v1.json"


class _FakeCurrentApp:
    def __init__(self, cache_dir: Path):
        self.config = {
            "FIPE_CACHE_DIR": cache_dir,
            "PERSISTENT_DIR": cache_dir.parent,
            "DATA_DIR": ROOT / "data",
            "ARQUIVO_PBEV_BASE": ROOT / "data" / "pbev" / "pbev_base_saneada_v1.json",
            "ARQUIVO_PBEV_MANIFEST": ROOT / "data" / "pbev" / "pbev_manifest_validacao_v1.json",
            "ARQUIVO_CURVAS_ELETRICO": ROOT / "data" / "eletrico" / "curvas_depreciacao_ev_v20.csv",
            "ARQUIVO_CURVAS_ELETRICO_BASE": ROOT / "data" / "eletrico" / "curvas_depreciacao_ev_v20.csv",
        }


class _NoApiService(FipeService):
    def __init__(self):
        self.calls = []

    def _get_json(self, endpoint: str):
        self.calls.append(endpoint)
        raise AssertionError(f"FIPE API não deveria ser chamada na navegação: {endpoint}")


class _FipePlusService(FipeService):
    def __init__(self):
        self.calls = []

    def _get_json(self, endpoint: str):
        self.calls.append(endpoint)
        if endpoint == "marcas/22/modelos":
            return {"modelos": [
                {"codigo": "773", "nome": "Fiesta Class 1.0 2p"},
                {"codigo": "4134", "nome": "Courier Van 1.6/ 1.6 Flex 8V (Carga)"},
            ]}
        if endpoint == "marcas/22/modelos/4134/anos":
            return [
                {"codigo": "2012-1", "nome": "2012 Gasolina"},
                {"codigo": "2011-1", "nome": "2011 Gasolina"},
            ]
        raise AssertionError(f"endpoint inesperado: {endpoint}")


def _prepare(tmp_path: Path, service_cls= _NoApiService):
    cache = tmp_path / "fipe_cache"
    cache.mkdir(parents=True, exist_ok=True)
    shutil.copy2(CATALOGO, cache / CATALOGO.name)
    # arquivos auxiliares mínimos para rotas legadas não interferirem
    for name in (
        "marcas_varridas.json", "marcas_bloqueadas.json", "modelos_bloqueados.json",
        "modelos_zero_km.json", "modelos_novos.json", "progresso_varredura.json",
    ):
        (cache / name).write_text("{}", encoding="utf-8")
    (cache / "catalogo_elegibilidade_fipe_v1.json").write_text(
        json.dumps({"schema_version": "catalogo_elegibilidade_fipe_v1", "modelos": {}, "anos": {}, "atualizado_em": None}),
        encoding="utf-8",
    )
    (cache / "catalogo_elegibilidade_fipe_v2.json").write_text(
        json.dumps({"schema_version": "catalogo_elegibilidade_fipe_v2", "marcas": {}}),
        encoding="utf-8",
    )
    fipe_module.current_app = _FakeCurrentApp(cache)
    return service_cls(), cache


def _catalogo():
    return json.loads(CATALOGO.read_text(encoding="utf-8"))


def test_catalogo_precompilado_tem_schema_e_contagens_esperadas():
    dados = _catalogo()
    assert dados["schema_version"] == "catalogo_navegacao_fipe_v1"
    assert dados["modo"] == "precompilado_offline"
    assert dados["contagens"]["modelos_depreciacao"] == 4494
    assert dados["contagens"]["modelos_ve"] == 348
    assert dados["contagens"]["modelos_icev"] == 4167
    assert dados["contagens"]["marcas"] == 78


def test_regra_temporal_ford_exclui_fiesta_antigo_e_inclui_fronteira_2012():
    modelos = _catalogo()["marcas"]["22"]["modelos"]["depreciacao"]
    ids = {str(item["codigo"]): item for item in modelos}
    assert "773" not in ids  # Fiesta Class 1.0 2p antigo
    assert "4134" in ids
    assert ids["4134"]["ano_maximo"] == 2012


def test_byd_navegacao_fica_no_lado_ve():
    marca = _catalogo()["marcas"]["238"]
    assert marca["marca"] == "BYD"
    assert len(marca["modelos"]["ve"]) > 0
    assert marca["modelos"]["icev"] == []


def test_haval_homologado_permanece_dividido_corretamente():
    marca = _catalogo()["marcas"]["240"]
    ve = {str(item["codigo"]) for item in marca["modelos"]["ve"]}
    icev = {str(item["codigo"]) for item in marca["modelos"]["icev"]}
    # PHEV19 / PHEV34 / PHEV35 / GT
    assert {"11721", "11723", "11794", "11724"} <= ve
    # H6 HEV / HEV2 não plug-in
    assert {"11719", "11720", "11722"} <= icev


def test_marcas_e_modelos_simular_sao_100_porcento_locais(tmp_path: Path):
    svc, _ = _prepare(tmp_path)
    marcas = svc.listar_marcas(contexto="icev")
    assert any(str(item["codigo"]) == "22" for item in marcas)
    data = svc.listar_modelos("22", contexto="icev", nome_marca="Ford")
    assert data["catalogo_navegacao_precompilado"] is True
    assert data["catalogo_estavel"] is True
    assert data["modelos_temporais_pendentes"] == 0
    assert svc.calls == []


def test_depreciacao_usa_mesmo_catalogo_local_sem_api(tmp_path: Path):
    svc, _ = _prepare(tmp_path)
    data = svc.listar_modelos("22", contexto="depreciacao", nome_marca="Ford")
    ids = {str(item["codigo"]) for item in data["modelos"]}
    assert "773" not in ids
    assert "4134" in ids
    assert svc.calls == []


def test_fipe_plus_continua_consultando_catalogo_integral_da_api(tmp_path: Path):
    svc, _ = _prepare(tmp_path, _FipePlusService)
    data = svc.listar_modelos_tipo("carros", "22")
    ids = {str(item["codigo"]) for item in data["modelos"]}
    assert "773" in ids  # antigo continua disponível na Fipe+
    assert "marcas/22/modelos" in svc.calls


def test_anos_do_modelo_selecionado_faz_so_uma_consulta_de_anos(tmp_path: Path):
    svc, _ = _prepare(tmp_path, _FipePlusService)
    anos = svc.listar_anos("22", "4134", contexto="icev")
    assert [item["nome"] for item in anos] == ["2012 Gasolina"]
    assert svc.calls == ["marcas/22/modelos/4134/anos"]


def test_catalogo_em_memoria_e_reutilizado_sem_reler_arquivo(tmp_path: Path):
    svc, cache = _prepare(tmp_path)
    primeira = svc._ler_catalogo_navegacao()
    path = cache / "catalogo_navegacao_fipe_v1.json"
    # segunda leitura com a mesma assinatura deve devolver a mesma instância em memória
    segunda = svc._ler_catalogo_navegacao()
    assert segunda is primeira
    assert path.exists()


def test_lookup_ford_precompilado_e_rapido_e_sem_api(tmp_path: Path):
    svc, _ = _prepare(tmp_path)
    # aquece a leitura do arquivo; mede somente o caminho de navegação em memória
    svc.listar_modelos("22", contexto="icev", nome_marca="Ford")
    inicio = time.perf_counter()
    for _ in range(500):
        data = svc.listar_modelos("22", contexto="icev", nome_marca="Ford")
    duracao = time.perf_counter() - inicio
    assert data["modelos"]
    assert svc.calls == []
    # limite propositalmente folgado para CI/container; objetivo é impedir regressão para varredura/PBEV.
    assert duracao < 2.0


def test_atualizador_publica_catalogo_apenas_de_forma_atomica_e_checkpoint():
    texto = (ROOT / "scripts" / "atualizar_catalogo_navegacao_fipe.py").read_text(encoding="utf-8")
    assert ".build" in texto
    assert "replace(" in texto
    assert "listar_anos_canonicos_carros" in texto
    assert "modelos_novos" in texto or "novos" in texto


def test_persistent_storage_semeia_catalogo_novo_sem_substituir_existente():
    texto = (ROOT / "services" / "persistent_storage.py").read_text(encoding="utf-8")
    assert "catalogo_navegacao_fipe_v1.json" in texto
    assert "_copy_if_missing" in texto


def test_versao_v50_30():
    texto = (ROOT / "config.py").read_text(encoding="utf-8")
    assert 'CURVE_VERSION = "V50.30"' in texto
