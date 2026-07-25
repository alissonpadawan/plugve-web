from __future__ import annotations

import json
import re
import threading
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

try:
    from flask import current_app
except Exception:  # permite testes locais sem Flask instalado
    current_app = None


BLOQUEIO_AUTOFILL_FLAGS = (
    "flag_bloquear_autofill",
    "flag_outlier_consumo",
    "flag_consumo_ausente",
    "flag_token_cabecalho",
    "flag_eletrico_em_campo_combustivel",
    "flag_combustivel_inconsistente",
    "flag_classificacao_corrompida",
    "flag_revisao_manual",
    "flag_duplicata_suspeita",
)

FUEL_TOKENS = {
    "FLEX", "GASOLINA", "DIESEL", "ETANOL", "ALCOOL", "ALCOOL", "ELETRICO", "ELETRICA",
    "HIBRIDO", "HIBRIDA", "HYBRID", "PHEV", "PLUGIN", "PLUG", "IN", "BEV", "EV",
}
TRANS_TOKENS = {
    "AUT", "AUTO", "AUTOMATICO", "AUTOMATICA", "AT", "A", "CVT", "MTA", "DCT", "DHT",
    "M", "MT", "MANUAL", "MEC", "MECANICO", "MECANICA",
}
ENGINE_TOKENS = {"8V", "10V", "12V", "16V", "20V", "24V", "32V", "40V", "48V", "60V"}
GENERIC_TOKENS = {
    "DE", "DO", "DA", "DOS", "DAS", "E", "COM", "SEM", "PARA", "THE", "OF", "BY",
    "NOVO", "NOVA", "NEW", "ZERO", "KM", "MY", "MODELO", "VERSAO", "VERSÃO",
    "PORTA", "PORTAS", "P", "CV", "HP", "PS", "KW", "TURBO", "T", "TSI", "TFSI", "GDI", "MPI",
    "VVT", "VVTIE", "VVT I", "DOHC", "SOHC", "VALV", "VALVULAS", "VALVULAS",
}
POWER_TOKEN_RE = re.compile(r"^\d{2,4}(?:CV|HP|PS|KW)$")
PORT_TOKEN_RE = re.compile(r"^[1-9]P$")
YEAR_TOKEN_RE = re.compile(r"^(?:19|20)\d{2}$")
SINGLE_DIGIT_MODEL_PREFIXES = {"A", "B", "C", "E", "F", "G", "I", "Q", "S", "T", "X", "Z", "CX", "MX", "RX", "ID"}
# CROSS costuma mudar família/modelo no PBEV e na FIPE (Yaris x Yaris Cross, Corolla x Corolla Cross).
HARD_BODY_TOKENS = {"CROSS", "PICKUP", "PICAPE", "CABINE", "CAB", "SW", "WAGON", "TOURING", "VAN", "MINIVAN"}
# HATCH/SEDAN ajudam, mas a FIPE frequentemente usa apenas 4P/5P ou omite a carroceria.
SOFT_BODY_TOKENS = {"HATCH", "HATCHBACK", "SEDAN", "SEDA", "SED", "SPORTBACK"}
# Em algumas marcas, estes termos são parte da família comercial, não mero acabamento.
# Evita confundir, por exemplo, BYD Dolphin Mini com Dolphin, Song Plus com Song Pro.
FAMILY_DESCRIPTOR_TOKENS = {"MINI", "PLUS", "PRO"}

TOKEN_ALIAS_MAP: dict[str, set[str]] = {
    "INT": {"INTENSE"},
    "INTP": {"INTENSE", "PLUS"},
    "MT": {"MANUAL", "MEC"},
    "MEC": {"MANUAL"},
    "AT": {"AUTO", "AUTOMATICO"},
    "AUT": {"AUTO", "AUTOMATICO"},
    "DYN": {"DYNAMIC"},
    "RDYN": {"R", "DYNAMIC"},
    "XDY": {"X", "DYNAMIC"},
    "HSEXD": {"HSE", "X", "DYNAMIC"},
    "P250F": {"P250", "FLEX"},
    "P250FF": {"P250", "FLEX"},
    "P240FF": {"P240", "FLEX"},
    "DIE": {"DIESEL"},
    "IDM": {"PHEV", "PLUGIN"},
    "DMI": {"PHEV", "PLUGIN"},
    "TOWNER": {"START"},
    "START": {"TOWNER"},
}

AUTOMOTIVE_PHRASE_ALIASES: tuple[tuple[str, str], ...] = (
    (r"\bPICK\s+UP\b", "PICKUP"),
    (r"\bDISCOVERY\s+SP\b", "DISCOVERY SPORT"),
    (r"\bX\s+DYN(?:AMIC)?\b", "X DYNAMIC"),
    (r"\bR\s+DYN(?:AMIC)?\b", "R DYNAMIC"),
    (r"\bE\s+(2008|208)\b", r"E\1"),
    (r"\bI\s+DM\b", "IDM"),
    (r"\bDM\s+I\b", "DMI"),
)

STRONG_TOKEN_TECH_SUFFIXES = ("PHEV", "HEV", "IDM", "DMI", "DM", "FLEX", "FF", "EV")
VERSION_STOP_TOKENS = FUEL_TOKENS | TRANS_TOKENS | ENGINE_TOKENS | GENERIC_TOKENS | SOFT_BODY_TOKENS | {
    "4P", "5P", "2P", "3P", "1P", "6P", "7L", "L", "V", "VALVE", "VALVES",
}
TRIM_TOKENS_IMPORTANTES = {
    "XR", "XS", "XL", "XLS", "XRE", "XRX", "XRV", "GR", "GRS", "GL", "GS", "SE", "SEL", "SL",
    "LT", "LTZ", "LS", "RS", "SS", "MID", "HC", "Z71", "EX", "EXL", "EXL", "LX", "ELX", "HLX",
    "LIMITED", "LONGITUDE", "TRAILHAWK", "SPORT", "SERIE", "SERIES", "S", "PREMIUM", "PRESTIGE",
    "PLATINUM", "ELITE", "ADVANCE", "ADVANCED", "AUDACE", "IMPETUS", "IMPETUS", "ICONIC",
    "PLUS", "MINI", "PRO", "MAX", "ULTRA", "COMFORT", "COMFORTLINE", "HIGHLINE", "TRENDLINE",
    "EXCLUSIVE", "INTENSE", "ZEN", "TROPHY", "FEEL", "SHINE", "LIVE", "TITANIUM", "TREMOR", "RANCH", "WILDTRAK",
    "HSE", "HSEL", "DYNAMIC", "STERRATO", "SVJ", "ROADSTER", "TECNICA", "EVO", "CREW",
    "ED", "EDITION", "FIRST", "MOMENT", "MOMENTUM", "INSCRIPT", "INSCRIPTION", "RDESIGN",
    "EL", "DX", "LXL", "FIRE", "BASE", "PULSE", "CLASS", "CULT", "DUALOGIC",
    "DESIGN", "KINETIC", "SUMMUM", "TOP", "DRIVE",
    "XDRIVE", "SDRIVE", "QUATTRO", "AWD", "FWD", "RWD", "4X4", "4X2",
}

PBEV_PORTAL_URL = (
    "https://www.gov.br/inmetro/pt-br/assuntos/regulamentacao/avaliacao-da-conformidade/"
    "programa-brasileiro-de-etiquetagem/tabelas-de-eficiencia-energetica/"
    "veiculos-automotivos-pbe-veicular"
)

PBEV_FONTES_OFICIAIS = {
    2012: {"rotulo": "Veículos leves 2012", "arquivo": "veiculos_leves_2012.pdf", "url": f"{PBEV_PORTAL_URL}/veiculos-leves-2012/%40%40download/file"},
    2013: {"rotulo": "Veículos leves 2013", "arquivo": "veiculos_leves_2013.pdf", "url": f"{PBEV_PORTAL_URL}/veiculos-leves-2013/%40%40download/file"},
    2014: {"rotulo": "Veículos leves 2014", "arquivo": "veiculos_leves_2014.pdf", "url": f"{PBEV_PORTAL_URL}/veiculos-leves-2014/%40%40download/file"},
    2015: {"rotulo": "Veículos leves 2015", "arquivo": "veiculos_leves_2015.pdf", "url": f"{PBEV_PORTAL_URL}/veiculos-leves-2015/%40%40download/file"},
    2016: {"rotulo": "Veículos leves 2016", "arquivo": "veiculos_leves_2016.pdf", "url": f"{PBEV_PORTAL_URL}/veiculos-leves-2016/%40%40download/file"},
    2017: {"rotulo": "Veículos leves 2017", "arquivo": "veiculos_leves_2017.pdf", "url": f"{PBEV_PORTAL_URL}/veiculos-leves-2017/%40%40download/file"},
    2018: {"rotulo": "Veículos leves 2018", "arquivo": "veiculos_leves_2018.pdf", "url": f"{PBEV_PORTAL_URL}/veiculos-leves-2018/%40%40download/file"},
    2019: {"rotulo": "Veículos leves 2019", "arquivo": "veiculos_leves_2019.pdf", "url": f"{PBEV_PORTAL_URL}/veiculos-leves-2019/%40%40download/file"},
    2020: {"rotulo": "Veículos leves 2020", "arquivo": "veiculos_leves_2020.pdf", "url": f"{PBEV_PORTAL_URL}/veiculos-leves-2020/%40%40download/file"},
    2021: {"rotulo": "Veículos leves 2021", "arquivo": "pbe-veicular-2021.pdf", "url": f"{PBEV_PORTAL_URL}/veiculos-leves-2021/%40%40download/file"},
    2022: {"rotulo": "Veículos leves 2022", "arquivo": "pbe-veicular-2022.pdf", "url": f"{PBEV_PORTAL_URL}/pbe-veicular-2022.pdf/%40%40download/file"},
    2023: {"rotulo": "Veículos leves 2023", "arquivo": "PBEV 11.2023.pdf", "url": f"{PBEV_PORTAL_URL}/pbe-veicular-2023.pdf/%40%40download/file"},
    2024: {"rotulo": "Veículos leves 2024 - 16º Ciclo", "arquivo": "Mascara PBEV 2024-4-OUT (7).pdf", "url": f"{PBEV_PORTAL_URL}/pbe-veicular-2024-1.pdf/%40%40download/file"},
    2025: {"rotulo": "Veículos leves 2025 - 17º Ciclo", "arquivo": "MÁSCARA-PBEV-2025-24-NOV-2025.pdf", "url": f"{PBEV_PORTAL_URL}/mascara-pbev-2025-mar-11.pdf/%40%40download/file"},
    2026: {"rotulo": "Veículos leves 2026 - 18º Ciclo", "arquivo": "Tabela PBEV 2026_3_JUN-1.pdf", "url": f"{PBEV_PORTAL_URL}/mascara-pbev-2026_19_jan-rev01.pdf/%40%40download/file"},
}


@dataclass(frozen=True)
class _BasePbevCache:
    path: str
    mtime: float
    registros: list[dict[str, Any]]
    indice_marca: dict[str, list[dict[str, Any]]]
    manifest: dict[str, Any]


