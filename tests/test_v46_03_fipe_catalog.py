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


class _FakeCurrentApp:
    def __init__(self, cache_dir: Path, root: Path):
        self.config = {
            "FIPE_CACHE_DIR": cache_dir,
            "PERSISTENT_DIR": root,
            "DATA_DIR": Path(__file__).resolve().parents[1] / "data",
            "ARQUIVO_PBEV_BASE": Path(__file__).resolve().parents[1] / "data" / "pbev" / "pbev_base_saneada_v1.json",
            "ARQUIVO_PBEV_MANIFEST": Path(__file__).resolve().parents[1] / "data" / "pbev" / "pbev_manifest_validacao_v1.json",
            "ARQUIVO_CURVAS_ELETRICO": Path(__file__).resolve().parents[1] / "data" / "eletrico" / "curvas_depreciacao_ev_v20.csv",
            "ARQUIVO_CURVAS_ELETRICO_BASE": Path(__file__).resolve().parents[1] / "data" / "eletrico" / "curvas_depreciacao_ev_v20.csv",
        }


class CatalogFixtureService(FipeService):
    def __init__(self, responses: dict[str, object]):
        self.responses = responses

    def _get_json(self, endpoint: str):
        if endpoint not in self.responses:
            raise AssertionError(f"Endpoint de teste não mapeado: {endpoint}")
        return self.responses[endpoint]

    def _get_json_tipo(self, tipo_veiculo: str | None, endpoint: str):
        return self._get_json(f"publica/{endpoint}")


