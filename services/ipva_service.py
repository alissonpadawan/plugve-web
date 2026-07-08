"""Serviço central de estimativa de IPVA da CurVE.

A regra fica concentrada aqui para que Simular e Consulta Fipe+ consumam o
mesmo cálculo. A estimativa aplica a ordem operacional:

1. imunidade/isenção por idade do veículo;
2. benefício por tecnologia, quando parametrizado;
3. alíquota estadual normal por categoria, potência, cilindrada, valor ou combustível.

Observação metodológica: quando a CurVE recebe apenas ano-modelo FIPE, esse ano
é usado como aproximação. A regra fiscal oficial pode usar o ano de fabricação
constante no CRLV.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import re
import unicodedata
from typing import Any


def _normalizar(valor: Any) -> str:
    texto = str(valor or "").strip().upper()
    texto = "".join(
        c for c in unicodedata.normalize("NFD", texto)
        if unicodedata.category(c) != "Mn"
    )
    return re.sub(r"\s+", " ", texto).strip()


def _to_float(valor: Any) -> float | None:
    if valor is None:
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    txt = str(valor).strip().replace("R$", "").replace("%", "")
    if not txt:
        return None
    try:
        if "," in txt:
            txt = txt.replace(".", "").replace(",", ".")
        return float(txt)
    except ValueError:
        return None


def _to_int(valor: Any) -> int | None:
    n = _to_float(valor)
    if n is None:
        return None
    try:
        return int(round(n))
    except (TypeError, ValueError):
        return None


def _to_bool(valor: Any) -> bool | None:
    if valor is None or valor == "":
        return None
    if isinstance(valor, bool):
        return valor
    txt = _normalizar(valor)
    if txt in {"1", "S", "SIM", "TRUE", "VERDADEIRO", "YES", "Y"}:
        return True
    if txt in {"0", "N", "NAO", "NÃO", "FALSE", "FALSO", "NO"}:
        return False
    return None


@dataclass
class IpvaResultado:
    uf: str
    valor_base: float
    ipva: float
    aliquota: float
    aliquota_percentual: float
    criterio: str
    regra: str
    ano_fabricacao: int | None
    ano_calendario: int
    idade_veiculo: int | None
    combustivel: str
    tipo_propulsao: str
    tecnologia: str
    potencia_cv: float | None
    cilindrada_cc: int | None
    isento: bool
    isencao_idade: bool
    beneficio_tecnologia: bool
    observacao: str
    memoria: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class IpvaService:
    """Motor único de IPVA usado pelas rotas do site."""

    # Alíquota prática para automóvel de passeio, quando não há regra específica.
    ALIQUOTAS_PADRAO = {
        "AC": 0.0200, "AP": 0.0300, "BA": 0.0250, "DF": 0.0300,
        "ES": 0.0200, "MG": 0.0400, "PA": 0.0250, "PB": 0.0250,
        "PE": 0.0240, "PR": 0.0190, "RN": 0.0300, "RR": 0.0250,
        "RS": 0.0300, "SC": 0.0200, "SP": 0.0400,
    }

    # Isenção/imunidade operacional por idade para carros de passeio.
    # A partir de 2026, usa piso nacional de 20 anos, preservando UFs mais benéficas.
    ANOS_ISENCAO_IDADE = {
        "AC": 20, "AL": 15, "AP": 10, "AM": 15, "BA": 15, "CE": 15,
        "DF": 15, "ES": 15, "GO": 15, "MA": 15, "MT": 18, "MS": 15,
        "MG": 20, "PA": 15, "PB": 15, "PR": 20, "PE": 20, "PI": 15,
        "RJ": 15, "RN": 10, "RO": 15, "RR": 10, "RS": 20, "SC": 20,
        "SE": 15, "SP": 20, "TO": 20,
    }

    @classmethod
    def calcular(
        cls,
        *,
        uf: str,
        valor_veiculo: float,
        ano_fabricacao: Any = None,
        combustivel: str = "",
        tipo_propulsao: str = "",
        potencia_cv: Any = None,
        cilindrada_cc: Any = None,
        motor: str = "",
        categoria: str = "",
        uso: str = "particular",
        ano_calendario: Any = None,
        ano_aquisicao: Any = None,
        valor_primeira_compra: Any = None,
        compra_local: Any = None,
        zero_km: Any = None,
    ) -> dict[str, Any]:
        uf = _normalizar(uf)[:2]
        valor = float(valor_veiculo or 0.0)
        ano_calc = _to_int(ano_calendario) or datetime.now().year
        ano_fab = cls._normalizar_ano(ano_fabricacao)
        ano_aq = cls._normalizar_ano(ano_aquisicao) or ano_fab or ano_calc
        idade = max(0, ano_calc - ano_fab) if ano_fab else None
        combustivel_norm = _normalizar(combustivel)
        tipo_norm = _normalizar(tipo_propulsao)
        categoria_norm = _normalizar(categoria)
        uso_norm = _normalizar(uso or "particular")
        potencia = _to_float(potencia_cv)
        cilindrada = _to_int(cilindrada_cc) or cls._inferir_cilindrada_cc(motor)
        valor_primeira = _to_float(valor_primeira_compra) or valor
        compra_local_bool = _to_bool(compra_local)
        zero_km_bool = _to_bool(zero_km)
        tecnologia = cls._classificar_tecnologia(combustivel_norm, tipo_norm)

        if valor <= 0:
            return cls._resultado(
                uf, 0.0, 0.0, "valor_indisponivel", "Valor FIPE/venal não informado",
                ano_fab, ano_calc, idade, combustivel_norm, tipo_norm, tecnologia,
                potencia, cilindrada, False, False, False,
                "IPVA não calculado porque o valor base é zero ou ausente.",
            )

        # 1) Isenção/imunidade por idade vem antes da alíquota.
        limite_idade = cls.ANOS_ISENCAO_IDADE.get(uf, 20 if ano_calc >= 2026 else None)
        if limite_idade is not None and idade is not None and idade >= limite_idade:
            obs = (
                f"IPVA zerado por idade do veículo em {uf}. "
                "Estimativa usa o ano informado pela FIPE/usuário; a regra oficial pode usar o ano de fabricação do CRLV."
            )
            return cls._resultado(
                uf, valor, 0.0, "isencao_idade", f"{uf}: isenção/imunidade por idade a partir de {limite_idade} anos",
                ano_fab, ano_calc, idade, combustivel_norm, tipo_norm, tecnologia,
                potencia, cilindrada, True, True, False, obs,
            )

        # 2) Benefício por tecnologia, quando a regra está parametrizada.
        beneficio = cls._beneficio_tecnologia(
            uf=uf,
            valor=valor,
            valor_primeira_compra=valor_primeira,
            tecnologia=tecnologia,
            combustivel=combustivel_norm,
            tipo_propulsao=tipo_norm,
            ano_calendario=ano_calc,
            ano_aquisicao=ano_aq,
            compra_local=compra_local_bool,
            zero_km=zero_km_bool,
        )
        if beneficio is not None:
            return cls._resultado(
                uf, valor, beneficio["aliquota"], beneficio["criterio"], beneficio["regra"],
                ano_fab, ano_calc, idade, combustivel_norm, tipo_norm, tecnologia,
                potencia, cilindrada, beneficio["aliquota"] == 0.0, False, True, beneficio.get("observacao", ""),
            )

        # 3) Alíquota estadual normal.
        aliquota, criterio, regra, obs = cls._selecionar_aliquota(
            uf=uf,
            valor=valor,
            combustivel=combustivel_norm,
            tipo_propulsao=tipo_norm,
            tecnologia=tecnologia,
            potencia_cv=potencia,
            cilindrada_cc=cilindrada,
            categoria=categoria_norm,
            uso=uso_norm,
        )
        return cls._resultado(
            uf, valor, aliquota, criterio, regra, ano_fab, ano_calc, idade,
            combustivel_norm, tipo_norm, tecnologia, potencia, cilindrada, False, False, False, obs,
        )

    @staticmethod
    def _normalizar_ano(ano: Any) -> int | None:
        txt = str(ano or "").strip()
        if txt.startswith("32000"):
            return datetime.now().year
        m = re.search(r"(19\d{2}|20\d{2})", txt)
        if not m:
            return None
        return int(m.group(1))

    @staticmethod
    def _inferir_cilindrada_cc(motor: str) -> int | None:
        texto = _normalizar(motor)
        if not texto or "ELETR" in texto:
            return None
        m_cc = re.search(r"\b(\d{3,4})\s*CC\b", texto)
        if m_cc:
            return int(m_cc.group(1))
        m = re.search(r"\b([1-6])(?:[\.,](\d))\b", texto)
        if m:
            litros = float(f"{m.group(1)}.{m.group(2)}")
            return int(round(litros * 1000))
        return None

    @staticmethod
    def _classificar_tecnologia(combustivel: str, tipo_propulsao: str) -> str:
        txt = f" {combustivel} {tipo_propulsao} "
        if "HIDROGEN" in txt:
            return "HIDROGENIO"
        if any(t in txt for t in ["PHEV", "PLUG", "DM-I", "DMI", " DM ", "HIBRIDO PLUG"]):
            return "PHEV"
        if "ELETR" in txt and not any(t in txt for t in ["HIBRID", "HYBRID"]):
            return "BEV"
        if any(t in txt for t in ["HIBRID", "HYBRID", "HEV", "MHEV"]):
            return "HEV"
        if "GNV" in txt or "GAS NATURAL" in txt:
            return "GNV"
        if "DIESEL" in txt:
            return "DIESEL"
        if any(t in txt for t in ["FLEX", "ETANOL", "ALCOOL", "ÁLCOOL"]):
            return "FLEX"
        if "GASOLINA" in txt:
            return "GASOLINA"
        return ""

    @staticmethod
    def _is_diesel(combustivel: str, tecnologia: str) -> bool:
        return tecnologia == "DIESEL" or "DIESEL" in combustivel

    @staticmethod
    def _is_gnv(combustivel: str, tecnologia: str) -> bool:
        return tecnologia == "GNV" or "GNV" in combustivel or "GAS NATURAL" in combustivel

    @staticmethod
    def _faixa_potencia(
        potencia: float | None,
        faixas: list[tuple[float | None, float]],
        fallback: float,
    ) -> tuple[float, bool]:
        if potencia is None or potencia <= 0:
            return fallback, False
        for limite, aliquota in faixas:
            if limite is None or potencia <= limite:
                return aliquota, True
        return faixas[-1][1], True

    @staticmethod
    def _idade_beneficio(ano_calendario: int, ano_aquisicao: int | None) -> int:
        if not ano_aquisicao:
            return 0
        return max(0, ano_calendario - ano_aquisicao)

    @classmethod
    def _beneficio_tecnologia(
        cls,
        *,
        uf: str,
        valor: float,
        valor_primeira_compra: float,
        tecnologia: str,
        combustivel: str,
        tipo_propulsao: str,
        ano_calendario: int,
        ano_aquisicao: int | None,
        compra_local: bool | None,
        zero_km: bool | None,
    ) -> dict[str, Any] | None:
        if tecnologia not in {"BEV", "PHEV", "HEV", "HIDROGENIO"}:
            return None

        idade_beneficio = cls._idade_beneficio(ano_calendario, ano_aquisicao)
        grupo_hibrido = tecnologia in {"PHEV", "HEV"}

        if uf == "AL":
            if tecnologia == "BEV":
                aliquota = 0.0 if idade_beneficio == 0 else (0.005 if idade_beneficio == 1 else 0.010)
                faixa = "primeiro ano" if idade_beneficio == 0 else ("segundo ano" if idade_beneficio == 1 else "terceiro ano em diante")
                return {"aliquota": aliquota, "criterio": "tecnologia_temporal", "regra": f"AL: BEV com benefício por tempo desde aquisição/emplacamento ({faixa})", "observacao": "Ano de aquisição/emplacamento estimado pelo ano informado quando não houver dado específico."}
            if grupo_hibrido:
                aliquota = 0.0 if idade_beneficio == 0 else (0.0075 if idade_beneficio == 1 else 0.015)
                faixa = "primeiro ano" if idade_beneficio == 0 else ("segundo ano" if idade_beneficio == 1 else "terceiro ano em diante")
                return {"aliquota": aliquota, "criterio": "tecnologia_temporal", "regra": f"AL: híbrido/PHEV com benefício por tempo desde aquisição/emplacamento ({faixa})", "observacao": "Ano de aquisição/emplacamento estimado pelo ano informado quando não houver dado específico."}

        if uf == "AP":
            if tecnologia == "BEV":
                if ano_calendario <= 2026:
                    aliquota = 0.0
                    faixa = "até 2026"
                elif ano_calendario == 2027:
                    aliquota = 0.005
                    faixa = "2027"
                elif ano_calendario == 2028:
                    aliquota = 0.010
                    faixa = "2028"
                elif ano_calendario == 2029:
                    aliquota = 0.020
                    faixa = "2029"
                else:
                    aliquota = 0.030
                    faixa = "2030 em diante"
                return {"aliquota": aliquota, "criterio": "tecnologia_temporal", "regra": f"AP: BEV com regra temporal ({faixa})", "observacao": "Para isenção até 2026, considerar condição de aquisição dentro da janela legal."}
            if grupo_hibrido:
                if ano_calendario <= 2026:
                    aliquota = 0.0
                    faixa = "até 2026"
                elif ano_calendario == 2027:
                    aliquota = 0.0075
                    faixa = "2027"
                elif ano_calendario == 2028:
                    aliquota = 0.015
                    faixa = "2028"
                elif ano_calendario == 2029:
                    aliquota = 0.025
                    faixa = "2029"
                else:
                    aliquota = 0.030
                    faixa = "2030 em diante"
                return {"aliquota": aliquota, "criterio": "tecnologia_temporal", "regra": f"AP: híbrido/PHEV com regra temporal ({faixa})", "observacao": "Para isenção até 2026, considerar condição de aquisição dentro da janela legal."}

        if uf == "RN" and tecnologia == "BEV":
            if ano_calendario <= 2024:
                aliquota = 0.0
                faixa = "até 2024"
            elif ano_calendario == 2025:
                aliquota = 0.005
                faixa = "2025"
            elif ano_calendario == 2026:
                aliquota = 0.010
                faixa = "2026"
            else:
                aliquota = 0.015
                faixa = "2027 em diante"
            return {"aliquota": aliquota, "criterio": "tecnologia_temporal", "regra": f"RN: BEV com alíquota escalonada ({faixa})", "observacao": "Regra temporal aplicada por exercício fiscal."}

        if uf == "AM" and tecnologia in {"BEV", "PHEV", "HEV"}:
            return {"aliquota": 0.015, "criterio": "tecnologia", "regra": "AM: elétrico/híbrido com alíquota reduzida", "observacao": "Benefício tecnológico aplicado pela classificação BEV/HEV/PHEV."}

        if uf == "BA" and tecnologia == "BEV" and valor <= 300000:
            return {"aliquota": 0.0, "criterio": "tecnologia_teto_valor", "regra": "BA: BEV até R$ 300 mil", "observacao": "Teto avaliado pelo valor FIPE/venal disponível na CurVE."}

        if uf == "PA" and tecnologia == "BEV" and valor_primeira_compra <= 150000:
            return {"aliquota": 0.0, "criterio": "tecnologia_teto_valor", "regra": "PA: BEV até R$ 150 mil", "observacao": "Teto avaliado pelo valor informado; se não houver valor de primeira compra, usa FIPE como aproximação."}

        if uf == "SP" and 2025 <= ano_calendario <= 2026:
            flex_etanol = any(t in combustivel for t in ["FLEX", "ETANOL", "ALCOOL", "ÁLCOOL"])
            if tecnologia == "HIDROGENIO" or (grupo_hibrido and flex_etanol):
                return {"aliquota": 0.0, "criterio": "tecnologia_temporal", "regra": "SP: benefício 2025-2026 para hidrogênio ou híbrido elétrico com etanol/flex", "observacao": "Não aplicado a BEV puro; benefício condicionado aos requisitos legais do estado."}

        if uf == "DF" and tecnologia in {"BEV", "PHEV", "HEV"} and compra_local is True:
            return {"aliquota": 0.0, "criterio": "tecnologia_condicional", "regra": "DF: benefício tecnológico condicionado à aquisição/localidade", "observacao": "Aplicado porque compra/localidade foi confirmada."}

        if uf == "TO" and tecnologia in {"BEV", "PHEV", "HEV"} and compra_local is True:
            return {"aliquota": 0.0, "criterio": "tecnologia_condicional", "regra": "TO: benefício tecnológico condicionado à aquisição no estado", "observacao": "Aplicado porque compra/localidade foi confirmada."}

        return None

    @classmethod
    def _selecionar_aliquota(
        cls,
        *,
        uf: str,
        valor: float,
        combustivel: str,
        tipo_propulsao: str,
        tecnologia: str,
        potencia_cv: float | None,
        cilindrada_cc: int | None,
        categoria: str,
        uso: str,
    ) -> tuple[float, str, str, str]:
        diesel = cls._is_diesel(combustivel, tecnologia)
        gnv = cls._is_gnv(combustivel, tecnologia)
        eletrico = tecnologia == "BEV"
        hibrido = tecnologia in {"HEV", "PHEV"}

        # Potência: só usa quando informada. Sem cv, aplica fallback conservador auditado.
        if uf == "AL":
            aliquota, usou_pot = cls._faixa_potencia(potencia_cv, [(80, 0.0275), (160, 0.0300), (None, 0.0325)], 0.0325)
            return aliquota, "potencia_hp" if usou_pot else "potencia_hp_fallback", "AL: alíquota por faixa de potência", "Potência ausente: usada faixa conservadora." if not usou_pot else ""
        if uf == "CE":
            aliquota, usou_pot = cls._faixa_potencia(potencia_cv, [(100, 0.0250), (180, 0.0300), (None, 0.0350)], 0.0350)
            return aliquota, "potencia_cv" if usou_pot else "potencia_cv_fallback", "CE: alíquota por faixa de potência", "Potência ausente: usada faixa conservadora." if not usou_pot else ""
        if uf == "GO":
            aliquota, usou_pot = cls._faixa_potencia(potencia_cv, [(100, 0.0300), (None, 0.0375)], 0.0375)
            return aliquota, "potencia_cv" if usou_pot else "potencia_cv_fallback", "GO: automóvel de passeio por faixa de potência", "Potência ausente: usada faixa conservadora." if not usou_pot else ""
        if uf == "TO":
            aliquota, usou_pot = cls._faixa_potencia(potencia_cv, [(100, 0.0250), (None, 0.0350)], 0.0350)
            return aliquota, "potencia_hp" if usou_pot else "potencia_hp_fallback", "TO: automóvel/pick-up/furgão por faixa de potência", "Potência ausente: usada faixa conservadora. Benefício tecnológico condicionado não aplicado sem confirmação de compra/localidade." if not usou_pot else "Benefício tecnológico condicionado não aplicado sem confirmação de compra/localidade."

        # Cilindrada / tecnologia.
        if uf == "AM":
            if eletrico or hibrido:
                return 0.0150, "tecnologia", "AM: elétrico/híbrido com alíquota reduzida", ""
            if cilindrada_cc and cilindrada_cc <= 1000:
                return 0.0150, "cilindrada", "AM: até 1.000 cc", ""
            return 0.0200, "cilindrada_fallback", "AM: acima de 1.000 cc ou cilindrada ausente", "Cilindrada ausente: aplicada regra geral acima de 1.000 cc." if not cilindrada_cc else ""
        if uf == "MT":
            if cilindrada_cc and cilindrada_cc <= 1000:
                return 0.0200, "cilindrada", "MT: até 1.000 cc", ""
            return 0.0300, "cilindrada_fallback", "MT: regra geral para automóvel", "Cilindrada ausente: aplicada regra geral." if not cilindrada_cc else ""
        if uf == "RO":
            if cilindrada_cc and cilindrada_cc <= 1000:
                return 0.0200, "cilindrada", "RO: até 1.000 cc", ""
            return 0.0300, "cilindrada_fallback", "RO: acima de 1.000 cc ou regra geral", "Cilindrada ausente: aplicada regra geral." if not cilindrada_cc else ""

        # Valor venal.
        if uf == "MA":
            return (0.0250 if valor <= 150000 else 0.0300), "valor_venal", "MA: faixa por valor venal", ""
        if uf == "PI":
            return (0.0250 if valor <= 150000 else 0.0300), "valor_venal", "PI: faixa por valor venal", ""
        if uf == "SE":
            return (0.0250 if valor <= 120000 else 0.0300), "valor_venal", "SE: faixa por valor venal", ""

        # Combustível / tecnologia.
        if uf == "BA":
            return (0.0300 if diesel else 0.0250), "combustivel", "BA: diesel com alíquota específica; demais passeio 2,5%", ""
        if uf == "MS":
            return (0.0450 if diesel else 0.0300), "combustivel", "MS: diesel com alíquota específica; demais passeio 3,0%", ""
        if uf == "PE":
            if gnv and valor <= 100000:
                return 0.0150, "combustivel", "PE: GNV até R$ 100 mil", ""
            return 0.0240, "categoria", "PE: automóvel de passeio", ""
        if uf == "RJ":
            if eletrico:
                return 0.0050, "tecnologia", "RJ: elétrico", ""
            if gnv or hibrido:
                return 0.0150, "tecnologia", "RJ: GNV/híbrido", ""
            return 0.0400, "combustivel", "RJ: gasolina/flex", ""
        if uf == "RN":
            return (0.0150 if gnv else 0.0300), "combustivel", "RN: GNV reduzido; demais passeio 3,0%", ""

        aliquota = cls.ALIQUOTAS_PADRAO.get(uf, 0.0300)
        obs = ""
        if uf == "DF" and tecnologia in {"BEV", "PHEV", "HEV"}:
            obs = "Benefício tecnológico condicionado não aplicado sem confirmação de compra/localidade."
        return aliquota, "categoria", f"{uf or 'UF'}: alíquota estimada por categoria de automóvel de passeio", obs

    @staticmethod
    def _resultado(
        uf: str,
        valor: float,
        aliquota: float,
        criterio: str,
        regra: str,
        ano_fab: int | None,
        ano_calc: int,
        idade: int | None,
        combustivel: str,
        tipo_propulsao: str,
        tecnologia: str,
        potencia: float | None,
        cilindrada: int | None,
        isento: bool,
        isencao_idade: bool,
        beneficio_tecnologia: bool,
        obs: str,
    ) -> dict[str, Any]:
        ipva = 0.0 if isento else round(valor * aliquota, 2)
        aliquota_pct = round(aliquota * 100, 4)
        memoria = f"IPVA = valor FIPE/venal × alíquota = R$ {valor:,.2f} × {aliquota_pct:.2f}% = R$ {ipva:,.2f}"
        memoria = memoria.replace(",", "X").replace(".", ",").replace("X", ".")
        return IpvaResultado(
            uf=uf,
            valor_base=round(valor, 2),
            ipva=ipva,
            aliquota=aliquota,
            aliquota_percentual=aliquota_pct,
            criterio=criterio,
            regra=regra,
            ano_fabricacao=ano_fab,
            ano_calendario=ano_calc,
            idade_veiculo=idade,
            combustivel=combustivel,
            tipo_propulsao=tipo_propulsao,
            tecnologia=tecnologia,
            potencia_cv=potencia,
            cilindrada_cc=cilindrada,
            isento=isento,
            isencao_idade=isencao_idade,
            beneficio_tecnologia=beneficio_tecnologia,
            observacao=obs,
            memoria=memoria,
        ).to_dict()
