from __future__ import annotations

import json
import sys
import types
from pathlib import Path

if "flask" not in sys.modules:
    flask_stub = types.ModuleType("flask")
    flask_stub.current_app = None
    sys.modules["flask"] = flask_stub

import services.fipe_service as fipe_module
from services.fipe_service import FipeService

ROOT = Path(__file__).resolve().parents[1]


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


class _Service(FipeService):
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def _get_json(self, endpoint: str):
        self.calls.append(endpoint)
        if endpoint not in self.responses:
            raise AssertionError(f"endpoint inesperado: {endpoint}")
        return self.responses[endpoint]


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _service(tmp_path: Path, *, completo: bool = False) -> _Service:
    cache = tmp_path / "fipe_cache"
    cache.mkdir(parents=True, exist_ok=True)
    fipe_module.current_app = _FakeCurrentApp(cache)

    _write(cache / "marcas_varridas.json", {
        "22": {"codigo_marca": "22", "marca": "Ford", "modelos_validos": 2, "modelos_bloqueados": 1}
    })
    _write(cache / "marcas_bloqueadas.json", {})
    _write(cache / "modelos_bloqueados.json", {
        "22": {"773": {"codigo_modelo": "773", "modelo": "Fiesta Class 1.0 2p", "motivo": "sem_ano_2012_ou_zero_km"}}
    })
    _write(cache / "modelos_zero_km.json", {})
    _write(cache / "modelos_novos.json", {})
    _write(cache / "progresso_varredura.json", {})
    _write(cache / "catalogo_elegibilidade_fipe_v1.json", {
        "schema_version": "catalogo_elegibilidade_fipe_v1", "modelos": {}, "anos": {}, "atualizado_em": None
    })
    modelos_v2 = {
        "773": {"elegivel": False, "origem": "modelos_bloqueados", "modelo": "Fiesta Class 1.0 2p"},
    }
    if completo:
        modelos_v2["900"] = {"elegivel": True, "origem": "fipe_anos_exato", "modelo": "Focus 2018"}
    _write(cache / "catalogo_elegibilidade_fipe_v2.json", {
        "schema_version": "catalogo_elegibilidade_fipe_v2",
        "modo": "allowlist_exata" if completo else "baseline_varredura_render",
        "marcas": {
            "22": {
                "marca": "Ford",
                "status": "completo" if completo else "varrida_legacy",
                "modelos": modelos_v2,
            }
        },
        "atualizado_em": "2026-09-05T00:00:00-03:00",
    })

    return _Service({
        "marcas/22/modelos": {"modelos": [
            {"codigo": "773", "nome": "Fiesta Class 1.0 2p"},
            {"codigo": "900", "nome": "Focus 2018"},
            {"codigo": "999", "nome": "Modelo novo não verificado"},
        ]},
    })


def test_seed_v2_compila_varredura_real_recebida():
    dados = json.loads((ROOT / "data" / "fipe_cache" / "catalogo_elegibilidade_fipe_v2.json").read_text(encoding="utf-8"))
    assert dados["schema_version"] == "catalogo_elegibilidade_fipe_v2"
    assert len(dados["marcas"]) == 107
    assert dados["marcas"]["22"]["status"] == "varrida_legacy"
    assert dados["marcas"]["22"]["modelos"]["773"]["elegivel"] is False


def test_baseline_varrido_entrega_lista_inteira_sem_consultar_anos(tmp_path: Path):
    svc = _service(tmp_path, completo=False)
    data = svc.listar_modelos("22", contexto="depreciacao", nome_marca="Ford", verificar_pendentes=False)
    assert [m["nome"] for m in data["modelos"]] == ["Focus 2018", "Modelo novo não verificado"]
    assert all(not call.endswith("/anos") for call in svc.calls)
    assert data["catalogo_incompleto"] is False
    assert data["verificacao_temporal_em_lotes"] is False


def test_catalogo_v2_completo_e_allowlist_e_nao_exibe_codigo_novo(tmp_path: Path):
    svc = _service(tmp_path, completo=True)
    data = svc.listar_modelos("22", contexto="depreciacao", nome_marca="Ford", verificar_pendentes=False)
    assert [m["nome"] for m in data["modelos"]] == ["Focus 2018"]
    assert all(not call.endswith("/anos") for call in svc.calls)


def test_fipe_plus_continua_integral_sem_recorte_temporal(tmp_path: Path):
    svc = _service(tmp_path, completo=True)
    data = svc.listar_modelos_tipo("carros", "22")
    assert [m["nome"] for m in data["modelos"]] == [
        "Fiesta Class 1.0 2p", "Focus 2018", "Modelo novo não verificado"
    ]


def test_segunda_abertura_reutiliza_cache_da_lista_filtrada(tmp_path: Path):
    svc = _service(tmp_path, completo=True)
    svc.listar_modelos("22", contexto="depreciacao", nome_marca="Ford", verificar_pendentes=False)
    primeira = list(svc.calls)
    segunda = svc.listar_modelos("22", contexto="depreciacao", nome_marca="Ford", verificar_pendentes=False)
    assert segunda["cache_modelos_filtrados"] is True
    assert svc.calls == primeira



def test_cache_filtrado_invalida_quando_catalogo_v2_muda(tmp_path: Path):
    svc = _service(tmp_path, completo=True)
    primeira = svc.listar_modelos("22", contexto="depreciacao", nome_marca="Ford", verificar_pendentes=False)
    assert [m["nome"] for m in primeira["modelos"]] == ["Focus 2018"]
    cache = tmp_path / "fipe_cache" / "catalogo_elegibilidade_fipe_v2.json"
    dados = json.loads(cache.read_text(encoding="utf-8"))
    dados["marcas"]["22"]["modelos"]["999"] = {"elegivel": True, "modelo": "Modelo novo não verificado"}
    cache.write_text(json.dumps(dados, ensure_ascii=False) + " ", encoding="utf-8")
    segunda = svc.listar_modelos("22", contexto="depreciacao", nome_marca="Ford", verificar_pendentes=False)
    assert segunda["cache_modelos_filtrados"] is False
    assert [m["nome"] for m in segunda["modelos"]] == ["Focus 2018", "Modelo novo não verificado"]

def test_frontend_nao_faz_polling_incremental_v50_29():
    simular = (ROOT / "templates" / "simular.html").read_text(encoding="utf-8")
    dep = (ROOT / "static" / "js" / "fipe.js").read_text(encoding="utf-8")
    for texto in (simular, dep):
        assert "atualizarPendentesEmLotes" not in texto
        assert 'verificar_temporais", "1"' not in texto
        assert "Atualizando catálogo FIPE..." not in texto
    assert 'catalogo: "v50_29"' in simular
    assert "catalogo=v50_29" in dep


def test_script_de_consolidacao_existe_e_publica_atomico():
    texto = (ROOT / "scripts" / "consolidar_catalogo_fipe_v2.py").read_text(encoding="utf-8")
    assert "listar_modelos_referencia" in texto
    assert "listar_anos_canonicos_carros" in texto
    assert '"status": "completo"' in texto
    assert "temporario.replace(destino)" in texto
    assert "_salvar_checkpoint" in texto
    assert 'status") == "completo"' in texto
    assert "PLUGVE_PREWARM_FIPE" in texto