def _write(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _service(tmp_path: Path) -> CatalogFixtureService:
    cache = tmp_path / "fipe_cache"
    cache.mkdir(parents=True, exist_ok=True)
    fipe_module.current_app = _FakeCurrentApp(cache, tmp_path)

    _write(cache / "marcas_varridas.json", {
        "10": {"codigo_marca": "10", "marca": "Cadillac", "modelos_validos": 0, "modelos_bloqueados": 1},
        "23": {"codigo_marca": "23", "marca": "GM - Chevrolet", "modelos_validos": 1, "modelos_bloqueados": 1},
        "13": {"codigo_marca": "13", "marca": "BYD", "modelos_validos": 1, "modelos_bloqueados": 0},
        "99": {"codigo_marca": "99", "marca": "GWM", "modelos_validos": 2, "modelos_bloqueados": 0},
    })
    _write(cache / "marcas_bloqueadas.json", {})
    _write(cache / "modelos_bloqueados.json", {
        "23": {
            "2": {"codigo_modelo": "2", "modelo": "AGILE LT 1.4 MPFI 8V FlexPower 5p", "motivo": "sem_ano_2012_ou_zero_km"}
        }
    })
    _write(cache / "modelos_zero_km.json", {})
    _write(cache / "modelos_novos.json", {})
    _write(cache / "progresso_varredura.json", {})
    _write(cache / "catalogo_elegibilidade_fipe_v1.json", {
        "schema_version": "catalogo_elegibilidade_fipe_v1", "modelos": {}, "anos": {}, "atualizado_em": None
    })

    responses = {
        "marcas": [
            {"codigo": "10", "nome": "Cadillac"},
            {"codigo": "23", "nome": "GM - Chevrolet"},
            {"codigo": "13", "nome": "BYD"},
            {"codigo": "99", "nome": "GWM"},
        ],
        "marcas/10/modelos": {"modelos": [{"codigo": "1", "nome": "Deville/Eldorado 4.9"}]},
        "marcas/23/modelos": {"modelos": [
            {"codigo": "2", "nome": "AGILE LT 1.4 MPFI 8V FlexPower 5p"},
            {"codigo": "3", "nome": "Onix 1.0 Flex"},
        ]},
        "marcas/13/modelos": {"modelos": [{"codigo": "4", "nome": "Yuan Pro"}]},
        "marcas/99/modelos": {"modelos": [
            {"codigo": "5", "nome": "Haval H6 HEV"},
            {"codigo": "6", "nome": "Haval H6 PHEV"},
        ]},
        "marcas/10/modelos/1/anos": [
            {"codigo": "1999-1", "nome": "1999 Gasolina"},
            {"codigo": "1998-1", "nome": "1998 Gasolina"},
        ],
        "marcas/23/modelos/2/anos": [{"codigo": "2013-3", "nome": "2013 Flex"}],
        "marcas/23/modelos/3/anos": [
            {"codigo": "2011-3", "nome": "2011 Flex"},
            {"codigo": "2012-3", "nome": "2012 Flex"},
            {"codigo": "32000-3", "nome": "Zero km Flex"},
        ],
        "marcas/13/modelos/4/anos": [{"codigo": "2025-1", "nome": "2025 Elétrico"}],
        "marcas/99/modelos/5/anos": [{"codigo": "2025-3", "nome": "2025 Híbrido"}],
        "marcas/99/modelos/6/anos": [{"codigo": "2025-3", "nome": "2025 Híbrido"}],
        "publica/marcas": [
            {"codigo": "10", "nome": "Cadillac"},
            {"codigo": "23", "nome": "GM - Chevrolet"},
        ],
        "publica/marcas/10/modelos": {"modelos": [{"codigo": "1", "nome": "Deville/Eldorado 4.9"}]},
        "publica/marcas/10/modelos/1/anos": [
            {"codigo": "1999-1", "nome": "1999 Gasolina"},
            {"codigo": "1998-1", "nome": "1998 Gasolina"},
        ],
    }
    return CatalogFixtureService(responses)


def test_depreciacao_oculta_marca_sem_modelo_2012(tmp_path: Path):
    service = _service(tmp_path)
    names = {item["nome"] for item in service.listar_marcas("depreciacao")}
    assert "Cadillac" not in names
    assert {"GM - Chevrolet", "BYD", "GWM"} <= names


def test_modelo_antigo_varrido_nao_aparece(tmp_path: Path):
    service = _service(tmp_path)
    data = service.listar_modelos("23", contexto="depreciacao", nome_marca="GM - Chevrolet")
    assert [item["nome"] for item in data["modelos"]] == ["Onix 1.0 Flex"]
    assert data["modelos_bloqueados_ocultos"] == 1


def test_modelos_sao_separados_por_propulsao(tmp_path: Path):
    service = _service(tmp_path)
    byd_ve = service.listar_modelos("13", contexto="ve", nome_marca="BYD")
    byd_icev = service.listar_modelos("13", contexto="icev", nome_marca="BYD")
    assert [item["nome"] for item in byd_ve["modelos"]] == ["Yuan Pro"]
    assert byd_icev["modelos"] == []

    gwm_ve = service.listar_modelos("99", contexto="ve", nome_marca="GWM")
    gwm_icev = service.listar_modelos("99", contexto="icev", nome_marca="GWM")
    assert [item["nome"] for item in gwm_ve["modelos"]] == ["Haval H6 PHEV"]
    assert [item["nome"] for item in gwm_icev["modelos"]] == ["Haval H6 HEV"]


def test_anos_sao_filtrados_no_backend(tmp_path: Path):
    service = _service(tmp_path)
    dep = service.listar_anos("23", "3", contexto="depreciacao")
    assert [item["codigo"] for item in dep] == ["2012-3", "32000-3"]

    hev_icev = service.listar_anos("99", "5", contexto="icev")
    hev_ve = service.listar_anos("99", "5", contexto="ve")
    phev_ve = service.listar_anos("99", "6", contexto="ve")
    phev_icev = service.listar_anos("99", "6", contexto="icev")
    assert [item["codigo"] for item in hev_icev] == ["2025-3"]
    assert hev_ve == []
    assert [item["codigo"] for item in phev_ve] == ["2025-3"]
    assert phev_icev == []


def test_fipe_publica_continua_com_catalogo_integral(tmp_path: Path):
    service = _service(tmp_path)
    marcas = service.listar_marcas_tipo("carros")
    modelos = service.listar_modelos_tipo("carros", "10")
    anos = service.listar_anos_tipo("carros", "10", "1")
    assert any(item["nome"] == "Cadillac" for item in marcas)
    assert modelos["modelos"][0]["nome"] == "Deville/Eldorado 4.9"
    assert [item["codigo"] for item in anos] == ["1999-1", "1998-1"]


def test_sem_estado_do_robo_pbev_nao_decide_mais_elegibilidade_temporal(tmp_path: Path):
    service = _service(tmp_path)
    cache = Path(fipe_module.current_app.config["FIPE_CACHE_DIR"])
    _write(cache / "marcas_varridas.json", {})
    _write(cache / "marcas_bloqueadas.json", {})
    _write(cache / "modelos_bloqueados.json", {})
    _write(cache / "modelos_zero_km.json", {})
    _write(cache / "catalogo_elegibilidade_fipe_v1.json", {
        "schema_version": "catalogo_elegibilidade_fipe_v1", "modelos": {}, "anos": {}, "atualizado_em": None
    })

    # Marca desconhecida pode ser aberta para verificação, mas modelo desconhecido
    # não é liberado por similaridade PBEV.
    assert service._marca_temporal_permitida("10", nome_marca="Cadillac", estrito=True) is True
    assert service._modelo_temporal_permitido(
        "10", "1", nome_marca="Cadillac", nome_modelo="Deville/Eldorado 4.9", estrito=True
    ) is False
    assert service._modelo_temporal_permitido(
        "23", "3", nome_marca="GM - Chevrolet", nome_modelo="Onix 1.0 Flex", estrito=True
    ) is False

    # listar_modelos() consulta os anos FIPE exatos: Cadillac antigo some e Onix
    # com 2012/Zero km permanece, independentemente da PBEV.
    cadillac = service.listar_modelos("10", contexto="depreciacao", nome_marca="Cadillac")
    onix = service.listar_modelos("23", contexto="depreciacao", nome_marca="GM - Chevrolet")
    assert cadillac["modelos"] == []
    assert [item["nome"] for item in onix["modelos"]] == ["AGILE LT 1.4 MPFI 8V FlexPower 5p", "Onix 1.0 Flex"]


def test_estado_do_robo_nao_e_sobrescrito_pelo_indice_novo(tmp_path: Path):
    service = _service(tmp_path)
    cache = Path(fipe_module.current_app.config["FIPE_CACHE_DIR"])
    antes = json.loads((cache / "marcas_varridas.json").read_text(encoding="utf-8"))

    service.listar_modelos("99", contexto="ve", nome_marca="GWM")

    depois = json.loads((cache / "marcas_varridas.json").read_text(encoding="utf-8"))
    indice = json.loads((cache / "catalogo_elegibilidade_fipe_v1.json").read_text(encoding="utf-8"))
    assert depois == antes
    assert indice["modelos"]["99"]


def test_frontend_forca_nova_versao_do_catalogo_sem_cache_antigo():
    root = Path(__file__).resolve().parents[1]
    simular = (root / "templates" / "simular.html").read_text(encoding="utf-8")
    depreciacao_js = (root / "static" / "js" / "fipe.js").read_text(encoding="utf-8")
    # A intenção original deste teste permanece: uma versão nova de catálogo
    # deve invalidar respostas antigas. V49.04 também elimina o cache local
    # independente da Simular e passa a revalidar no backend canônico.
    assert simular.count('catalogo: "v49_04"') >= 4
    assert simular.count('params.set("catalogo", "v49_04")') >= 2
    assert depreciacao_js.count("catalogo=v49_04") >= 3
    assert "plugve:fipe:v2:" not in simular
