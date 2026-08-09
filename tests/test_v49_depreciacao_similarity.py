from __future__ import annotations

import sys
import types

try:
    import flask  # noqa: F401
except ModuleNotFoundError:  # sandbox de análise sem Flask
    fake_flask = types.ModuleType("flask")
    fake_flask.current_app = types.SimpleNamespace(config={})
    sys.modules["flask"] = fake_flask

from core.modelos import VeiculoSelecionado
from repositories.curvas_repository import CurvasRepository
from services.depreciacao_service import DepreciacaoService


def _veiculo(**overrides) -> VeiculoSelecionado:
    payload = {
        "tipo": "auto", "codigo_marca": "56", "codigo_modelo": "9999",
        "codigo_ano": "32000-1", "codigo_fipe": "002999-9", "marca": "Toyota",
        "modelo": "YARIS Cross XRE 1.5 16V 5p Aut. (Híbrido)", "ano_modelo": "32000",
        "ano_modelo_raw": "32000", "combustivel": "Híbrido", "valor_atual": 174435,
        "horizonte_anos": 10,
    }
    payload.update(overrides)
    return VeiculoSelecionado.from_payload(payload)


def test_v49_hev_convencional_usa_base_combustao():
    service = DepreciacaoService.__new__(DepreciacaoService)
    assert service._detectar_tipo_por_veiculo(_veiculo()) == "combustao"


def test_v49_flex_usa_base_combustao():
    service = DepreciacaoService.__new__(DepreciacaoService)
    assert service._detectar_tipo_por_veiculo(_veiculo(modelo="YARIS Cross XRX 1.5 16V 5p Aut.", combustivel="Flex")) == "combustao"


def test_v49_phev_continua_usando_base_eletrica():
    service = DepreciacaoService.__new__(DepreciacaoService)
    assert service._detectar_tipo_por_veiculo(_veiculo(marca="Volvo", modelo="XC60 T8 Recharge Plug-in Hybrid", combustivel="Híbrido")) == "eletrico"


def test_v49_bev_continua_usando_base_eletrica():
    service = DepreciacaoService.__new__(DepreciacaoService)
    assert service._detectar_tipo_por_veiculo(_veiculo(marca="Volvo", modelo="EX30 Ultra", combustivel="Elétrico")) == "eletrico"


def test_v49_similaridade_aceita_ids_iguais_mesmo_se_nome_mudou():
    repo = CurvasRepository.__new__(CurvasRepository)
    vinculo = {"tipo": "combustao", "marca_id": "56", "modelo_id": "9999", "marca": "Toyota", "modelo": "Nome antigo"}
    assert repo._vinculo_corresponde_veiculo(vinculo, _veiculo(), "combustao") is True


def test_v49_similaridade_aceita_id_modelo_alterado_com_nome_exato():
    repo = CurvasRepository.__new__(CurvasRepository)
    vinculo = {"tipo": "combustao", "marca_id": "56", "modelo_id": "1234", "marca": "Toyota", "modelo": "YARIS Cross XRE 1.5 16V 5p Aut. (Híbrido)"}
    assert repo._vinculo_corresponde_veiculo(vinculo, _veiculo(), "combustao") is True


def test_v49_similaridade_nome_exato_tolera_formatacao_de_pontuacao():
    repo = CurvasRepository.__new__(CurvasRepository)
    vinculo = {"tipo": "combustao", "marca_id": "56", "modelo_id": "1234", "marca": "Toyota", "modelo": "YARIS Cross XRE 1.5 16V 5p Aut. (Híbrido)"}
    veiculo = _veiculo(modelo="YARIS Cross XRE 1-5 16V 5p Aut Híbrido")
    assert repo._vinculo_corresponde_veiculo(vinculo, veiculo, "combustao") is True


def test_v49_similaridade_nao_faz_fuzzy_quando_ids_divergem():
    repo = CurvasRepository.__new__(CurvasRepository)
    vinculo = {"tipo": "combustao", "marca_id": "56", "modelo_id": "1234", "marca": "Toyota", "modelo": "YARIS Cross XRX 1.5 16V 5p Aut."}
    assert repo._vinculo_corresponde_veiculo(vinculo, _veiculo(), "combustao") is False


def test_v49_similaridade_respeita_tipo_da_arvore():
    repo = CurvasRepository.__new__(CurvasRepository)
    vinculo = {"tipo": "eletrico", "marca_id": "56", "modelo_id": "9999", "marca": "Toyota", "modelo": "YARIS Cross XRE 1.5 16V 5p Aut. (Híbrido)"}
    assert repo._vinculo_corresponde_veiculo(vinculo, _veiculo(), "combustao") is False