class PbevService:
    """Serviço conservador para sugerir consumo/eficiência PBEV na aba Simular.

    A base saneada é carregada em JSON e indexada em memória. O serviço nunca abre XLSX
    em tempo de consulta e nunca altera motor de TCO/depreciação.
    """

    _lock = threading.RLock()
    _cache: _BasePbevCache | None = None

    def __init__(self, base_path: str | Path | None = None, manifest_path: str | Path | None = None):
        self.base_path = Path(base_path) if base_path else None
        self.manifest_path = Path(manifest_path) if manifest_path else None

    # ------------------------------------------------------------------
    # Normalização pública/reutilizável
    # ------------------------------------------------------------------
    @staticmethod
    def normalizar_texto(valor: Any) -> str:
        texto = str(valor or "").strip().upper()
        if not texto:
            return ""
        texto = unicodedata.normalize("NFD", texto)
        texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
        texto = texto.replace("Á", "A")
        texto = re.sub(r"(?<=\d)[,.](?=\d)", " ", texto)
        texto = re.sub(r"[^A-Z0-9]+", " ", texto)
        return re.sub(r"\s+", " ", texto).strip()

    @classmethod
    def normalizar_aliases_automotivos(cls, valor: Any) -> str:
        """Normaliza grafias FIPE/PBEV sem depender de marca ou modelo específico."""
        texto = cls.normalizar_texto(valor)
        if not texto:
            return ""
        for padrao, substituicao in AUTOMOTIVE_PHRASE_ALIASES:
            texto = re.sub(padrao, substituicao, texto)
        # Abreviações coladas de acabamento/propulsão são expandidas como termos.
        saida: list[str] = []
        for token in texto.split():
            aliases = TOKEN_ALIAS_MAP.get(token)
            if aliases:
                saida.append(token)
                saida.extend(sorted(aliases))
            else:
                saida.append(token)
        return re.sub(r"\s+", " ", " ".join(saida)).strip()

    @classmethod
    def _tokens(cls, valor: Any, *, remover_genericos: bool = True) -> set[str]:
        bruto = cls.normalizar_aliases_automotivos(valor)
        if not bruto:
            return set()
        tokens = {t for t in bruto.split() if t}

        # Expansões conservadoras para nomenclaturas FIPE x PBEV.
        # Não substituem o token original; apenas adicionam aliases úteis para o score.
        extras: set[str] = set()
        for token in list(tokens):
            # Peugeot e-2008/e2008/e 2008, e-208/e208/e 208 etc.
            # O número do modelo passa a ser descritor forte e evita confundir 2008 com 208.
            m = re.fullmatch(r"([A-Z]+)(\d{2,5})([A-Z]*)", token)
            if m:
                prefixo, numero, sufixo = m.groups()
                if numero:
                    extras.add(numero)
                if prefixo and numero:
                    extras.add(f"{prefixo}{numero}")
                if sufixo:
                    extras.add(sufixo)

            # Alias comerciais/técnicos recorrentes na PBEV.
            extras |= TOKEN_ALIAS_MAP.get(token, set())

            # Ferrari: a FIPE pode vir com erro de grafia; PBEV usa 12CILINDRI.
            if "CILINRDRI" in token:
                extras.add(token.replace("CILINRDRI", "CILINDRI"))

            # PBEV abrevia Spider como SPI em alguns registros.
            if token == "SPI":
                extras.add("SPIDER")
            elif token == "SPIDER":
                extras.add("SPI")

        tokens |= extras
        if remover_genericos:
            tokens = {t for t in tokens if t not in GENERIC_TOKENS}
        return tokens

    @classmethod
    def _marca_key(cls, marca: Any) -> str:
        texto = cls.normalizar_texto(marca)
        if not texto:
            return ""
        if "CHEVROLET" in texto or texto in {"GM", "G M", "GM CHEVROLET"}:
            return "CHEVROLET"
        if "VOLKSWAGEN" in texto or texto in {"VW", "VOLKS", "VOLKS WAGEN"}:
            return "VOLKSWAGEN"
        if "MERCEDES" in texto or "BENZ" in texto or texto in {"M BENZ", "MB"}:
            return "MERCEDES BENZ"
        if "CHERY" in texto:
            return "CHERY"
        if "LAND ROVER" in texto or texto == "LR":
            return "LAND ROVER"
        if "GREAT WALL" in texto or texto == "GWM":
            return "GWM"
        if "JAC" in texto:
            return "JAC"
        if "RAM" == texto or texto.startswith("RAM "):
            return "RAM"
        if "MINI" == texto or texto.startswith("MINI "):
            return "MINI"
        if "CAOA" in texto and "HYUNDAI" in texto:
            return "HYUNDAI"
        return texto

    @classmethod
    def _marca_keys_busca(cls, consulta: dict[str, Any]) -> list[str]:
        """Resolve marca e submarca sem aceitar família errada.

        A FIPE historicamente pode listar RAM como Dodge. A ampliação serve apenas
        para buscar no índice correto; modelo, combustível e motor continuam sendo
        filtros obrigatórios no score.
        """
        principal = cls._marca_key(consulta.get("marca"))
        texto = cls.normalizar_aliases_automotivos(cls._texto_consulta(consulta))
        keys: list[str] = [principal] if principal else []
        if principal == "DODGE" and re.search(r"\bRAM\b", texto):
            keys.append("RAM")
        elif principal == "RAM":
            keys.append("DODGE")
        return list(dict.fromkeys(k for k in keys if k))

    # ------------------------------------------------------------------
    # Carregamento/cache
    # ------------------------------------------------------------------
    def _config_path(self, chave: str, fallback: str) -> Path:
        if chave == "ARQUIVO_PBEV_BASE" and self.base_path:
            return self.base_path
        if chave == "ARQUIVO_PBEV_MANIFEST" and self.manifest_path:
            return self.manifest_path
        try:
            if current_app is not None:
                valor = current_app.config.get(chave)
                if valor:
                    return Path(valor)
                data_dir = Path(current_app.config.get("DATA_DIR") or Path(__file__).resolve().parents[1] / "data")
            else:
                data_dir = Path(__file__).resolve().parents[1] / "data"
        except RuntimeError:
            data_dir = Path(__file__).resolve().parents[1] / "data"
        return data_dir / "pbev" / fallback

    def _base_json_path(self) -> Path:
        return self._config_path("ARQUIVO_PBEV_BASE", "pbev_base_saneada_v1.json")

    def _manifest_json_path(self) -> Path:
        return self._config_path("ARQUIVO_PBEV_MANIFEST", "pbev_manifest_validacao_v1.json")

    def carregar_base_pbev(self) -> _BasePbevCache:
        path = self._base_json_path()
        if not path.exists():
            raise FileNotFoundError(f"Base PBEV não encontrada em {path}")
        mtime = path.stat().st_mtime
        with self._lock:
            if self._cache and self._cache.path == str(path) and self._cache.mtime == mtime:
                return self._cache

            with path.open("r", encoding="utf-8") as f:
                registros = json.load(f)
            if not isinstance(registros, list):
                raise ValueError("Base PBEV saneada deve ser uma lista JSON de registros.")

            indice: dict[str, list[dict[str, Any]]] = {}
            for reg in registros:
                if not isinstance(reg, dict):
                    continue
                marca_key = self._marca_key(reg.get("marca_normalizada") or reg.get("marca"))
                indice.setdefault(marca_key, []).append(reg)

            manifest: dict[str, Any] = {}
            manifest_path = self._manifest_json_path()
            if manifest_path.exists():
                try:
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                except Exception:
                    manifest = {}

            self._cache = _BasePbevCache(
                path=str(path),
                mtime=mtime,
                registros=registros,
                indice_marca=indice,
                manifest=manifest,
            )
            return self._cache

    # ------------------------------------------------------------------
    # Flags/bloqueios
    # ------------------------------------------------------------------
    @staticmethod
    def _bool_flag(valor: Any) -> bool:
        if isinstance(valor, bool):
            return valor
        if valor is None:
            return False
        return str(valor).strip().lower() in {"1", "true", "sim", "s", "yes", "y"}

    def validar_flags_autofill(self, registro: dict[str, Any]) -> tuple[bool, list[str]]:
        motivos: list[str] = []
        status = str(registro.get("status_registro") or "").strip().upper()
        if status == "BLOQUEAR_AUTOFILL":
            motivos.append("status_registro=BLOQUEAR_AUTOFILL")
        for flag in BLOQUEIO_AUTOFILL_FLAGS:
            if self._bool_flag(registro.get(flag)):
                motivos.append(f"{flag}=true")
        return (len(motivos) == 0, motivos)

    # ------------------------------------------------------------------
    # Parsing técnico
    # ------------------------------------------------------------------
    @staticmethod
    def _num(registro: dict[str, Any], campo: str) -> float | None:
        valor = registro.get(campo)
        if valor is None or valor == "":
            return None
        try:
            n = float(str(valor).replace(".", ".").replace(",", "."))
            return n if n > 0 else None
        except Exception:
            return None

    @staticmethod
    def _parse_ano(valor: Any) -> int | None:
        texto = str(valor or "")
        # A FIPE usa 32000-x para zero km; esse código não é ano real.
        match = re.search(r"(20\d{2}|19\d{2})", texto)
        if not match:
            return None
        ano = int(match.group(1))
        return ano if 2010 <= ano <= 2035 else None

    @classmethod
    def _consulta_zero_km_contexto(cls, consulta: dict[str, Any]) -> bool:
        """Detecta o código especial FIPE de zero km em qualquer tela.

        A Simular costuma enviar o ano-modelo já resolvido, mas a Consulta Fipe+
        pode receber ``32000-x`` diretamente da FIPE pública. A decisão precisa
        ficar centralizada aqui para que todas as telas usem o mesmo matching.
        """
        if consulta.get("zero_km") is True or str(consulta.get("zero_km") or "").strip().lower() in {"1", "true", "sim", "s"}:
            return True
        bruto = " ".join(str(consulta.get(k) or "") for k in (
            "ano", "ano_modelo", "ano_codigo", "codigo_ano", "texto_ano"
        ))
        return "32000" in bruto or "ZERO" in cls.normalizar_texto(bruto)

    @classmethod
    def resolver_ano_fipe_para_matching(cls, consulta: dict[str, Any]) -> dict[str, Any]:
        """Resolve ano real e contexto zero km de forma centralizada.

        O código 32000 nunca é tratado como ano. Quando não há ano-modelo real,
        a ordenação dos candidatos deve priorizar o maior ano de tabela PBEV.
        """
        zero_km = cls._consulta_zero_km_contexto(consulta)
        campos = ("ano_modelo", "ano", "texto_ano", "ano_codigo", "codigo_ano")
        anos: list[int] = []
        for campo in campos:
            valor = consulta.get(campo)
            bruto = str(valor or "")
            if "32000" in bruto:
                continue
            ano = cls._parse_ano(valor)
            if ano:
                anos.append(ano)
        ano_modelo = anos[0] if anos else None
        return {
            "ano_modelo": ano_modelo,
            "ano_referencia": ano_modelo,
            "zero_km_contexto": zero_km,
            "prioridade_ano_tabela": "mais_recente" if zero_km and not ano_modelo else "proximidade_ano_modelo",
        }

    @staticmethod
    def _ano_tabela_registro(registro: dict[str, Any]) -> int:
        try:
            return int(registro.get("ano_tabela") or registro.get("ano_tabela_pbev") or 0)
        except Exception:
            return 0

    @staticmethod
    def _ratio(a: str, b: str) -> float:
        if not a or not b:
            return 0.0
        return SequenceMatcher(None, a, b).ratio()

    @staticmethod
    def _displacement_signature(*partes: Any) -> str:
        texto = " ".join(str(p or "") for p in partes)
        texto = texto.replace(",", ".")
        matches = re.findall(r"(?<!\d)([1-6](?:\.\d))(?!\d)", texto)
        if matches:
            return matches[0]
        norm = PbevService.normalizar_texto(texto)
        # FIPE/PBEV normalizados às vezes separam 1.5 como "1 5".
        pares = re.findall(r"\b([1-6])\s+([0-9])\b", norm)
        if pares:
            return f"{pares[0][0]}.{pares[0][1]}"
        return ""

    @staticmethod
    def _valvulas_signature(*partes: Any) -> str:
        texto = PbevService.normalizar_texto(" ".join(str(p or "") for p in partes))
        match = re.search(r"\b(8|10|12|16|20|24|32|40|48|60)\s*V\b", texto)
        if match:
            return f"{match.group(1)}V"
        match = re.search(r"\b(8V|10V|12V|16V|20V|24V|32V|40V|48V|60V)\b", texto)
        return match.group(1) if match else ""

    @staticmethod
    def _transmissao_signature(*partes: Any) -> str:
        texto = PbevService.normalizar_texto(" ".join(str(p or "") for p in partes))
        if not texto:
            return ""
        if "CVT" in texto:
            return "CVT"
        if re.search(r"\b(MTA|DCT|DHT)\b", texto):
            return "AUTO"
        if re.search(r"\b(A|AT|AUT|AUTO|AUTOMATICO|AUTOMATICA)\b", texto) or re.search(r"\bA\s*[0-9]\b", texto) or re.search(r"\b[0-9]+\s*AT\b", texto):
            return "AUTO"
        if re.search(r"\b(M|MT|MEC|MANUAL|MECANICO|MECANICA)\b", texto) or re.search(r"\bM\s*[0-9]\b", texto) or re.search(r"\b[0-9]+\s*MT\b", texto):
            return "MANUAL"
        return ""

    @classmethod
    def _texto_consulta(cls, consulta: dict[str, Any]) -> str:
        return " ".join(
            str(consulta.get(k) or "")
            for k in ("marca", "modelo", "texto_modelo", "combustivel", "texto_ano", "tipo_veiculo")
        )

    @classmethod
    def resolver_propulsao_real(cls, consulta: dict[str, Any], registro: dict[str, Any] | None = None) -> str:
        """Resolve a propulsão/combustível real, refinando o rótulo genérico FIPE."""
        tipo = cls.normalizar_aliases_automotivos(consulta.get("tipo_veiculo"))
        texto = cls.normalizar_aliases_automotivos(cls._texto_consulta(consulta))
        tokens = set(texto.split())
        fortes = cls.extrair_tokens_fortes_modelo(texto)
        if tipo == "ELETRICO" or re.search(r"\b(ELETRICO|ELETRICA|BEV|EV|ELECTRIC)\b", texto):
            return "ELETRICO"
        if re.search(r"\b(PHEV|PLUGIN|IDM|DMI)\b", texto) or "DM" in tokens or tipo == "PHEV":
            return "PLUG_IN"
        # D300/D350 e códigos Dxxx, combinados com híbrido/diesel, representam diesel.
        if "DIESEL" in tokens or any(re.fullmatch(r"D\d{3}", token) for token in fortes):
            return "DIESEL"
        if tipo == "HIBRIDO" or re.search(r"\b(HIBRIDO|HIBRIDA|HYBRID|HEV|MHEV)\b", texto):
            # A PBEV pode refinar o híbrido genérico da FIPE. O rótulo FLEX
            # não deve apagar a natureza híbrida; o combustível real continua
            # disponível no registro e gera sugestão ``hibrido_flex``.
            if registro:
                prop = cls.normalizar_texto(registro.get("tipo_propulsao_normalizado") or registro.get("tipo_propulsao")).replace(" ", "_")
                comb = cls.normalizar_texto(registro.get("combustivel_normalizado") or registro.get("combustivel")).replace(" ", "_")
                if prop in {"PLUG_IN", "PLUGIN", "PHEV", "HIBRIDO_PLUG_IN"}:
                    return "PLUG_IN"
                if comb == "DIESEL":
                    return "DIESEL"
            return "HIBRIDO"
        if "FLEX" in tokens or re.search(r"\b(TOTAL FLEX|BICOMBUSTIVEL|BI COMBUSTIVEL)\b", texto):
            return "FLEX"
        if "ETANOL" in tokens or "ALCOOL" in tokens:
            return "ETANOL"
        if "GASOLINA" in tokens:
            return "GASOLINA"
        return ""

    @classmethod
    def _detectar_combustivel_consulta(cls, consulta: dict[str, Any]) -> str:
        return cls.resolver_propulsao_real(consulta)

    @staticmethod
    def _combustivel_compativel(req: str, cand_comb: str, cand_prop: str) -> tuple[bool, int, str]:
        req = (req or "").upper().replace(" ", "_")
        cand_comb = (cand_comb or "").upper().replace(" ", "_")
        cand_prop = (cand_prop or "").upper().replace(" ", "_")

        # Normalizações defensivas: a base PBEV pode representar plug-in/PHEV de
        # formas diferentes. A decisão fica centralizada aqui para Simular e Fipe+.
        cand_is_eletrico = cand_prop in {"ELETRICO", "ELÉTRICO", "BEV", "EV"}
        cand_is_plugin = cand_prop in {
            "PLUG_IN", "PLUGIN", "PHEV", "HIBRIDO_PLUG_IN", "HIBRIDO_PLUGIN",
            "HYBRID_PLUG_IN", "HYBRID_PLUGIN", "RECARREGAVEL", "RECARREGÁVEL",
        }
        cand_is_hibrido_convencional = cand_prop in {"HIBRIDO", "HÍBRIDO", "HYBRID", "HEV", "MHEV"}

        if req == "ELETRICO":
            return (cand_is_eletrico, 24 if cand_is_eletrico else -80, "propulsão elétrica compatível" if cand_is_eletrico else "propulsão não elétrica")
        if req == "PLUG_IN":
            return (cand_is_plugin, 24 if cand_is_plugin else -75, "PHEV/plugin compatível" if cand_is_plugin else "propulsão não plugin")
        if req == "HIBRIDO":
            if cand_is_hibrido_convencional:
                return True, 22, "híbrido convencional compatível"
            if cand_is_plugin:
                # A FIPE frequentemente classifica PHEV/DM/DM-i apenas como
                # "Híbrido". Quando o restante da identidade técnica bater, a PBEV
                # pode refinar o tipo real para híbrido plug-in sem virar incompatível.
                return True, 22, "híbrido FIPE compatível com PHEV/plugin PBEV"
            return False, -45, "propulsão não híbrida"
        if req in {"FLEX", "DIESEL", "GASOLINA", "ETANOL"}:
            if cand_is_eletrico or cand_is_plugin or cand_is_hibrido_convencional:
                return False, -55, f"propulsão PBEV incompatível com veículo FIPE {req.lower()} não híbrido"
            if cand_comb == req:
                return True, 22, f"combustível {req.lower()} compatível"
            return False, -55, f"combustível diverge: FIPE {req.lower()} x PBEV {cand_comb.lower() or 'vazio'}"
        # Sem combustível explícito: aceita, mas não permite sozinho um match alto.
        return True, 4, "combustível FIPE não explícito"

    @staticmethod
    def _token_secundario_identidade(token: str) -> bool:
        token = str(token or "").upper().strip()
        return bool(
            not token
            or POWER_TOKEN_RE.fullmatch(token)
            or PORT_TOKEN_RE.fullmatch(token)
            or YEAR_TOKEN_RE.fullmatch(token)
        )

    @classmethod
    def _tokens_compostos_modelo(cls, texto: Any) -> set[str]:
        """Monta identificadores comerciais separados na FIPE/PBEV.

        Exemplos: XC 40 -> XC40, SF 90 -> SF90, E 2008 -> E2008,
        RAM 2500 -> RAM2500. A função não decide sozinha se o código é
        família ou versão; essa classificação ocorre no score contextual.
        """
        norm = cls.normalizar_aliases_automotivos(texto)
        tokens = norm.split()
        compostos: set[str] = set()
        ignorar_prefixo = (
            FUEL_TOKENS | TRANS_TOKENS | ENGINE_TOKENS | GENERIC_TOKENS
            | TRIM_TOKENS_IMPORTANTES | HARD_BODY_TOKENS | SOFT_BODY_TOKENS
            | {"BAU", "FURGAO", "CABRIO", "CABRIOLET"}
        )
        for idx, (primeiro, segundo) in enumerate(zip(tokens, tokens[1:])):
            if primeiro in ignorar_prefixo or cls._token_secundario_identidade(segundo):
                continue
            if re.fullmatch(r"[A-Z]{1,3}", primeiro) and re.fullmatch(r"\d{1,5}[A-Z]{0,3}", segundo):
                if YEAR_TOKEN_RE.fullmatch(segundo):
                    continue
                numero = re.match(r"\d+", segundo)
                if numero and len(numero.group(0)) == 1:
                    if primeiro not in SINGLE_DIGIT_MODEL_PREFIXES:
                        continue
                    # Evita criar modelo falso a partir de acabamento + cilindrada
                    # normalizada, como ``Etios X 1 3`` -> X1. Em designações
                    # reais como BMW X 1, o próximo token não é outro algarismo.
                    proximo = tokens[idx + 2] if idx + 2 < len(tokens) else ""
                    if re.fullmatch(r"\d", proximo):
                        continue
                compostos.add(f"{primeiro}{segundo}")
        return compostos

    @classmethod
    def _palavras_familia_modelo(cls, texto: Any) -> set[str]:
        """Extrai nomes textuais de família, separados de acabamento/técnica."""
        tokens = cls.normalizar_aliases_automotivos(texto).split()
        excluir = (
            FUEL_TOKENS | TRANS_TOKENS | ENGINE_TOKENS | GENERIC_TOKENS
            | TRIM_TOKENS_IMPORTANTES | HARD_BODY_TOKENS | SOFT_BODY_TOKENS
            | {"BAU", "FURGAO", "SPIDER", "CONVERSIVEL", "CABRIO", "CABRIOLET", "DCT", "DHT"}
        )
        palavras: set[str] = set()
        for token in tokens:
            if token in excluir or cls._token_secundario_identidade(token):
                continue
            if re.fullmatch(r"\d+(?:\.\d+)?", token) or re.fullmatch(r"V\d{1,2}", token):
                continue
            if cls._token_forte_tecnico(token):
                continue
            if len(token) <= 2:
                continue
            if re.fullmatch(r"[A-Z]{1,8}\d{1,5}[A-Z]{0,4}", token):
                continue
            palavras.add(token)
        return palavras

    @classmethod
    def _tokens_designacao_modelo(cls, texto: Any) -> set[str]:
        """Assinatura comercial da designação, sem motor/potência/ano."""
        norm = cls.normalizar_aliases_automotivos(texto)
        tokens = norm.split()
        saida = set(cls.extrair_tokens_fortes_modelo(norm))
        saida |= cls._palavras_familia_modelo(norm)
        saida |= {t for t in cls._tokens(norm) if t in TRIM_TOKENS_IMPORTANTES}
        saida |= cls.classificar_carroceria(norm)
        for token in tokens:
            if PORT_TOKEN_RE.fullmatch(token):
                saida.add(token)
        for primeiro, segundo in zip(tokens, tokens[1:]):
            if re.fullmatch(r"[1-9]", primeiro) and segundo in {"PORTA", "PORTAS"}:
                saida.add(f"{primeiro}P")
        return {t for t in saida if not cls._token_secundario_identidade(t)}

    @classmethod
    def extrair_tokens_fortes_modelo(cls, texto: Any) -> set[str]:
        """Extrai identificadores comerciais fortes, sem potência/portas/ano."""
        norm = cls.normalizar_aliases_automotivos(texto)
        tokens = norm.split()
        fortes: set[str] = set(cls._tokens_compostos_modelo(norm))
        ignorar = FUEL_TOKENS | TRANS_TOKENS | ENGINE_TOKENS | GENERIC_TOKENS | {
            "4X4", "4X2", "AWD", "FWD", "RWD", "2WD",
        }
        for token in tokens:
            if token in ignorar or cls._token_secundario_identidade(token) or re.fullmatch(r"V\d{1,2}", token):
                continue
            canon = token
            for sufixo in STRONG_TOKEN_TECH_SUFFIXES:
                if canon.endswith(sufixo) and len(canon) > len(sufixo) + 1:
                    base = canon[:-len(sufixo)]
                    if re.fullmatch(r"[A-Z]{1,8}\d{1,5}[A-Z]{0,3}", base):
                        canon = base
                        break
            if cls._token_secundario_identidade(canon):
                continue
            if re.fullmatch(r"[A-Z]{1,8}\d{1,5}[A-Z]{0,4}", canon) or re.fullmatch(r"\d{1,5}[A-Z]{1,4}", canon):
                fortes.add(canon)
            elif re.fullmatch(r"\d{3,4}", canon):
                n = int(canon)
                if not 2010 <= n <= 2035:
                    fortes.add(canon)
        return fortes

    @classmethod
    def classificar_carroceria(cls, texto: Any) -> set[str]:
        tokens = set(cls.normalizar_aliases_automotivos(texto).split())
        categorias: set[str] = set()
        if tokens & {"PICKUP", "PICAPE", "BAU"}:
            categorias.add("PICKUP")
        if tokens & {"VAN", "MINIVAN", "FURGAO"}:
            categorias.add("VAN")
        if tokens & {"SEDAN", "SEDA", "SED"}:
            categorias.add("SEDAN")
        if tokens & {"HATCH", "HATCHBACK"}:
            categorias.add("HATCH")
        if tokens & {"SW", "WAGON", "TOURING"}:
            categorias.add("WAGON")
        if tokens & {"SPIDER", "ROADSTER", "CABRIO", "CABRIOLET", "CONVERSIVEL"}:
            categorias.add("CONVERSIVEL")
        if "CROSS" in tokens:
            categorias.add("CROSS")
        return categorias

    @staticmethod
    def _token_forte_tecnico(token: str) -> bool:
        # Códigos P250/D300/D350 descrevem motorização, não a família do veículo.
        return bool(re.fullmatch(r"[PD]\d{3}", str(token or "")))

    @classmethod
    def calcular_score_modelo(cls, texto_fipe: Any, texto_pbev: Any) -> dict[str, Any]:
        """Score de identidade comercial separado de acabamento e técnica."""
        fortes_fipe = cls.extrair_tokens_fortes_modelo(texto_fipe)
        fortes_pbev = cls.extrair_tokens_fortes_modelo(texto_pbev)
        familia_fipe = {t for t in fortes_fipe if not cls._token_forte_tecnico(t)}
        familia_pbev = {t for t in fortes_pbev if not cls._token_forte_tecnico(t)}
        tecnicos_fipe = fortes_fipe - familia_fipe
        tecnicos_pbev = fortes_pbev - familia_pbev
        palavras_fipe = cls._palavras_familia_modelo(texto_fipe)
        palavras_pbev = cls._palavras_familia_modelo(texto_pbev)
        corpo_fipe = cls.classificar_carroceria(texto_fipe)
        corpo_pbev = cls.classificar_carroceria(texto_pbev)
        ajuste = 0.0
        motivos: list[str] = []
        penalidades: list[str] = []
        forte_compativel = False
        forte_divergente = False
        token_forte_parcial = False
        identidade_nivel = 0

        if familia_fipe:
            inter = familia_fipe & familia_pbev
            cobertura = len(inter) / max(1, len(familia_fipe))
            if cobertura >= 1.0:
                ajuste += 36
                forte_compativel = True
                identidade_nivel = 4
                motivos.append("token forte de modelo compatível: " + ", ".join(sorted(inter)))
            elif inter:
                ajuste += 8
                token_forte_parcial = True
                identidade_nivel = 2
                ausentes = familia_fipe - familia_pbev
                motivos.append("token forte de modelo parcialmente compatível: " + ", ".join(sorted(inter)))
                penalidades.append("token forte da FIPE ausente no PBEV: " + ", ".join(sorted(ausentes)))
            elif familia_pbev:
                ajuste -= 55
                forte_divergente = True
                identidade_nivel = -2
                penalidades.append("token forte de modelo divergente: " + ", ".join(sorted(familia_fipe)) + " x " + ", ".join(sorted(familia_pbev)))
            else:
                ajuste -= 18
                identidade_nivel = -1
                penalidades.append("token forte da FIPE ausente no PBEV: " + ", ".join(sorted(familia_fipe)))
        else:
            inter_palavras = palavras_fipe & palavras_pbev
            if palavras_fipe and inter_palavras:
                cobertura_palavras = len(inter_palavras) / max(1, len(palavras_fipe))
                if cobertura_palavras >= 1.0:
                    ajuste += 28
                    identidade_nivel = 3
                    motivos.append("família comercial textual compatível: " + ", ".join(sorted(inter_palavras)))
                else:
                    ajuste += 12
                    identidade_nivel = 2
                    motivos.append("família comercial textual parcialmente compatível: " + ", ".join(sorted(inter_palavras)))
            elif palavras_fipe and palavras_pbev:
                ajuste -= 35
                identidade_nivel = -2
                penalidades.append("família comercial textual divergente: " + ", ".join(sorted(palavras_fipe)) + " x " + ", ".join(sorted(palavras_pbev)))

        if tecnicos_fipe:
            inter_tecnico = tecnicos_fipe & tecnicos_pbev
            if inter_tecnico:
                ajuste += 10
                motivos.append("código técnico compatível: " + ", ".join(sorted(inter_tecnico)))
            else:
                ajuste -= 3
                penalidades.append("código técnico da FIPE ausente no PBEV: " + ", ".join(sorted(tecnicos_fipe)))

        if corpo_fipe and corpo_pbev:
            if corpo_fipe & corpo_pbev:
                ajuste += 10
                motivos.append("carroceria compatível")
            else:
                ajuste -= 38
                identidade_nivel = min(identidade_nivel, -1)
                penalidades.append("carroceria divergente: " + ", ".join(sorted(corpo_fipe)) + " x " + ", ".join(sorted(corpo_pbev)))
        elif corpo_fipe and not corpo_pbev:
            ajuste -= 7
            penalidades.append("carroceria explícita da FIPE ausente no PBEV: " + ", ".join(sorted(corpo_fipe)))

        designacao_fipe = cls._tokens_designacao_modelo(texto_fipe)
        designacao_pbev = cls._tokens_designacao_modelo(texto_pbev)
        designacao_exata = bool(designacao_fipe and designacao_fipe == designacao_pbev)
        designacao_parcial = False
        if designacao_exata:
            ajuste += 18
            motivos.append("designação comercial exata")
            identidade_nivel = max(identidade_nivel, 4)
        elif designacao_fipe and designacao_pbev:
            inter_designacao = designacao_fipe & designacao_pbev
            cobertura_designacao = len(inter_designacao) / max(1, len(designacao_fipe))
            if cobertura_designacao >= 0.6:
                designacao_parcial = True
                ajuste += 6
                motivos.append("designação comercial parcialmente compatível")

        return {
            "ajuste": ajuste,
            "motivos": motivos,
            "penalidades": penalidades,
            "tokens_fortes_fipe": fortes_fipe,
            "tokens_fortes_pbev": fortes_pbev,
            "tokens_familia_fipe": familia_fipe,
            "tokens_familia_pbev": familia_pbev,
            "tokens_tecnicos_fipe": tecnicos_fipe,
            "tokens_tecnicos_pbev": tecnicos_pbev,
            "palavras_familia_fipe": palavras_fipe,
            "palavras_familia_pbev": palavras_pbev,
            "token_forte_compativel": forte_compativel,
            "token_forte_parcial": token_forte_parcial,
            "token_forte_divergente": forte_divergente,
            "carroceria_fipe": corpo_fipe,
            "carroceria_pbev": corpo_pbev,
            "nivel_identidade_modelo": identidade_nivel,
            "familia_textual_compativel": bool(palavras_fipe & palavras_pbev),
            "familia_textual_divergente": bool(palavras_fipe and palavras_pbev and not (palavras_fipe & palavras_pbev)),
            "designacao_fipe": designacao_fipe,
            "designacao_pbev": designacao_pbev,
            "designacao_exata": designacao_exata,
            "designacao_parcial": designacao_parcial,
        }

    @classmethod
    def _version_tokens(cls, texto: Any, modelo_core_tokens: set[str] | None = None) -> set[str]:
        tokens = cls._tokens(texto)
        modelo_core_tokens = modelo_core_tokens or set()
        saida: set[str] = set()
        for token in tokens:
            if token in modelo_core_tokens or token in VERSION_STOP_TOKENS:
                continue
            if re.fullmatch(r"20\d{2}", token) and token != "2008":
                continue
            if re.fullmatch(r"[0-9]", token):
                continue
            if token in TRIM_TOKENS_IMPORTANTES or len(token) >= 2:
                saida.add(token)
        return saida

    @classmethod
    def _trim_tokens_contextual(cls, texto: Any) -> set[str]:
        return {token for token in cls._tokens(texto) if token in TRIM_TOKENS_IMPORTANTES}

    @classmethod
    def _family_descriptor_tokens_contextual(cls, tokens_all: set[str], trim_tokens: set[str]) -> set[str]:
        descriptors = set(tokens_all or set()) & FAMILY_DESCRIPTOR_TOKENS
        if not descriptors:
            return set()
        outros_trims = set(trim_tokens or set()) - descriptors
        saida = set(descriptors)
        for token in list(saida):
            # Quando PLUS/PRO/MINI aparece ao lado de outro acabamento forte
            # (ex.: Intense Plus), ele deve atuar como versão, não como família.
            if token in trim_tokens and outros_trims:
                saida.discard(token)
        return saida

    @classmethod
    def _modelo_core_tokens(cls, texto_modelo: Any) -> set[str]:
        """Tokens de família/modelo para matching.

        Remove combustível, transmissão e ruídos que às vezes aparecem no campo
        ``modelo`` da PBEV. Isso evita penalizar casos como:
        FIPE ``Hilux CD SRV 4x4 2.8 TDI Diesel Aut.`` x PBEV
        ``HILUX DIESEL 4X4 AT SRV AT``.
        """
        tokens = cls._tokens(texto_modelo)
        core: set[str] = set()
        for token in tokens:
            if cls._token_secundario_identidade(token):
                continue
            if token in SOFT_BODY_TOKENS or token in FUEL_TOKENS or token in TRANS_TOKENS or token in ENGINE_TOKENS or token in GENERIC_TOKENS:
                continue
            if re.fullmatch(r"20\d{2}", token) and token != "2008":
                continue
            if re.fullmatch(r"[0-9]", token):
                continue
            core.add(token)
        return core or tokens

    @classmethod
    def _identificadores_comerciais_modelo(cls, texto_modelo: Any) -> set[str]:
        """Identificadores comerciais, excluindo potência, portas e ano."""
        return cls.extrair_tokens_fortes_modelo(texto_modelo)

    @staticmethod
    def _identificadores_comerciais_divergentes(requisitados: set[str], candidatos: set[str]) -> bool:
        """Detecta derivação comercial colada que muda a identidade do modelo.

        Só há divergência quando não existe identificador exato e um identificador é
        prefixo direto do outro com sufixo curto. Isso evita que igualdade numérica
        mascare famílias diferentes sem transformar acabamentos soltos em bloqueio.
        """
        if not requisitados or not candidatos or requisitados & candidatos:
            return False
        for req in requisitados:
            for cand in candidatos:
                menor, maior = (req, cand) if len(req) <= len(cand) else (cand, req)
                sufixo = maior[len(menor):] if maior.startswith(menor) else ""
                if sufixo and len(sufixo) <= 3 and sufixo.isalpha():
                    return True
        return False

    @classmethod
    def avaliar_identidade_tecnica(
        cls, *, fuel_ok: bool, ok_flags: bool, modelo_score: float,
        penalidades: list[str], motor_fipe: str, motor_pbev: str,
        transmissao_fipe: str, transmissao_pbev: str,
        token_forte_compativel: bool = False,
    ) -> dict[str, Any]:
        leves_consumo = {"ACABAMENTO DIVERGENTE"}
        ignorar_ano = {"ANO FIPE AUSENTE PARA SCORE"}
        penalidades_tecnicas: list[str] = []
        for p in penalidades:
            norm = cls.normalizar_texto(p)
            if norm.startswith("ANO DISTANTE") or norm in ignorar_ano:
                continue
            if norm.startswith("CODIGO TECNICO DA FIPE AUSENTE NO PBEV"):
                continue
            penalidades_tecnicas.append(p)
        bloqueantes = [p for p in penalidades_tecnicas if cls.normalizar_texto(p) not in leves_consumo]
        motor_ok = not motor_fipe or not motor_pbev or motor_fipe == motor_pbev
        trans_ok = not transmissao_fipe or not transmissao_pbev or transmissao_fipe == transmissao_pbev or {transmissao_fipe, transmissao_pbev} <= {"AUTO", "CVT"}
        modelo_ok = modelo_score >= 30 or (token_forte_compativel and modelo_score >= 24)
        identidade_forte = fuel_ok and ok_flags and modelo_ok and not penalidades_tecnicas and motor_ok and trans_ok
        suficiente = fuel_ok and ok_flags and modelo_ok and not bloqueantes and motor_ok and trans_ok
        return {
            "penalidades_tecnicas": penalidades_tecnicas,
            "penalidades_bloqueantes_consumo": bloqueantes,
            "identidade_tecnica_forte": identidade_forte,
            "tecnica_suficiente_para_consumo": suficiente,
        }

    # ------------------------------------------------------------------
    # Score de matching
    # ------------------------------------------------------------------
    def calcular_score_match(self, registro: dict[str, Any], consulta: dict[str, Any]) -> dict[str, Any]:
        motivos: list[str] = []
        penalidades: list[str] = []
        score = 0.0

        marca_req = self._marca_key(consulta.get("marca"))
        marca_cand = self._marca_key(registro.get("marca_normalizada") or registro.get("marca"))
        if marca_req and marca_req == marca_cand:
            score += 25
            motivos.append("marca compatível")
        else:
            return {"score": 0.0, "motivos": ["marca incompatível"], "penalidades": [], "fuel_ok": False, "ano_exato": False, "modelo_score": 0.0}

        ano_resolvido = self.resolver_ano_fipe_para_matching(consulta)
        ano_req = ano_resolvido.get("ano_referencia")
        ano_cand = self._ano_tabela_registro(registro)
        ano_exato = False
        ano_diff = 999
        zero_km_contexto = bool(ano_resolvido.get("zero_km_contexto"))
        ano_compativel_fipe_pbev = False
        ano_relacao = "indefinido"

        if ano_req and ano_cand:
            diff = abs(ano_req - ano_cand)
            ano_diff = diff
            if diff == 0:
                score += 12
                ano_exato = True
                ano_compativel_fipe_pbev = True
                ano_relacao = "exato"
                motivos.append("ano PBEV igual ao ano-modelo FIPE")
            elif diff == 1:
                score += 7
                ano_compativel_fipe_pbev = True
                ano_relacao = "adjacente"
                motivos.append("ano PBEV adjacente ao ano-modelo FIPE")
            elif zero_km_contexto and ano_cand < ano_req and diff <= 3:
                score += 2
                ano_compativel_fipe_pbev = True
                ano_relacao = "zero_km_tabela_anterior"
                motivos.append("ano PBEV anterior aceito para zero km/ano-modelo")
            elif zero_km_contexto and ano_cand > ano_req and diff <= 1:
                score += 2
                ano_compativel_fipe_pbev = True
                ano_relacao = "zero_km_tabela_posterior"
                motivos.append("ano PBEV posterior próximo aceito para ano-modelo")
            else:
                score -= min(20, diff * 5)
                penalidades.append(f"ano distante ({ano_req} x {ano_cand})")
        elif zero_km_contexto and ano_cand:
            score += 10
            ano_diff = 0
            ano_compativel_fipe_pbev = True
            ano_relacao = "zero_km_tabela_atual"
            motivos.append("zero km FIPE: ano PBEV mais recente compatível priorizado")
        else:
            penalidades.append("ano FIPE ausente para score")

        query_modelo_norm = self.normalizar_aliases_automotivos(" ".join(str(consulta.get(k) or "") for k in ("modelo", "texto_modelo")))
        query_all_norm = self.normalizar_aliases_automotivos(self._texto_consulta(consulta))
        query_model_tokens = self._tokens(query_modelo_norm)
        query_model_core = self._modelo_core_tokens(query_modelo_norm)
        query_all_tokens = self._tokens(query_all_norm)
        query_trim_tokens = self._trim_tokens_contextual(query_all_norm)

        cand_model_norm = self.normalizar_aliases_automotivos(registro.get("modelo_normalizado") or registro.get("modelo"))
        cand_version_norm = self.normalizar_aliases_automotivos(registro.get("versao_normalizada") or registro.get("versao_corrigida") or registro.get("versao"))
        cand_motor_norm = self.normalizar_aliases_automotivos(registro.get("motor_normalizado") or registro.get("motor_corrigido") or registro.get("motor"))
        cand_trans_norm = self.normalizar_aliases_automotivos(registro.get("transmissao_normalizada") or registro.get("transmissao"))
        cand_all_norm = self.normalizar_aliases_automotivos(f"{cand_model_norm} {cand_version_norm} {cand_motor_norm} {cand_trans_norm}")

        cand_model_tokens = self._tokens(cand_model_norm)
        cand_model_core = self._modelo_core_tokens(cand_model_norm)
        cand_trim_tokens = self._trim_tokens_contextual(f"{cand_model_norm} {cand_version_norm}")
        score_modelo_geral = self.calcular_score_modelo(query_modelo_norm, f"{cand_model_norm} {cand_version_norm}")
        score += float(score_modelo_geral["ajuste"])
        motivos.extend(score_modelo_geral["motivos"])
        penalidades.extend(score_modelo_geral["penalidades"])
        modelo_overlap = len(cand_model_core & query_all_tokens) / max(1, len(cand_model_core))
        modelo_score = 0.0
        if modelo_overlap >= 1.0:
            modelo_score = 32
        elif modelo_overlap >= 0.67:
            modelo_score = 22
        elif modelo_overlap >= 0.50 and len(cand_model_core) <= 2:
            modelo_score = 12
        else:
            modelo_score = 0
            penalidades.append("família/modelo PBEV pouco compatível")

        if score_modelo_geral["token_forte_compativel"]:
            modelo_score = max(modelo_score, 32)
            penalidades = [p for p in penalidades if p != "família/modelo PBEV pouco compatível"]
        if score_modelo_geral["token_forte_divergente"]:
            modelo_score = min(modelo_score, 4)

        # Similaridade textual como apoio, sem substituir tokens técnicos.
        sim = self._ratio(cand_model_norm, query_modelo_norm)
        if sim >= 0.86:
            modelo_score += 4
        elif sim >= 0.74:
            modelo_score += 2

        # Modelos numéricos/alfanuméricos exigem cuidado:
        # Peugeot e-2008/e2008/e 2008 não pode empatar com e-208.
        def _numeros_modelo(tokens: set[str]) -> set[str]:
            nums: set[str] = set()
            for tk in tokens:
                if re.fullmatch(r"\d{2,5}", tk):
                    nums.add(tk)
                m_num = re.fullmatch(r"[A-Z]+(\d{2,5})(?:[A-Z]+)?", tk)
                if m_num:
                    nums.add(m_num.group(1))
            return nums

        identificadores_req = self.extrair_tokens_fortes_modelo(query_modelo_norm) or self._identificadores_comerciais_modelo(query_modelo_norm)
        identificadores_cand = self.extrair_tokens_fortes_modelo(f"{cand_model_norm} {cand_version_norm}") or self._identificadores_comerciais_modelo(cand_model_norm)
        identificador_comercial_divergente = self._identificadores_comerciais_divergentes(
            identificadores_req,
            identificadores_cand,
        )
        if identificador_comercial_divergente:
            modelo_score = min(modelo_score, 8)
            score -= 36
            penalidades.append(
                "identificador comercial/família divergente (" +
                ",".join(sorted(identificadores_req)) + " x " +
                ",".join(sorted(identificadores_cand)) + ")"
            )

        cand_nums_modelo = _numeros_modelo(cand_model_tokens | cand_model_core)
        query_nums_modelo = _numeros_modelo(query_all_tokens)
        if cand_nums_modelo and query_nums_modelo:
            if cand_nums_modelo & query_nums_modelo:
                if not identificador_comercial_divergente:
                    modelo_score = max(modelo_score, 32)
                    motivos.append("número/modelo compatível")
            else:
                score -= 28
                penalidades.append(
                    "número/modelo divergente (" +
                    ",".join(sorted(cand_nums_modelo)) + " x " +
                    ",".join(sorted(query_nums_modelo)) + ")"
                )

        # CROSS/PICKUP/etc. ausentes costumam indicar família diferente.
        hard_cand = cand_model_tokens & HARD_BODY_TOKENS
        hard_query = query_all_tokens & HARD_BODY_TOKENS
        if hard_cand and not hard_cand.issubset(query_all_tokens):
            score -= 30
            penalidades.append("descritor forte do PBEV ausente na FIPE: " + ", ".join(sorted(hard_cand - query_all_tokens)))
        if hard_query and not hard_query.issubset(set(cand_all_norm.split())):
            score -= 30
            penalidades.append("descritor forte da FIPE ausente no PBEV: " + ", ".join(sorted(hard_query - set(cand_all_norm.split()))))

        cand_all_tokens = set(cand_all_norm.split())
        family_query = self._family_descriptor_tokens_contextual(query_all_tokens, query_trim_tokens)
        family_cand = self._family_descriptor_tokens_contextual(cand_all_tokens, cand_trim_tokens)
        missing_family = family_query - family_cand
        extra_family = family_cand - query_all_tokens
        if missing_family:
            score -= 22 * len(missing_family)
            penalidades.append("descritor de família da FIPE ausente no PBEV: " + ", ".join(sorted(missing_family)))
        if extra_family:
            score -= 10 * len(extra_family)
            penalidades.append("descritor de família do PBEV ausente na FIPE: " + ", ".join(sorted(extra_family)))

        # HATCH x SEDAN ajuda, mas não bloqueia quando a FIPE só traz 4P/5P.
        soft_cand = cand_model_tokens & SOFT_BODY_TOKENS
        soft_query = query_all_tokens & SOFT_BODY_TOKENS
        if soft_cand and soft_query:
            if ({"HATCH", "HATCHBACK"} & soft_cand and {"SEDAN", "SEDA", "SED"} & soft_query) or ({"SEDAN", "SEDA", "SED"} & soft_cand and {"HATCH", "HATCHBACK"} & soft_query):
                score -= 10
                penalidades.append("carroceria hatch/sedan divergente")
        if "5P" in query_all_tokens and {"SEDAN", "SEDA", "SED"} & soft_cand:
            score -= 10
            penalidades.append("FIPE indica 5P; PBEV parece sedan")
        if "4P" in query_all_tokens and {"HATCH", "HATCHBACK"} & soft_cand:
            score -= 10
            penalidades.append("FIPE indica 4P; PBEV parece hatch")

        score += modelo_score
        if modelo_score >= 30:
            motivos.append("modelo/família compatível")
        elif modelo_score >= 20:
            motivos.append("modelo/família parcialmente compatível")

        req_fuel = self.resolver_propulsao_real(consulta, registro)
        cand_comb = self.normalizar_texto(registro.get("combustivel_normalizado") or registro.get("combustivel"))
        cand_prop = self.normalizar_texto(registro.get("tipo_propulsao_normalizado") or registro.get("tipo_propulsao"))
        fuel_ok, fuel_score, fuel_motivo = self._combustivel_compativel(req_fuel, cand_comb, cand_prop)
        score += fuel_score
        (motivos if fuel_score >= 0 else penalidades).append(fuel_motivo)

        acabamento_divergente = False
        acabamento_parcial = False
        acabamento_exato = False
        cand_version_tokens = self._version_tokens(cand_version_norm, cand_model_core)
        query_version_tokens = self._version_tokens(query_all_norm, query_model_core)
        if cand_trim_tokens:
            inter_trim = cand_trim_tokens & query_trim_tokens
            ratio_trim_cand = len(inter_trim) / max(1, len(cand_trim_tokens))
            ratio_trim_query = len(inter_trim) / max(1, len(query_trim_tokens)) if query_trim_tokens else ratio_trim_cand
            score += (9 * ratio_trim_cand) + (7 * ratio_trim_query)
            if ratio_trim_cand >= 0.75 and ratio_trim_query >= 0.75:
                acabamento_exato = True
                motivos.append("versão/acabamento compatível")
            elif inter_trim and (ratio_trim_cand >= 0.5 or ratio_trim_query >= 0.5):
                acabamento_parcial = True
                motivos.append("versão/acabamento parcialmente compatível")
            elif query_trim_tokens and cand_trim_tokens.isdisjoint(query_trim_tokens):
                acabamento_divergente = True
                score -= 12
                penalidades.append("acabamento divergente")
        elif cand_version_tokens:
            inter = cand_version_tokens & query_version_tokens
            ratio_version = len(inter) / max(1, len(cand_version_tokens))
            score += 8 * ratio_version
            if query_trim_tokens and not inter:
                acabamento_divergente = True
        else:
            score += 2
            if query_trim_tokens:
                acabamento_divergente = True

        motor_q = self._displacement_signature(query_all_norm)
        motor_c = self._displacement_signature(cand_motor_norm, cand_version_norm)
        if motor_q and motor_c:
            if motor_q == motor_c:
                score += 12
                motivos.append("motor compatível")
            else:
                score -= 12
                penalidades.append(f"motor divergente ({motor_q} x {motor_c})")
        valv_q = self._valvulas_signature(query_all_norm)
        valv_c = self._valvulas_signature(cand_motor_norm, cand_version_norm)
        if valv_q and valv_c and valv_q == valv_c:
            score += 3

        trans_q = self._transmissao_signature(query_all_norm)
        trans_c = self._transmissao_signature(cand_trans_norm, cand_version_norm)
        if trans_q and trans_c:
            if trans_q == trans_c:
                score += 8
                motivos.append("transmissão compatível")
            elif trans_q == "AUTO" and trans_c == "CVT":
                score += 5
                motivos.append("transmissão automática/CVT compatível")
            elif trans_q == "CVT" and trans_c == "AUTO":
                score += 4
                motivos.append("transmissão CVT/automática parcialmente compatível")
            else:
                score -= 8
                penalidades.append("transmissão divergente")

        ok_flags, bloqueios = self.validar_flags_autofill(registro)
        if not ok_flags:
            score -= 100
            penalidades.extend(bloqueios)

        identidade = self.avaliar_identidade_tecnica(
            fuel_ok=fuel_ok,
            ok_flags=ok_flags,
            modelo_score=modelo_score,
            penalidades=penalidades,
            motor_fipe=motor_q,
            motor_pbev=motor_c,
            transmissao_fipe=trans_q,
            transmissao_pbev=trans_c,
            token_forte_compativel=bool(score_modelo_geral["token_forte_compativel"]),
        )
        penalidades_tecnicas = identidade["penalidades_tecnicas"]
        penalidades_bloqueantes_consumo = identidade["penalidades_bloqueantes_consumo"]
        identidade_tecnica_forte = identidade["identidade_tecnica_forte"]
        tecnica_suficiente_para_consumo = identidade["tecnica_suficiente_para_consumo"]

        limite_ano_fallback = 3 if (
            score_modelo_geral.get("token_forte_compativel") and acabamento_exato
        ) else 2
        fallback_familia_tecnica = bool(
            not ano_compativel_fipe_pbev
            and ano_req and ano_cand and 0 < ano_diff <= limite_ano_fallback
            and int(score_modelo_geral.get("nivel_identidade_modelo") or 0) >= 3
            and fuel_ok and ok_flags and tecnica_suficiente_para_consumo
            and (not motor_q or not motor_c or motor_q == motor_c)
            and (not trans_q or not trans_c or trans_q == trans_c or {trans_q, trans_c} <= {"AUTO", "CVT"})
        )
        if fallback_familia_tecnica:
            ano_compativel_fipe_pbev = True
            ano_relacao = "familia_tecnica_proxima"
            motivos.append("ano PBEV próximo aceito por família técnica equivalente")

        score_bruto = max(0.0, round(score, 2))
        score_publico = min(100.0, score_bruto)
        return {
            "score": score_publico,
            "score_bruto": score_bruto,
            "motivos": motivos,
            "penalidades": penalidades,
            "fuel_ok": fuel_ok,
            "ano_exato": ano_exato,
            "ano_diff": ano_diff,
            "ano_req": ano_req,
            "ano_cand": ano_cand,
            "ano_relacao": ano_relacao,
            "zero_km_contexto": zero_km_contexto,
            "ano_compativel_fipe_pbev": ano_compativel_fipe_pbev,
            "modelo_score": round(modelo_score, 2),
            "nivel_identidade_modelo": int(score_modelo_geral.get("nivel_identidade_modelo") or 0),
            "familia_textual_compativel": bool(score_modelo_geral.get("familia_textual_compativel")),
            "familia_textual_divergente": bool(score_modelo_geral.get("familia_textual_divergente")),
            "designacao_exata": bool(score_modelo_geral.get("designacao_exata")),
            "designacao_parcial": bool(score_modelo_geral.get("designacao_parcial")),
            "fallback_familia_tecnica": fallback_familia_tecnica,
            "tokens_fortes_fipe": sorted(score_modelo_geral["tokens_fortes_fipe"]),
            "tokens_fortes_pbev": sorted(score_modelo_geral["tokens_fortes_pbev"]),
            "token_forte_compativel": bool(score_modelo_geral["token_forte_compativel"]),
            "token_forte_divergente": bool(score_modelo_geral["token_forte_divergente"]),
            "carroceria_fipe": sorted(score_modelo_geral["carroceria_fipe"]),
            "carroceria_pbev": sorted(score_modelo_geral["carroceria_pbev"]),
            "acabamento_exato": acabamento_exato,
            "acabamento_parcial": acabamento_parcial,
            "acabamento_divergente": acabamento_divergente,
            "ano_resolvido": ano_resolvido,
            "identificadores_comerciais_fipe": sorted(identificadores_req),
            "identificadores_comerciais_pbev": sorted(identificadores_cand),
            "identificador_comercial_divergente": identificador_comercial_divergente,
            "req_fuel": req_fuel,
            "ok_flags": ok_flags,
            "bloqueios_flags": bloqueios,
            "identidade_tecnica_forte": identidade_tecnica_forte,
            "tecnica_suficiente_para_consumo": tecnica_suficiente_para_consumo,
            "penalidades_bloqueantes_consumo": penalidades_bloqueantes_consumo,
            "penalidades_tecnicas": penalidades_tecnicas,
        }

    # ------------------------------------------------------------------
    # Consumo/eficiência sugeridos
    # ------------------------------------------------------------------
    def montar_sugestao_consumo(self, registro: dict[str, Any]) -> dict[str, Any] | None:
        prop = self.normalizar_texto(registro.get("tipo_propulsao_normalizado") or registro.get("tipo_propulsao")).replace(" ", "_")
        combustivel = self.normalizar_texto(registro.get("combustivel_normalizado") or registro.get("combustivel")).replace(" ", "_")

        gas_cid = self._num(registro, "gasolina_diesel_cidade_km_l_num") or self._num(registro, "gasolina_diesel_cidade_km_l")
        gas_est = self._num(registro, "gasolina_diesel_estrada_km_l_num") or self._num(registro, "gasolina_diesel_estrada_km_l")
        eta_cid = self._num(registro, "etanol_cidade_km_l_num") or self._num(registro, "etanol_cidade_km_l")
        eta_est = self._num(registro, "etanol_estrada_km_l_num") or self._num(registro, "etanol_estrada_km_l")
        kwh_km = self._num(registro, "consumo_eletrico_kwh_km_derivado")
        km_kwh = self._num(registro, "eficiencia_eletrica_km_kwh_derivada")
        mj_km = self._num(registro, "consumo_energetico_mj_km_num") or self._num(registro, "consumo_energetico_mj_km")
        autonomia = self._num(registro, "autonomia_eletrica_km_num") or self._num(registro, "autonomia_eletrica_km")

        base = {
            "criterio_campo_unico": "cidade_pbev_conservador",
            "observacao": "Consumo sugerido com base no Inmetro/PBEV. Você pode editar conforme seu uso real.",
        }

        if prop == "ELETRICO":
            if not kwh_km:
                return None
            return {
                **base,
                "tipo": "eletrico",
                "consumo_eletrico_kwh_km": round(kwh_km, 6),
                "eficiencia_eletrica_km_kwh": round(km_kwh, 6) if km_kwh else None,
                "consumo_energetico_mj_km": round(mj_km, 6) if mj_km else None,
                "autonomia_eletrica_km": round(autonomia, 2) if autonomia else None,
                "fonte_derivacao_eletrica": registro.get("fonte_derivacao_eletrica") or "MJ/km PBEV convertido para kWh/km",
                "nao_usar_km_l_equivalente": True,
            }

        if prop == "PLUG_IN":
            if not (kwh_km or gas_cid or eta_cid):
                return None
            return {
                **base,
                "tipo": "phev",
                "consumo_eletrico_kwh_km": round(kwh_km, 6) if kwh_km else None,
                "eficiencia_eletrica_km_kwh": round(km_kwh, 6) if km_kwh else None,
                "consumo_energetico_mj_km": round(mj_km, 6) if mj_km else None,
                "gasolina_diesel_cidade_km_l": round(gas_cid, 3) if gas_cid else None,
                "gasolina_diesel_estrada_km_l": round(gas_est, 3) if gas_est else None,
                "etanol_cidade_km_l": round(eta_cid, 3) if eta_cid else None,
                "etanol_estrada_km_l": round(eta_est, 3) if eta_est else None,
                "fonte_derivacao_eletrica": registro.get("fonte_derivacao_eletrica") or ("MJ/km PBEV convertido para kWh/km" if kwh_km else None),
                "nao_inferir_percentual_eletrico": True,
                "nao_usar_km_l_equivalente": True,
            }

        if combustivel == "FLEX":
            if not (gas_cid or eta_cid):
                return None
            return {
                **base,
                "tipo": "flex" if prop != "HIBRIDO" else "hibrido_flex",
                "gasolina_cidade_km_l": round(gas_cid, 3) if gas_cid else None,
                "gasolina_estrada_km_l": round(gas_est, 3) if gas_est else None,
                "etanol_cidade_km_l": round(eta_cid, 3) if eta_cid else None,
                "etanol_estrada_km_l": round(eta_est, 3) if eta_est else None,
                "consumo_energetico_mj_km": round(mj_km, 6) if mj_km else None,
            }

        if combustivel == "DIESEL":
            if not gas_cid:
                return None
            return {
                **base,
                "tipo": "diesel",
                "diesel_cidade_km_l": round(gas_cid, 3),
                "diesel_estrada_km_l": round(gas_est, 3) if gas_est else None,
                "consumo_energetico_mj_km": round(mj_km, 6) if mj_km else None,
            }

        if combustivel in {"GASOLINA", "ETANOL"} or prop in {"COMBUSTAO", "HIBRIDO"}:
            if not gas_cid:
                return None
            chave = "etanol" if combustivel == "ETANOL" else "gasolina"
            return {
                **base,
                "tipo": "hibrido" if prop == "HIBRIDO" else chave,
                f"{chave}_cidade_km_l": round(gas_cid, 3),
                f"{chave}_estrada_km_l": round(gas_est, 3) if gas_est else None,
                "consumo_energetico_mj_km": round(mj_km, 6) if mj_km else None,
            }

        return None

    @staticmethod
    def _candidato_publico(registro: dict[str, Any]) -> dict[str, Any]:
        """Recorte público e rastreável do registro PBEV usado pela interface.

        A Consulta Fipe+ usa estes campos como ficha técnica compacta. Não altera
        matching, não inventa consumo e não expõe a linha bruta inteira da base.
        """
        return {
            "id_pbev": registro.get("id_pbev_preliminar"),
            "ano_tabela": registro.get("ano_tabela"),
            "marca": registro.get("marca"),
            "modelo": registro.get("modelo"),
            "versao": registro.get("versao_corrigida") or registro.get("versao"),
            "motor": registro.get("motor_corrigido") or registro.get("motor"),
            "transmissao": registro.get("transmissao"),
            "transmissao_normalizada": registro.get("transmissao_normalizada"),
            "combustivel": registro.get("combustivel"),
            "combustivel_normalizado": registro.get("combustivel_normalizado"),
            "tipo_propulsao": registro.get("tipo_propulsao"),
            "tipo_propulsao_normalizado": registro.get("tipo_propulsao_normalizado"),
            "categoria": registro.get("categoria"),
            "categoria_normalizada": registro.get("categoria_normalizada"),
            "classificacao_pbe_absoluta_geral": registro.get("classificacao_pbe_absoluta_geral"),
            "classificacao_pbe_relativa_categoria": registro.get("classificacao_pbe_relativa_categoria"),
            "selo_conpet": registro.get("selo_conpet"),
            "co2_fossil_gasolina_diesel_g_km": registro.get("co2_fossil_gasolina_diesel_g_km_num") or registro.get("co2_fossil_gasolina_diesel_g_km"),
            "co2_fossil_etanol_g_km": registro.get("co2_fossil_etanol_g_km_num") or registro.get("co2_fossil_etanol_g_km"),
            "co2e_fossil_vehp_g_km": registro.get("co2e_fossil_vehp_g_km_num") or registro.get("co2e_fossil_vehp_g_km"),
            "consumo_energetico_mj_km": registro.get("consumo_energetico_mj_km_num") or registro.get("consumo_energetico_mj_km"),
            "consumo_eletrico_kwh_km_derivado": registro.get("consumo_eletrico_kwh_km_derivado"),
            "eficiencia_eletrica_km_kwh_derivada": registro.get("eficiencia_eletrica_km_kwh_derivada"),
            "autonomia_eletrica_km": registro.get("autonomia_eletrica_km_num") or registro.get("autonomia_eletrica_km"),
            "ar_condicionado": registro.get("ar_condicionado"),
            "direcao_assistida": registro.get("direcao_assistida"),
            "fonte_arquivo": registro.get("fonte_arquivo"),
            "data_atualizacao_pdf": registro.get("data_atualizacao_pdf"),
            "pagina": registro.get("pagina"),
            "confianca_registro": registro.get("confianca_registro"),
            "status_registro": registro.get("status_registro"),
            "chave_tecnica_normalizada": registro.get("chave_tecnica_normalizada"),
        }

    @staticmethod
    def _flags_publicas(registro: dict[str, Any]) -> dict[str, Any]:
        flags = {flag: bool(PbevService._bool_flag(registro.get(flag))) for flag in BLOQUEIO_AUTOFILL_FLAGS}
        flags["flag_inversao_versao_motor"] = bool(PbevService._bool_flag(registro.get("flag_inversao_versao_motor")))
        flags["status_registro"] = registro.get("status_registro")
        return flags

    @staticmethod
    def _fonte_oficial_por_ano(ano: Any) -> dict[str, Any]:
        try:
            ano_int = int(ano)
        except Exception:
            ano_int = 0
        fonte = dict(PBEV_FONTES_OFICIAIS.get(ano_int) or {})
        if not fonte:
            fonte = {
                "rotulo": "Página oficial do Inmetro/PBEV",
                "arquivo": "Tabela PBEV",
                "url": PBEV_PORTAL_URL,
            }
        fonte["ano"] = ano_int or None
        fonte["portal_url"] = PBEV_PORTAL_URL
        fonte["origem"] = "Inmetro/PBEV"
        return fonte

    @staticmethod
    def _assinatura_sugestao(sugestao: dict[str, Any] | None) -> tuple[Any, ...]:
        if not sugestao:
            return ()
        campos = (
            "tipo",
            "consumo_eletrico_kwh_km",
            "gasolina_cidade_km_l",
            "etanol_cidade_km_l",
            "diesel_cidade_km_l",
            "gasolina_diesel_cidade_km_l",
        )
        assinatura: list[Any] = []
        for campo in campos:
            valor = sugestao.get(campo)
            if isinstance(valor, (int, float)):
                assinatura.append(round(float(valor), 5))
            else:
                assinatura.append(valor or None)
        return tuple(assinatura)

    @classmethod
    def _assinatura_tecnica_registro(cls, registro: dict[str, Any]) -> tuple[Any, ...]:
        """Assinatura técnica para desempatar anos PBEV adjacentes/anteriores.

        Mantém versão, motor, válvulas, câmbio, combustível e propulsão.
        Não inclui ano_tabela, porque FIPE usa ano-modelo/zero km e PBEV usa ano da tabela.
        """
        modelo_norm = cls.normalizar_texto(registro.get("modelo_normalizado") or registro.get("modelo"))
        modelo_tokens = cls._tokens(modelo_norm)
        modelo_core = cls._modelo_core_tokens(modelo_norm)
        versao_norm = cls.normalizar_texto(registro.get("versao_normalizada") or registro.get("versao_corrigida") or registro.get("versao"))
        motor_norm = cls.normalizar_texto(registro.get("motor_normalizado") or registro.get("motor_corrigido") or registro.get("motor"))
        trans_norm = cls.normalizar_texto(registro.get("transmissao_normalizada") or registro.get("transmissao"))
        comb_norm = cls.normalizar_texto(registro.get("combustivel_normalizado") or registro.get("combustivel"))
        prop_norm = cls.normalizar_texto(registro.get("tipo_propulsao_normalizado") or registro.get("tipo_propulsao"))
        return (
            cls._marca_key(registro.get("marca_normalizada") or registro.get("marca")),
            tuple(sorted(modelo_core)),
            tuple(sorted(cls._version_tokens(versao_norm, modelo_core) & TRIM_TOKENS_IMPORTANTES)),
            cls._displacement_signature(motor_norm, versao_norm),
            cls._valvulas_signature(motor_norm, versao_norm),
            cls._transmissao_signature(trans_norm, versao_norm),
            comb_norm.replace(" ", "_"),
            prop_norm.replace(" ", "_"),
        )

    def _candidatos_proximos_bloqueiam_autofill(self, top: dict[str, Any], proximos: list[dict[str, Any]]) -> bool:
        """Retorna True quando há candidato próximo realmente ambíguo.

        A regra é conservadora, mas não burra: se versões próximas têm a mesma
        assinatura técnica ou o mesmo consumo aplicável ao campo da CurVE, não há motivo
        para bloquear o autofill. Isso cobre casos como Corolla Cross XRV/XRX no mesmo
        ano PBEV, em que a FIPE usa outro acabamento, mas o consumo é idêntico.
        """
        if not proximos:
            return False
        top_av = top.get("avaliacao") or {}
        top_forte = bool(top_av.get("identidade_tecnica_forte"))
        top_suficiente = bool(top_av.get("tecnica_suficiente_para_consumo"))
        top_sig = self._assinatura_tecnica_registro(top.get("registro") or {})
        top_sug = self._assinatura_sugestao(top.get("sugestao"))
        for cand in proximos:
            cand_av = cand.get("avaliacao") or {}
            # Um candidato tecnicamente fraco não pode bloquear outro que comprovou
            # família, motor, transmissão, combustível e flags. A regra é geral e
            # atua antes da comparação puramente numérica do score.
            if top_forte and not cand_av.get("identidade_tecnica_forte"):
                continue
            if top_suficiente and not cand_av.get("tecnica_suficiente_para_consumo"):
                continue
            cand_sig = self._assinatura_tecnica_registro(cand.get("registro") or {})
            if cand_sig == top_sig:
                continue
            cand_sug = self._assinatura_sugestao(cand.get("sugestao"))
            if top_sug and cand_sug == top_sug:
                continue
            return True
        return False

    def _candidatos_equivalentes_por_consumo(self, top: dict[str, Any], proximos: list[dict[str, Any]]) -> bool:
        """Indica se todos os próximos relevantes entregam o mesmo consumo aplicável."""
        if not proximos:
            return False
        top_sug = self._assinatura_sugestao(top.get("sugestao"))
        if not top_sug:
            return False
        return all(self._assinatura_sugestao(c.get("sugestao")) == top_sug for c in proximos)

    def _candidatos_tecnicos_para_conservador(self, top: dict[str, Any], proximos: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Grupo de candidatos próximos onde a divergência é versão/acabamento.

        Usado quando a FIPE é mais genérica que a PBEV. Ex.: Dolphin Mini sem
        versão na FIPE contra GS/GS 5/GL 5 na PBEV. O grupo só entra se todos
        tiverem combustível/propulsão compatível, ano compatível, flags OK,
        modelo/família forte e consumo útil.
        """
        grupo = [top] + list(proximos or [])
        filtrado: list[dict[str, Any]] = []
        tipos: set[str] = set()
        modelos_core: set[tuple[str, ...]] = set()
        for item in grupo:
            av = item.get("avaliacao") or {}
            sug = item.get("sugestao") or {}
            reg = item.get("registro") or {}
            if not sug or not av.get("ok_flags") or not av.get("fuel_ok") or not av.get("ano_compativel_fipe_pbev"):
                continue
            if float(av.get("modelo_score") or 0) < 30:
                continue
            if not av.get("tecnica_suficiente_para_consumo"):
                continue
            tipos.add(str(sug.get("tipo") or ""))
            modelo_norm = self.normalizar_texto(reg.get("modelo_normalizado") or reg.get("modelo"))
            modelos_core.add(tuple(sorted(self._modelo_core_tokens(modelo_norm))))
            filtrado.append(item)
        if len(filtrado) < 2 or len(tipos) != 1 or len(modelos_core) != 1:
            return []
        return filtrado

    @staticmethod
    def _min_num(valores: list[Any]) -> float | None:
        nums = [float(v) for v in valores if isinstance(v, (int, float)) and float(v) > 0]
        return min(nums) if nums else None

    @staticmethod
    def _max_num(valores: list[Any]) -> float | None:
        nums = [float(v) for v in valores if isinstance(v, (int, float)) and float(v) > 0]
        return max(nums) if nums else None

    def _montar_sugestao_conservadora(self, candidatos: list[dict[str, Any]]) -> dict[str, Any] | None:
        """Resolve versões próximas por pior caso de custo operacional.

        Elétrico/PHEV: maior kWh/km.
        Combustão/flex/diesel/híbrido: menor km/L.
        """
        if not candidatos:
            return None
        sugestoes = [c.get("sugestao") or {} for c in candidatos if c.get("sugestao")]
        if not sugestoes:
            return None
        tipo = str(sugestoes[0].get("tipo") or "")
        if any(str(s.get("tipo") or "") != tipo for s in sugestoes):
            return None

        conservadora = dict(sugestoes[0])
        criterio_extra = (
            "FIPE sem detalhar versão/acabamento; versões PBEV compatíveis avaliadas; "
            "adotado valor conservador para o custo operacional."
        )

        if tipo == "eletrico":
            maior = self._max_num([s.get("consumo_eletrico_kwh_km") for s in sugestoes])
            if not maior:
                return None
            conservadora["consumo_eletrico_kwh_km"] = round(maior, 6)
            # Recalcula eficiência coerente com o kWh/km escolhido quando possível.
            conservadora["eficiencia_eletrica_km_kwh"] = round(1 / maior, 6) if maior else conservadora.get("eficiencia_eletrica_km_kwh")
            maior_mj = self._max_num([s.get("consumo_energetico_mj_km") for s in sugestoes])
            if maior_mj:
                conservadora["consumo_energetico_mj_km"] = round(maior_mj, 6)
            criterio_extra = (
                "FIPE sem detalhar versão/acabamento; versões elétricas PBEV compatíveis avaliadas; "
                "adotado maior kWh/km por critério conservador."
            )
        elif tipo == "phev":
            maior = self._max_num([s.get("consumo_eletrico_kwh_km") for s in sugestoes])
            if maior:
                conservadora["consumo_eletrico_kwh_km"] = round(maior, 6)
                conservadora["eficiencia_eletrica_km_kwh"] = round(1 / maior, 6)
            maior_mj = self._max_num([s.get("consumo_energetico_mj_km") for s in sugestoes])
            if maior_mj:
                conservadora["consumo_energetico_mj_km"] = round(maior_mj, 6)
            for campo in ("gasolina_diesel_cidade_km_l", "gasolina_diesel_estrada_km_l", "etanol_cidade_km_l", "etanol_estrada_km_l"):
                menor = self._min_num([s.get(campo) for s in sugestoes])
                if menor:
                    conservadora[campo] = round(menor, 3)
            criterio_extra = (
                "FIPE sem detalhar versão/acabamento; versões PHEV da PBEV compatíveis avaliadas; "
                "adotado maior kWh/km e menor km/L por critério conservador, sem inferir percentual elétrico/combustível."
            )
        elif tipo in {"diesel", "gasolina", "hibrido"}:
            for campo in ("diesel_cidade_km_l", "diesel_estrada_km_l", "gasolina_cidade_km_l", "gasolina_estrada_km_l"):
                menor = self._min_num([s.get(campo) for s in sugestoes])
                if menor:
                    conservadora[campo] = round(menor, 3)
            criterio_extra = (
                "FIPE sem detalhar versão/acabamento; versões PBEV compatíveis avaliadas; "
                "adotado menor km/L por critério conservador."
            )
        elif tipo in {"flex", "hibrido_flex"}:
            for campo in ("gasolina_cidade_km_l", "gasolina_estrada_km_l", "etanol_cidade_km_l", "etanol_estrada_km_l"):
                menor = self._min_num([s.get(campo) for s in sugestoes])
                if menor:
                    conservadora[campo] = round(menor, 3)
            criterio_extra = (
                "FIPE sem detalhar versão/acabamento; versões PBEV compatíveis avaliadas; "
                "adotado menor km/L por critério conservador."
            )
        else:
            return None

        conservadora["criterio_conservador_versoes_compativeis"] = True
        conservadora["criterio_conservador_descricao"] = criterio_extra
        conservadora["versoes_pbev_consideradas"] = [
            " ".join(str((c.get("registro") or {}).get(k) or "") for k in ("modelo", "versao", "ano_tabela")).strip()
            for c in candidatos[:8]
        ]
        return conservadora

    # ------------------------------------------------------------------
    # Diagnóstico/debug provisório V38.3
    # ------------------------------------------------------------------
    @staticmethod
    def _resumo_sugestao_debug(sugestao: dict[str, Any] | None) -> dict[str, Any]:
        if not sugestao:
            return {}
        chaves = (
            "tipo",
            "criterio_campo_unico",
            "consumo_eletrico_kwh_km",
            "eficiencia_eletrica_km_kwh",
            "consumo_energetico_mj_km",
            "autonomia_eletrica_km",
            "gasolina_cidade_km_l",
            "gasolina_estrada_km_l",
            "etanol_cidade_km_l",
            "etanol_estrada_km_l",
            "diesel_cidade_km_l",
            "diesel_estrada_km_l",
            "gasolina_diesel_cidade_km_l",
            "gasolina_diesel_estrada_km_l",
            "fonte_derivacao_eletrica",
            "nao_usar_km_l_equivalente",
            "nao_inferir_percentual_eletrico",
            "criterio_conservador_versoes_compativeis",
            "criterio_conservador_descricao",
            "versoes_pbev_consideradas",
        )
        return {k: sugestao.get(k) for k in chaves if sugestao.get(k) not in (None, "", [])}

    def _debug_candidato_item(self, item: dict[str, Any], posicao: int) -> dict[str, Any]:
        avaliacao = item.get("avaliacao") or {}
        registro = item.get("registro") or {}
        sugestao = item.get("sugestao")
        return {
            "posicao": posicao,
            "score": round(float(item.get("score") or avaliacao.get("score_bruto") or avaliacao.get("score") or 0), 2),
            "score_publico": round(float(item.get("score_publico") or avaliacao.get("score") or 0), 2),
            "tem_sugestao_consumo": bool(sugestao),
            "flags_ok": bool(avaliacao.get("ok_flags")),
            "fuel_ok": bool(avaliacao.get("fuel_ok")),
            "modelo_score": avaliacao.get("modelo_score"),
            "ano_req": avaliacao.get("ano_req"),
            "ano_pbev": avaliacao.get("ano_cand"),
            "ano_diff": avaliacao.get("ano_diff"),
            "ano_relacao": avaliacao.get("ano_relacao"),
            "ano_compativel_fipe_pbev": bool(avaliacao.get("ano_compativel_fipe_pbev")),
            "zero_km_contexto": bool(avaliacao.get("zero_km_contexto")),
            "identidade_tecnica_forte": bool(avaliacao.get("identidade_tecnica_forte")),
            "tecnica_suficiente_para_consumo": bool(avaliacao.get("tecnica_suficiente_para_consumo")),
            "token_forte_divergente": bool(avaliacao.get("token_forte_divergente")),
            "familia_textual_divergente": bool(avaliacao.get("familia_textual_divergente")),
            "nivel_identidade_modelo": int(avaliacao.get("nivel_identidade_modelo") or 0),
            "designacao_exata": bool(avaliacao.get("designacao_exata")),
            "fallback_familia_tecnica": bool(avaliacao.get("fallback_familia_tecnica")),
            "combustivel_detectado_fipe": avaliacao.get("req_fuel"),
            "motivos": list(avaliacao.get("motivos") or []),
            "penalidades": list(avaliacao.get("penalidades") or []),
            "bloqueios_flags": list(avaliacao.get("bloqueios_flags") or []),
            "candidato": self._candidato_publico(registro),
            "sugestao_consumo": self._resumo_sugestao_debug(sugestao),
        }

    @staticmethod
    def _fmt_debug_val(valor: Any) -> str:
        if valor is None or valor == "":
            return "-"
        if isinstance(valor, bool):
            return "sim" if valor else "não"
        if isinstance(valor, float):
            return str(round(valor, 6)).replace(".", ",")
        return str(valor)

    def _montar_terminal_debug(self, debug: dict[str, Any], resposta: dict[str, Any] | None = None) -> str:
        resposta = resposta or {}
        linhas: list[str] = []
        add = linhas.append
        add("=== DIAGNÓSTICO PBEV / INMETRO — V38.6 ===")
        add("Ferramenta provisória para calibrar o matching FIPE × PBEV.")
        add("")

        entrada = debug.get("entrada_fipe") or {}
        add("[1] Dados recebidos da FIPE/Simular")
        for chave in ("prefixo", "marca", "modelo", "texto_modelo", "ano", "texto_ano", "ano_codigo", "combustivel", "tipo_veiculo", "codigo_fipe"):
            add(f"- {chave}: {self._fmt_debug_val(entrada.get(chave))}")
        add("")

        normalizacao = debug.get("normalizacao") or {}
        add("[2] Normalização usada na busca")
        add(f"- marca_key: {self._fmt_debug_val(normalizacao.get('marca_key'))}")
        add(f"- combustível/propulsão detectado: {self._fmt_debug_val(normalizacao.get('combustivel_detectado'))}")
        add(f"- texto normalizado: {self._fmt_debug_val(normalizacao.get('texto_normalizado'))}")
        tokens = normalizacao.get("tokens_modelo") or []
        add(f"- tokens do modelo: {', '.join(tokens[:40]) if tokens else '-'}")
        add("")

        filtros = debug.get("filtros") or {}
        add("[3] Filtros e contagens")
        for chave in (
            "registros_base",
            "marcas_indexadas",
            "registros_marca",
            "registros_avaliados_marca",
            "com_sugestao_consumo",
            "sem_sugestao_consumo",
            "descartados_score_baixo",
            "candidatos_considerados",
            "candidatos_utilizaveis",
            "candidatos_bloqueados_flags",
        ):
            add(f"- {chave}: {self._fmt_debug_val(filtros.get(chave))}")
        add("")

        candidatos = debug.get("candidatos_top") or []
        add("[4] Principais candidatos avaliados")
        if not candidatos:
            add("- Nenhum candidato com consumo útil entrou na lista de análise.")
        else:
            for cand in candidatos[:12]:
                cpub = cand.get("candidato") or {}
                nome = " ".join(str(cpub.get(k) or "") for k in ("marca", "modelo", "versao", "motor", "transmissao")).strip()
                add(f"{cand.get('posicao')}) {nome or '(sem identificação)'}")
                add(f"   Ano PBEV: {self._fmt_debug_val(cpub.get('ano_tabela') or cand.get('ano_pbev'))} | Score: {self._fmt_debug_val(cand.get('score'))} | Score público: {self._fmt_debug_val(cand.get('score_publico'))}")
                add(f"   Status: {self._fmt_debug_val(cpub.get('status_registro'))} | Flags OK: {self._fmt_debug_val(cand.get('flags_ok'))} | Sugestão consumo: {self._fmt_debug_val(cand.get('tem_sugestao_consumo'))}")
                add(f"   Ano relação: {self._fmt_debug_val(cand.get('ano_relacao'))} | Diferença ano: {self._fmt_debug_val(cand.get('ano_diff'))} | Identidade técnica forte: {self._fmt_debug_val(cand.get('identidade_tecnica_forte'))}")
                add(f"   Técnica suficiente para consumo: {self._fmt_debug_val(cand.get('tecnica_suficiente_para_consumo'))}")
                motivos = cand.get("motivos") or []
                penalidades = cand.get("penalidades") or []
                bloqueios = cand.get("bloqueios_flags") or []
                if motivos:
                    add("   + " + " | ".join(str(m) for m in motivos[:8]))
                if penalidades:
                    add("   - " + " | ".join(str(p) for p in penalidades[:8]))
                if bloqueios:
                    add("   ! bloqueios: " + " | ".join(str(b) for b in bloqueios[:8]))
                sug = cand.get("sugestao_consumo") or {}
                if sug:
                    valores = []
                    for k, v in sug.items():
                        if k in {"observacao"}:
                            continue
                        valores.append(f"{k}={self._fmt_debug_val(v)}")
                    add("   Consumo/eficiência: " + ("; ".join(valores[:12]) if valores else "-"))
                add("")

        add("[5] Decisão final")
        add(f"- encontrou: {self._fmt_debug_val(resposta.get('encontrou'))}")
        add(f"- nível: {self._fmt_debug_val(resposta.get('nivel_match'))}")
        add(f"- autopreencher: {self._fmt_debug_val(resposta.get('autopreencher'))}")
        add(f"- score exibido: {self._fmt_debug_val(resposta.get('score'))}")
        if resposta.get("score_bruto") not in (None, ""):
            add(f"- score bruto: {self._fmt_debug_val(resposta.get('score_bruto'))}")
        add(f"- motivo: {self._fmt_debug_val(resposta.get('motivo'))}")
        diag_final = resposta.get("diagnostico") or {}
        for chave in ("criterio_match", "dominante", "ambiguidade_proxima", "dominancia_resolvida_por_identidade_tecnica", "ambiguidade_resolvida_por_consumo", "ambiguidade_resolvida_por_criterio_conservador", "candidatos_conservador", "diferenca_para_segundo", "score_segundo_candidato", "ano_relacao", "ano_compativel_fipe_pbev", "zero_km_contexto", "identidade_tecnica_forte", "tecnica_suficiente_para_consumo", "modelo_score"):
            if chave in diag_final:
                add(f"- {chave}: {self._fmt_debug_val(diag_final.get(chave))}")
        add("")

        add("[6] Ação aplicada na Simular")
        if resposta.get("autopreencher") and resposta.get("nivel_match") == "alto":
            add("- A interface deve aplicar a sugestão nos campos de consumo editáveis.")
        else:
            add("- Nenhum valor deve ser colocado automaticamente. O consumo fica manual.")
        add("- Esta janela é provisória de auditoria do matching; não altera TCO, depreciação ou painel local.")
        return "\n".join(linhas)

    # ------------------------------------------------------------------
    # API principal
    # ------------------------------------------------------------------
    def resolver_ambiguidade_por_consumo(self, top: dict[str, Any], proximos: list[dict[str, Any]]) -> dict[str, Any]:
        equivalentes = self._candidatos_equivalentes_por_consumo(top, proximos)
        grupo = self._candidatos_tecnicos_para_conservador(top, proximos)
        conservadora = self.aplicar_criterio_conservador(grupo)
        return {"equivalentes": equivalentes, "grupo": grupo, "sugestao_conservadora": conservadora}

    def aplicar_criterio_conservador(self, candidatos: list[dict[str, Any]]) -> dict[str, Any] | None:
        return self._montar_sugestao_conservadora(candidatos)

    @staticmethod
    def _criterio_match(
        avaliacao: dict[str, Any], *, equivalentes: bool, conservador: bool,
        aproximacao: bool = False,
    ) -> str:
        if aproximacao:
            return "aproximacao_com_observacao"
        if conservador:
            return "conservador_por_familia"
        fallback_com_acabamento_divergente = bool(
            avaliacao.get("fallback_familia_tecnica")
            and avaliacao.get("acabamento_divergente")
        )
        if equivalentes and not fallback_com_acabamento_divergente:
            return "versoes_equivalentes"
        if avaliacao.get("fallback_familia_tecnica") or (avaliacao.get("acabamento_divergente") and avaliacao.get("tecnica_suficiente_para_consumo")):
            return "conservador_por_familia"
        if avaliacao.get("ano_exato") or avaliacao.get("ano_relacao") == "zero_km_tabela_atual":
            return "exato"
        if avaliacao.get("ano_relacao") in {"adjacente", "zero_km_tabela_anterior", "zero_km_tabela_posterior"}:
            return "ano_modelo_adjacente"
        return "aproximacao_com_observacao"

    @staticmethod
    def _cobertura_por_criterio(criterio_match: str, *, autopreencher: bool) -> str:
        if criterio_match == "exato":
            return "exata"
        if criterio_match == "versoes_equivalentes":
            return "equivalente"
        if criterio_match in {"ano_modelo_adjacente", "conservador_por_familia", "aproximacao_com_observacao"}:
            return "familia"
        return "ausente"

    @classmethod
    def decidir_nivel_match(
        cls, *, avaliacao: dict[str, Any], score: float, dominante: bool,
        ambiguidade: bool, tem_consumo: bool, criterio_match: str,
    ) -> tuple[str, bool]:
        base_tecnica = (
            avaliacao.get("ok_flags") and avaliacao.get("fuel_ok")
            and avaliacao.get("ano_compativel_fipe_pbev")
            and avaliacao.get("tecnica_suficiente_para_consumo")
            and float(avaliacao.get("modelo_score") or 0) >= 30
            and tem_consumo
        )
        if base_tecnica and dominante and not ambiguidade and score >= 74:
            return "alto", True
        if criterio_match == "conservador_por_familia" and base_tecnica and dominante and not ambiguidade:
            return "alto", True
        if score >= 70 and tem_consumo:
            return "medio", False
        if score >= 50 and tem_consumo:
            return "baixo", False
        return "sem_match", False

    def sugerir_consumo(self, consulta: dict[str, Any]) -> dict[str, Any]:
        entrada_debug = {
            "prefixo": consulta.get("prefixo"),
            "marca": consulta.get("marca"),
            "modelo": consulta.get("modelo"),
            "texto_modelo": consulta.get("texto_modelo"),
            "ano": consulta.get("ano"),
            "texto_ano": consulta.get("texto_ano"),
            "ano_codigo": consulta.get("ano_codigo"),
            "combustivel": consulta.get("combustivel"),
            "tipo_veiculo": consulta.get("tipo_veiculo"),
            "codigo_fipe": consulta.get("codigo_fipe"),
            "codigo_marca": consulta.get("codigo_marca") or consulta.get("marca_id"),
            "codigo_modelo": consulta.get("codigo_modelo") or consulta.get("modelo_id"),
        }
        texto_normalizado = self.normalizar_aliases_automotivos(self._texto_consulta(consulta))
        marca_key = self._marca_key(consulta.get("marca"))
        marca_keys_busca = self._marca_keys_busca(consulta)
        debug: dict[str, Any] = {
            "entrada_fipe": entrada_debug,
            "normalizacao": {
                "marca_key": marca_key,
                "marca_keys_busca": marca_keys_busca,
                "combustivel_detectado": self._detectar_combustivel_consulta(consulta),
                "texto_normalizado": texto_normalizado,
                "tokens_modelo": sorted(self._tokens(" ".join(str(consulta.get(k) or "") for k in ("modelo", "texto_modelo"))))[:80],
                "tokens_fortes_modelo": sorted(self.extrair_tokens_fortes_modelo(" ".join(str(consulta.get(k) or "") for k in ("modelo", "texto_modelo")))),
                "ano_resolvido": self.resolver_ano_fipe_para_matching(consulta),
            },
            "filtros": {},
            "candidatos_top": [],
        }

        try:
            cache = self.carregar_base_pbev()
        except Exception as exc:
            resposta = {
                "encontrou": False,
                "nivel_match": "sem_match",
                "score": 0,
                "motivo": f"Base PBEV indisponível: {exc}",
                "autopreencher": False,
                "criterio_match": "sem_match",
                "cobertura_pbev": "ausente",
                "origem": "Inmetro/PBEV",
                "sugestoes_consumo": {},
                "candidato": None,
                "flags": {},
                "motivo_decisao": [],
                "motivo_nao_preenchimento": [f"Base PBEV indisponível: {exc}"],
                "candidatos_equivalentes": [],
                "diagnostico": {},
            }
            debug["filtros"] = {"registros_base": 0, "marcas_indexadas": 0, "registros_marca": 0}
            resposta["debug"] = debug
            resposta["diagnostico_terminal"] = self._montar_terminal_debug(debug, resposta)
            return resposta

        debug["filtros"].update({
            "registros_base": len(cache.registros),
            "marcas_indexadas": len(cache.indice_marca),
        })

        if not marca_key:
            resposta = {
                "encontrou": False,
                "nivel_match": "sem_match",
                "score": 0,
                "motivo": "Marca FIPE ausente para busca PBEV.",
                "autopreencher": False,
                "criterio_match": "sem_match",
                "cobertura_pbev": "ausente",
                "origem": "Inmetro/PBEV",
                "sugestoes_consumo": {},
                "candidato": None,
                "flags": {},
                "motivo_decisao": [],
                "motivo_nao_preenchimento": ["Marca FIPE ausente para busca PBEV."],
                "candidatos_equivalentes": [],
                "diagnostico": {},
            }
            debug["filtros"].update({"registros_marca": 0, "registros_avaliados_marca": 0})
            resposta["debug"] = debug
            resposta["diagnostico_terminal"] = self._montar_terminal_debug(debug, resposta)
            return resposta

        registros_marca: list[dict[str, Any]] = []
        vistos_registros: set[int] = set()
        for chave_marca in marca_keys_busca or [marca_key]:
            for registro in cache.indice_marca.get(chave_marca, []):
                ident = id(registro)
                if ident not in vistos_registros:
                    vistos_registros.add(ident)
                    registros_marca.append(registro)
        candidatos: list[dict[str, Any]] = []
        candidatos_bloqueados = 0
        debug_items: list[dict[str, Any]] = []
        sem_sugestao_consumo = 0
        com_sugestao_consumo = 0
        descartados_score_baixo = 0
        descartados_prefiltro_identidade = 0

        texto_modelo_consulta = " ".join(str(consulta.get(k) or "") for k in ("modelo", "texto_modelo"))
        fortes_consulta = {
            token for token in self.extrair_tokens_fortes_modelo(texto_modelo_consulta)
            if not self._token_forte_tecnico(token)
        }
        palavras_consulta = self._palavras_familia_modelo(texto_modelo_consulta)

        def _passa_prefiltro_identidade(registro: dict[str, Any]) -> bool:
            texto_candidato = " ".join(str(registro.get(k) or "") for k in ("modelo", "versao_corrigida", "versao"))
            fortes_candidato = {
                token for token in self.extrair_tokens_fortes_modelo(texto_candidato)
                if not self._token_forte_tecnico(token)
            }
            palavras_candidato = self._palavras_familia_modelo(texto_candidato)
            if fortes_consulta:
                if fortes_candidato and not (fortes_consulta & fortes_candidato):
                    return False
                if not fortes_candidato and palavras_consulta and palavras_candidato and not (palavras_consulta & palavras_candidato):
                    return False
            elif palavras_consulta and palavras_candidato and not (palavras_consulta & palavras_candidato):
                return False
            return True

        for registro in registros_marca:
            if not _passa_prefiltro_identidade(registro):
                descartados_prefiltro_identidade += 1
                continue
            avaliacao = self.calcular_score_match(registro, consulta)
            sugestao = self.montar_sugestao_consumo(registro)
            item = {
                "registro": registro,
                "score": float(avaliacao.get("score_bruto", avaliacao["score"])),
                "score_publico": float(avaliacao["score"]),
                "avaliacao": avaliacao,
                "sugestao": sugestao,
            }
            # Guarda candidatos com algum sinal mínimo para o terminal, inclusive bloqueados/sem consumo.
            if avaliacao["score"] >= 25 or avaliacao.get("bloqueios_flags") or sugestao:
                debug_items.append(item)
            if not sugestao:
                sem_sugestao_consumo += 1
            else:
                com_sugestao_consumo += 1
            if avaliacao["score"] < 35 and not avaliacao.get("bloqueios_flags"):
                descartados_score_baixo += 1
                continue
            if not sugestao:
                continue
            if not avaliacao.get("ok_flags"):
                candidatos_bloqueados += 1
            candidatos.append(item)

        def _ordem_candidato(c: dict[str, Any]) -> tuple[Any, ...]:
            avaliacao = c.get("avaliacao") or {}
            ano_cand = int(avaliacao.get("ano_cand") or self._ano_tabela_registro(c.get("registro") or {}))
            zero_km = bool(avaliacao.get("zero_km_contexto"))
            zero_km_sem_ano_real = zero_km and not avaliacao.get("ano_req")
            nivel_identidade = int(avaliacao.get("nivel_identidade_modelo") or 0)
            ano_zero_km_preferido = ano_cand if zero_km and avaliacao.get("ano_compativel_fipe_pbev") else 0
            return (
                1 if avaliacao.get("fuel_ok") else 0,
                1 if avaliacao.get("tecnica_suficiente_para_consumo") else 0,
                nivel_identidade,
                ano_zero_km_preferido if zero_km_sem_ano_real else 0,
                1 if avaliacao.get("ano_exato") else 0,
                1 if avaliacao.get("designacao_exata") else 0,
                1 if avaliacao.get("identidade_tecnica_forte") else 0,
                1 if avaliacao.get("fallback_familia_tecnica") else 0,
                float(avaliacao.get("modelo_score") or 0),
                float(c.get("score") or 0),
                ano_zero_km_preferido,
                -int(avaliacao.get("ano_diff") if avaliacao.get("ano_diff") is not None else 999),
            )

        candidatos.sort(key=_ordem_candidato, reverse=True)
        debug_items.sort(key=_ordem_candidato, reverse=True)

        def _priorizar_identidade_tecnica(lista: list[dict[str, Any]]) -> list[dict[str, Any]]:
            if not lista:
                return lista
            scores_validos = [float(item.get("score") or 0) for item in lista if (item.get("avaliacao") or {}).get("ok_flags")]
            if not scores_validos:
                return lista
            score_maximo = max(scores_validos)
            faixa = [
                item for item in lista
                if (item.get("avaliacao") or {}).get("ok_flags")
                and score_maximo - float(item.get("score") or 0) < 8
            ]
            exatos_suficientes = [
                item for item in faixa
                if (item.get("avaliacao") or {}).get("ano_exato")
                and (item.get("avaliacao") or {}).get("tecnica_suficiente_para_consumo")
            ]
            if exatos_suficientes:
                preferido = max(exatos_suficientes, key=_ordem_candidato)
            else:
                fortes = [item for item in faixa if (item.get("avaliacao") or {}).get("identidade_tecnica_forte")]
                if not fortes:
                    fortes = [item for item in faixa if (item.get("avaliacao") or {}).get("tecnica_suficiente_para_consumo")]
                if not fortes:
                    return lista
                preferido = max(fortes, key=_ordem_candidato)
            if lista[0] is preferido:
                return lista
            return [preferido] + [item for item in lista if item is not preferido]

        candidatos = _priorizar_identidade_tecnica(candidatos)
        debug_items = _priorizar_identidade_tecnica(debug_items)
        utilizaveis = [c for c in candidatos if c["avaliacao"].get("ok_flags")]

        debug["filtros"].update({
            "registros_marca": len(registros_marca),
            "registros_avaliados_marca": len(registros_marca),
            "com_sugestao_consumo": com_sugestao_consumo,
            "sem_sugestao_consumo": sem_sugestao_consumo,
            "descartados_score_baixo": descartados_score_baixo,
            "descartados_prefiltro_identidade": descartados_prefiltro_identidade,
            "candidatos_considerados": len(candidatos),
            "candidatos_utilizaveis": len(utilizaveis),
            "candidatos_bloqueados_flags": candidatos_bloqueados,
        })
        debug["candidatos_top"] = [self._debug_candidato_item(item, idx + 1) for idx, item in enumerate(debug_items[:12])]

        if not utilizaveis:
            bloqueados_relevantes = [
                item for item in debug_items
                if not (item.get("avaliacao") or {}).get("ok_flags")
                and (item.get("avaliacao") or {}).get("fuel_ok")
                and float((item.get("avaliacao") or {}).get("modelo_score") or 0) >= 30
                and not (item.get("avaliacao") or {}).get("token_forte_divergente")
                and not (item.get("avaliacao") or {}).get("familia_textual_divergente")
            ]
            motivo = "Nenhum candidato PBEV confiável encontrado."
            if candidatos_bloqueados:
                motivo += f" {candidatos_bloqueados} candidato(s) foram bloqueados por status/flags."
            resposta = {
                "encontrou": False,
                "nivel_match": "sem_match",
                "score": 0,
                "motivo": motivo,
                "autopreencher": False,
                "criterio_match": "sem_match",
                "cobertura_pbev": "bloqueada" if bloqueados_relevantes else "ausente",
                "origem": "Inmetro/PBEV",
                "sugestoes_consumo": {},
                "candidato": None,
                "flags": {},
                "motivo_decisao": [],
                "motivo_nao_preenchimento": [motivo],
                "candidatos_equivalentes": [],
                "diagnostico": {
                    "candidatos_bloqueados": candidatos_bloqueados,
                    "candidatos_bloqueados_relevantes": len(bloqueados_relevantes),
                    "total_candidatos_marca": len(registros_marca),
                },
            }
            resposta["debug"] = debug
            resposta["diagnostico_terminal"] = self._montar_terminal_debug(debug, resposta)
            return resposta

        top = utilizaveis[0]
        segundo_score = utilizaveis[1]["score"] if len(utilizaveis) > 1 else None
        diferenca = top["score"] - segundo_score if segundo_score is not None else None
        avaliacao_top = top["avaliacao"]
        top_nivel_identidade = int(avaliacao_top.get("nivel_identidade_modelo") or 0)
        candidatos_proximos = [
            c for c in utilizaveis[1:]
            if abs(float(top["score"]) - float(c["score"])) < 8
            and int((c.get("avaliacao") or {}).get("nivel_identidade_modelo") or 0) >= max(2, top_nivel_identidade - 1)
            and not (c.get("avaliacao") or {}).get("token_forte_divergente")
            and not (c.get("avaliacao") or {}).get("familia_textual_divergente")
            and (
                not avaliacao_top.get("designacao_exata")
                or (c.get("avaliacao") or {}).get("designacao_exata")
            )
        ]
        dominante = segundo_score is None or (diferenca is not None and diferenca >= 8)

        # Se o melhor candidato é do ano exato, candidatos adjacentes não devem bloquear
        # quando existe grupo do mesmo ano para comparação. Ex.: Corolla Cross 2022 XRV/XRX
        # empata no mesmo ano e no mesmo consumo; 2021/2023 não devem travar a escolha 2022.
        proximos_mesmo_ano = [c for c in candidatos_proximos if (c.get("avaliacao") or {}).get("ano_exato")]
        # Ano exato tecnicamente suficiente não deve ser bloqueado por versões de
        # anos adjacentes, mesmo quando estas têm score textual parecido ou maior.
        proximos_relevantes_ambiguidade = proximos_mesmo_ano if avaliacao_top.get("ano_exato") else candidatos_proximos
        ambiguidade_proxima = self._candidatos_proximos_bloqueiam_autofill(top, proximos_relevantes_ambiguidade)
        dominancia_resolvida_por_identidade_tecnica = bool(
            proximos_relevantes_ambiguidade
            and avaliacao_top.get("identidade_tecnica_forte")
            and not ambiguidade_proxima
            and any(not (c.get("avaliacao") or {}).get("identidade_tecnica_forte") for c in proximos_relevantes_ambiguidade)
        )
        resolucao_ambiguidade = self.resolver_ambiguidade_por_consumo(top, proximos_relevantes_ambiguidade)
        ambiguidade_resolvida_por_consumo = bool(resolucao_ambiguidade["equivalentes"])
        grupo_conservador = resolucao_ambiguidade["grupo"]
        sugestao_conservadora = resolucao_ambiguidade["sugestao_conservadora"]
        if ambiguidade_resolvida_por_consumo:
            dominante = True
            ambiguidade_proxima = False
        ambiguidade_resolvida_por_criterio_conservador = bool(ambiguidade_proxima and sugestao_conservadora)
        if ambiguidade_resolvida_por_criterio_conservador:
            top["sugestao"] = sugestao_conservadora
            dominante = True
            ambiguidade_proxima = False

        if not dominante and avaliacao_top.get("ano_exato"):
            if not proximos_mesmo_ano:
                dominante = True
            elif not ambiguidade_proxima:
                dominante = True

        if (
            not dominante
            and avaliacao_top.get("tecnica_suficiente_para_consumo")
            and avaliacao_top.get("ano_compativel_fipe_pbev")
            and not ambiguidade_proxima
        ):
            dominante = True

        score_top = float(top["score"])
        score_publico_top = float(top.get("score_publico", min(100.0, score_top)))
        aproximacao = bool(
            not avaliacao_top.get("ano_compativel_fipe_pbev")
            or float(avaliacao_top.get("modelo_score") or 0) < 30
        )
        criterio_match = self._criterio_match(
            avaliacao_top,
            equivalentes=ambiguidade_resolvida_por_consumo,
            conservador=ambiguidade_resolvida_por_criterio_conservador,
            aproximacao=aproximacao,
        )
        nivel, autopreencher = self.decidir_nivel_match(
            avaliacao=avaliacao_top,
            score=score_top,
            dominante=dominante,
            ambiguidade=ambiguidade_proxima,
            tem_consumo=bool(top.get("sugestao")),
            criterio_match=criterio_match,
        )

        # Um fallback técnico conservador pode ter apenas um registro utilizável
        # da família correta. Nesse caso, mantém o consumo observado, mas marca
        # explicitamente que não é correspondência exata de acabamento.
        if criterio_match == "conservador_por_familia" and top.get("sugestao"):
            sugestao_marcada = dict(top["sugestao"])
            sugestao_marcada.setdefault("criterio_conservador_versoes_compativeis", True)
            sugestao_marcada.setdefault(
                "criterio_conservador_descricao",
                "Correspondência pela família técnica compatível; usado o consumo PBEV disponível com observação conservadora.",
            )
            if not sugestao_marcada.get("versoes_pbev_consideradas"):
                reg_top = top.get("registro") or {}
                sugestao_marcada["versoes_pbev_consideradas"] = [
                    " ".join(str(reg_top.get(k) or "") for k in ("modelo", "versao", "ano_tabela")).strip()
                ]
            top["sugestao"] = sugestao_marcada

        if nivel == "medio":
            score_retorno = min(score_publico_top, 89.0)
        elif nivel == "baixo":
            score_retorno = min(score_publico_top, 69.0)
        elif nivel == "sem_match":
            score_retorno = 0.0
        else:
            score_retorno = score_publico_top

        motivos = list(avaliacao_top.get("motivos") or [])
        penalidades = list(avaliacao_top.get("penalidades") or [])
        if dominancia_resolvida_por_identidade_tecnica:
            motivos.append("candidato dominante por identidade técnica forte; candidatos próximos tecnicamente fracos não bloqueiam")
        if ambiguidade_resolvida_por_consumo:
            motivos.append("candidatos próximos têm o mesmo consumo aplicável; ambiguidade não bloqueia")
        if ambiguidade_resolvida_por_criterio_conservador:
            motivos.append("candidatos próximos da mesma família resolvidos por critério conservador de consumo")
        if not dominante:
            penalidades.append("há outro candidato PBEV próximo tecnicamente ambíguo; autofill bloqueado")
        if nivel != "alto" and not penalidades:
            penalidades.append("score insuficiente para autofill automático")

        motivo_txt = "; ".join(motivos + penalidades) or "Matching PBEV avaliado."
        resposta = {
            "encontrou": nivel != "sem_match",
            "nivel_match": nivel,
            "score": round(score_retorno, 2),
            "score_bruto": round(score_top, 2),
            "motivo": motivo_txt,
            "autopreencher": autopreencher,
            "criterio_match": criterio_match,
            "cobertura_pbev": self._cobertura_por_criterio(criterio_match, autopreencher=autopreencher),
            "origem": "Inmetro/PBEV",
            "ano_tabela_pbev": top["registro"].get("ano_tabela"),
            "candidato": self._candidato_publico(top["registro"]),
            "sugestoes_consumo": top["sugestao"],
            "flags": self._flags_publicas(top["registro"]),
            "fonte_oficial": self._fonte_oficial_por_ano(top["registro"].get("ano_tabela")),
            "motivo_decisao": motivos,
            "motivo_nao_preenchimento": [] if autopreencher else penalidades,
            "candidatos_equivalentes": [
                self._candidato_publico(item.get("registro") or {})
                for item in ([top] + list(proximos_relevantes_ambiguidade))
                if item.get("registro")
                and (
                    self._assinatura_sugestao(item.get("sugestao")) == self._assinatura_sugestao(top.get("sugestao"))
                    or item is top
                )
            ],
            "diagnostico": {
                "score_segundo_candidato": round(segundo_score, 2) if segundo_score is not None else None,
                "diferenca_para_segundo": round(diferenca, 2) if diferenca is not None else None,
                "dominante": dominante,
                "candidatos_considerados": len(candidatos),
                "candidatos_utilizaveis": len(utilizaveis),
                "candidatos_bloqueados": candidatos_bloqueados,
                "ano_exato": bool(avaliacao_top.get("ano_exato")),
                "ano_diff": avaliacao_top.get("ano_diff"),
                "ano_relacao": avaliacao_top.get("ano_relacao"),
                "ano_compativel_fipe_pbev": bool(avaliacao_top.get("ano_compativel_fipe_pbev")),
                "zero_km_contexto": bool(avaliacao_top.get("zero_km_contexto")),
                "identidade_tecnica_forte": bool(avaliacao_top.get("identidade_tecnica_forte")),
                "tecnica_suficiente_para_consumo": bool(avaliacao_top.get("tecnica_suficiente_para_consumo")),
                "ambiguidade_proxima": bool(ambiguidade_proxima),
                "dominancia_resolvida_por_identidade_tecnica": bool(dominancia_resolvida_por_identidade_tecnica),
                "ambiguidade_resolvida_por_consumo": bool(ambiguidade_resolvida_por_consumo),
                "ambiguidade_resolvida_por_criterio_conservador": bool(ambiguidade_resolvida_por_criterio_conservador),
                "candidatos_conservador": len(grupo_conservador),
                "modelo_score": avaliacao_top.get("modelo_score"),
                "combustivel_detectado_fipe": avaliacao_top.get("req_fuel"),
                "criterio_match": criterio_match,
                "tokens_fortes_fipe": avaliacao_top.get("tokens_fortes_fipe"),
                "tokens_fortes_pbev": avaliacao_top.get("tokens_fortes_pbev"),
                "carroceria_fipe": avaliacao_top.get("carroceria_fipe"),
                "carroceria_pbev": avaliacao_top.get("carroceria_pbev"),
                "acabamento_exato": avaliacao_top.get("acabamento_exato"),
                "acabamento_parcial": avaliacao_top.get("acabamento_parcial"),
                "acabamento_divergente": avaliacao_top.get("acabamento_divergente"),
            },
            "valor_autopreenchido": autopreencher,
        }
        resposta["debug"] = debug
        resposta["diagnostico_terminal"] = self._montar_terminal_debug(debug, resposta)
        return resposta
