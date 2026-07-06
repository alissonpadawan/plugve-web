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
    "AUT", "AUTO", "AUTOMATICO", "AUTOMATICA", "AT", "A", "CVT", "M", "MT", "MANUAL", "MEC", "MECANICO", "MECANICA",
}
ENGINE_TOKENS = {"8V", "10V", "12V", "16V", "20V", "24V", "32V", "40V", "48V", "60V"}
GENERIC_TOKENS = {
    "DE", "DO", "DA", "DOS", "DAS", "E", "COM", "SEM", "PARA", "THE", "OF", "BY",
    "NOVO", "NOVA", "NEW", "ZERO", "KM", "MY", "MODELO", "VERSAO", "VERSÃO",
    "PORTA", "PORTAS", "P", "CV", "HP", "TURBO", "T", "TSI", "TFSI", "GDI", "MPI",
    "VVT", "VVTIE", "VVT I", "DOHC", "SOHC", "VALV", "VALVULAS", "VALVULAS",
}
# CROSS costuma mudar família/modelo no PBEV e na FIPE (Yaris x Yaris Cross, Corolla x Corolla Cross).
HARD_BODY_TOKENS = {"CROSS", "PICKUP", "PICAPE", "CABINE", "CAB", "SW", "WAGON", "TOURING", "VAN", "MINIVAN"}
# HATCH/SEDAN ajudam, mas a FIPE frequentemente usa apenas 4P/5P ou omite a carroceria.
SOFT_BODY_TOKENS = {"HATCH", "HATCHBACK", "SEDAN", "SEDA", "SED", "SPORTBACK"}
VERSION_STOP_TOKENS = FUEL_TOKENS | TRANS_TOKENS | ENGINE_TOKENS | GENERIC_TOKENS | SOFT_BODY_TOKENS | {
    "4P", "5P", "2P", "3P", "1P", "6P", "7L", "L", "V", "VALVE", "VALVES",
}
TRIM_TOKENS_IMPORTANTES = {
    "XR", "XS", "XL", "XLS", "XRE", "XRX", "XRV", "GR", "GRS", "GL", "GS", "SE", "SEL", "SL",
    "LT", "LTZ", "LS", "RS", "SS", "MID", "HC", "Z71", "EX", "EXL", "EXL", "LX", "ELX", "HLX",
    "LIMITED", "LONGITUDE", "TRAILHAWK", "SPORT", "SERIE", "SERIES", "S", "PREMIUM", "PRESTIGE",
    "PLATINUM", "ELITE", "ADVANCE", "ADVANCED", "AUDACE", "IMPETUS", "IMPETUS", "ICONIC",
    "PLUS", "MINI", "PRO", "MAX", "ULTRA", "COMFORT", "COMFORTLINE", "HIGHLINE", "TRENDLINE",
    "EXCLUSIVE", "INTENSE", "FEEL", "SHINE", "LIVE", "TITANIUM", "TREMOR", "RANCH", "WILDTRAK",
    "XDRIVE", "SDRIVE", "QUATTRO", "AWD", "FWD", "RWD", "4X4", "4X2",
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
    def _tokens(cls, valor: Any, *, remover_genericos: bool = True) -> set[str]:
        bruto = cls.normalizar_texto(valor)
        if not bruto:
            return set()
        tokens = {t for t in bruto.split() if t}
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
        # A FIPE usa 32000-x para zero km; na tela a CurVE passa o ano-modelo já resolvido.
        match = re.search(r"(20\d{2}|19\d{2})", texto)
        if not match:
            return None
        ano = int(match.group(1))
        return ano if 2010 <= ano <= 2035 else None

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
    def _detectar_combustivel_consulta(cls, consulta: dict[str, Any]) -> str:
        tipo = cls.normalizar_texto(consulta.get("tipo_veiculo"))
        texto = cls.normalizar_texto(cls._texto_consulta(consulta))
        if tipo == "ELETRICO" or re.search(r"\b(ELETRICO|ELETRICA|BEV|EV|ELECTRIC)\b", texto):
            return "ELETRICO"
        if tipo == "PHEV" or re.search(r"\b(PHEV|PLUG IN|PLUGIN|DM I|DMI|TFSI E|E HYBRID|RECHARGE)\b", texto):
            return "PLUG_IN"
        if "DIESEL" in texto:
            return "DIESEL"
        if re.search(r"\b(FLEX|TOTAL FLEX|BICOMBUSTIVEL|BI COMBUSTIVEL|ETANOL GASOLINA|GASOLINA ETANOL|ALCOOL GASOLINA|GASOLINA ALCOOL)\b", texto):
            return "FLEX"
        if tipo == "HIBRIDO" or re.search(r"\b(HIBRIDO|HIBRIDA|HYBRID|HEV|MHEV)\b", texto):
            return "HIBRIDO"
        if "ETANOL" in texto or "ALCOOL" in texto:
            return "ETANOL"
        if "GASOLINA" in texto:
            return "GASOLINA"
        return ""

    @staticmethod
    def _combustivel_compativel(req: str, cand_comb: str, cand_prop: str) -> tuple[bool, int, str]:
        req = (req or "").upper()
        cand_comb = (cand_comb or "").upper().replace(" ", "_")
        cand_prop = (cand_prop or "").upper().replace(" ", "_")
        if req == "ELETRICO":
            return (cand_prop == "ELETRICO", 24 if cand_prop == "ELETRICO" else -80, "propulsão elétrica compatível" if cand_prop == "ELETRICO" else "propulsão não elétrica")
        if req == "PLUG_IN":
            return (cand_prop == "PLUG_IN", 24 if cand_prop == "PLUG_IN" else -75, "PHEV/plugin compatível" if cand_prop == "PLUG_IN" else "propulsão não plugin")
        if req == "HIBRIDO":
            if cand_prop == "HIBRIDO":
                return True, 22, "híbrido convencional compatível"
            return False, -45, "propulsão não híbrida"
        if req in {"FLEX", "DIESEL", "GASOLINA", "ETANOL"}:
            if cand_comb == req:
                return True, 22, f"combustível {req.lower()} compatível"
            return False, -55, f"combustível diverge: FIPE {req.lower()} x PBEV {cand_comb.lower() or 'vazio'}"
        # Sem combustível explícito: aceita, mas não permite sozinho um match alto.
        return True, 4, "combustível FIPE não explícito"

    @classmethod
    def _version_tokens(cls, texto: Any, modelo_core_tokens: set[str] | None = None) -> set[str]:
        tokens = cls._tokens(texto)
        modelo_core_tokens = modelo_core_tokens or set()
        saida: set[str] = set()
        for token in tokens:
            if token in modelo_core_tokens or token in VERSION_STOP_TOKENS:
                continue
            if re.fullmatch(r"20\d{2}", token):
                continue
            if re.fullmatch(r"[0-9]", token):
                continue
            if token in TRIM_TOKENS_IMPORTANTES or len(token) >= 2:
                saida.add(token)
        return saida

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

        ano_req = self._parse_ano(consulta.get("ano")) or self._parse_ano(consulta.get("texto_ano")) or self._parse_ano(consulta.get("ano_codigo"))
        try:
            ano_cand = int(registro.get("ano_tabela") or 0)
        except Exception:
            ano_cand = 0
        ano_exato = False
        ano_diff = 999
        zero_km_contexto = False
        ano_compativel_fipe_pbev = False
        ano_relacao = "indefinido"
        texto_ano_consulta = self.normalizar_texto(consulta.get("texto_ano") or consulta.get("ano_codigo") or "")
        if "ZERO" in texto_ano_consulta or "32000" in str(consulta.get("ano_codigo") or ""):
            zero_km_contexto = True

        if ano_req and ano_cand:
            diff = abs(ano_req - ano_cand)
            ano_diff = diff
            if diff == 0:
                score += 10
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
                # FIPE trabalha com ano-modelo/zero km antecipado; PBEV usa ano da tabela.
                # O ano não deve bloquear autofill quando a identidade técnica bate forte.
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
        else:
            penalidades.append("ano FIPE ausente para score")

        query_modelo_norm = self.normalizar_texto(" ".join(str(consulta.get(k) or "") for k in ("modelo", "texto_modelo")))
        query_all_norm = self.normalizar_texto(self._texto_consulta(consulta))
        query_model_tokens = self._tokens(query_modelo_norm)
        query_all_tokens = self._tokens(query_all_norm)

        cand_model_norm = self.normalizar_texto(registro.get("modelo_normalizado") or registro.get("modelo"))
        cand_version_norm = self.normalizar_texto(registro.get("versao_normalizada") or registro.get("versao_corrigida") or registro.get("versao"))
        cand_motor_norm = self.normalizar_texto(registro.get("motor_normalizado") or registro.get("motor_corrigido") or registro.get("motor"))
        cand_trans_norm = self.normalizar_texto(registro.get("transmissao_normalizada") or registro.get("transmissao"))
        cand_all_norm = self.normalizar_texto(f"{cand_model_norm} {cand_version_norm} {cand_motor_norm} {cand_trans_norm}")

        cand_model_tokens = self._tokens(cand_model_norm)
        cand_model_core = {t for t in cand_model_tokens if t not in SOFT_BODY_TOKENS}
        if not cand_model_core:
            cand_model_core = set(cand_model_tokens)
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

        # Similaridade textual como apoio, sem substituir tokens técnicos.
        sim = self._ratio(cand_model_norm, query_modelo_norm)
        if sim >= 0.86:
            modelo_score += 4
        elif sim >= 0.74:
            modelo_score += 2

        # CROSS/PICKUP/etc. ausentes costumam indicar família diferente.
        hard_cand = cand_model_tokens & HARD_BODY_TOKENS
        hard_query = query_all_tokens & HARD_BODY_TOKENS
        if hard_cand and not hard_cand.issubset(query_all_tokens):
            score -= 30
            penalidades.append("descritor forte do PBEV ausente na FIPE: " + ", ".join(sorted(hard_cand - query_all_tokens)))
        if hard_query and not hard_query.issubset(set(cand_all_norm.split())):
            score -= 30
            penalidades.append("descritor forte da FIPE ausente no PBEV: " + ", ".join(sorted(hard_query - set(cand_all_norm.split()))))

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

        req_fuel = self._detectar_combustivel_consulta(consulta)
        cand_comb = self.normalizar_texto(registro.get("combustivel_normalizado") or registro.get("combustivel"))
        cand_prop = self.normalizar_texto(registro.get("tipo_propulsao_normalizado") or registro.get("tipo_propulsao"))
        fuel_ok, fuel_score, fuel_motivo = self._combustivel_compativel(req_fuel, cand_comb, cand_prop)
        score += fuel_score
        (motivos if fuel_score >= 0 else penalidades).append(fuel_motivo)

        cand_version_tokens = self._version_tokens(cand_version_norm, cand_model_core)
        query_version_tokens = self._version_tokens(query_all_norm, cand_model_core)
        if cand_version_tokens:
            inter = cand_version_tokens & query_version_tokens
            trim_cand = cand_version_tokens & TRIM_TOKENS_IMPORTANTES
            trim_query = query_version_tokens & TRIM_TOKENS_IMPORTANTES
            if trim_cand:
                ratio_trim = len(trim_cand & trim_query) / max(1, len(trim_cand))
                score += 15 * ratio_trim
                if ratio_trim >= 0.75:
                    motivos.append("versão/acabamento compatível")
                elif trim_query and trim_cand.isdisjoint(trim_query):
                    score -= 12
                    penalidades.append("acabamento divergente")
            else:
                ratio_version = len(inter) / max(1, len(cand_version_tokens))
                score += 8 * ratio_version
        else:
            score += 2

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

        penalidades_tecnicas = [
            p for p in penalidades
            if not p.startswith("ano distante") and p != "ano FIPE ausente para score"
        ]
        identidade_tecnica_forte = (
            fuel_ok
            and ok_flags
            and modelo_score >= 30
            and not penalidades_tecnicas
            and (
                not motor_q or not motor_c or motor_q == motor_c
            )
            and (
                not trans_q or not trans_c or trans_q == trans_c or {trans_q, trans_c} <= {"AUTO", "CVT"}
            )
        )

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
            "req_fuel": req_fuel,
            "ok_flags": ok_flags,
            "bloqueios_flags": bloqueios,
            "identidade_tecnica_forte": identidade_tecnica_forte,
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
            }

        if combustivel == "DIESEL":
            if not gas_cid:
                return None
            return {
                **base,
                "tipo": "diesel",
                "diesel_cidade_km_l": round(gas_cid, 3),
                "diesel_estrada_km_l": round(gas_est, 3) if gas_est else None,
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
            }

        return None

    @staticmethod
    def _candidato_publico(registro: dict[str, Any]) -> dict[str, Any]:
        return {
            "id_pbev": registro.get("id_pbev_preliminar"),
            "ano_tabela": registro.get("ano_tabela"),
            "marca": registro.get("marca"),
            "modelo": registro.get("modelo"),
            "versao": registro.get("versao_corrigida") or registro.get("versao"),
            "motor": registro.get("motor_corrigido") or registro.get("motor"),
            "transmissao": registro.get("transmissao"),
            "combustivel": registro.get("combustivel"),
            "tipo_propulsao": registro.get("tipo_propulsao"),
            "categoria": registro.get("categoria"),
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
        modelo_core = {t for t in modelo_tokens if t not in SOFT_BODY_TOKENS}
        if not modelo_core:
            modelo_core = modelo_tokens
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

        Candidatos de anos diferentes com a mesma assinatura técnica não devem bloquear
        autofill: neste caso o sistema usa o registro PBEV mais recente/mais próximo.
        Candidatos com consumo idêntico também não bloqueiam, pois o valor aplicado ao TCO
        seria o mesmo.
        """
        if not proximos:
            return False
        top_sig = self._assinatura_tecnica_registro(top.get("registro") or {})
        top_sug = self._assinatura_sugestao(top.get("sugestao"))
        for cand in proximos:
            cand_sig = self._assinatura_tecnica_registro(cand.get("registro") or {})
            if cand_sig == top_sig:
                continue
            if top_sug and self._assinatura_sugestao(cand.get("sugestao")) == top_sug:
                continue
            return True
        return False

    # ------------------------------------------------------------------
    # API principal
    # ------------------------------------------------------------------
    def sugerir_consumo(self, consulta: dict[str, Any]) -> dict[str, Any]:
        try:
            cache = self.carregar_base_pbev()
        except Exception as exc:
            return {
                "encontrou": False,
                "nivel_match": "sem_match",
                "score": 0,
                "motivo": f"Base PBEV indisponível: {exc}",
                "autopreencher": False,
                "origem": "Inmetro/PBEV",
                "sugestoes_consumo": {},
                "candidato": None,
                "flags": {},
            }

        marca_key = self._marca_key(consulta.get("marca"))
        if not marca_key:
            return {
                "encontrou": False,
                "nivel_match": "sem_match",
                "score": 0,
                "motivo": "Marca FIPE ausente para busca PBEV.",
                "autopreencher": False,
                "origem": "Inmetro/PBEV",
                "sugestoes_consumo": {},
                "candidato": None,
                "flags": {},
            }

        registros_marca = cache.indice_marca.get(marca_key, [])
        candidatos: list[dict[str, Any]] = []
        candidatos_bloqueados = 0

        for registro in registros_marca:
            avaliacao = self.calcular_score_match(registro, consulta)
            if avaliacao["score"] < 35 and not avaliacao.get("bloqueios_flags"):
                continue
            sugestao = self.montar_sugestao_consumo(registro)
            if not sugestao:
                continue
            item = {
                "registro": registro,
                "score": float(avaliacao.get("score_bruto", avaliacao["score"])),
                "score_publico": float(avaliacao["score"]),
                "avaliacao": avaliacao,
                "sugestao": sugestao,
            }
            if not avaliacao.get("ok_flags"):
                candidatos_bloqueados += 1
            candidatos.append(item)

        def _ordem_candidato(c: dict[str, Any]) -> tuple[float, int, int, float, int]:
            avaliacao = c.get("avaliacao") or {}
            return (
                float(c.get("score") or 0),
                1 if avaliacao.get("ano_exato") else 0,
                -int(avaliacao.get("ano_diff") if avaliacao.get("ano_diff") is not None else 999),
                float(avaliacao.get("modelo_score") or 0),
                1 if avaliacao.get("fuel_ok") else 0,
            )

        candidatos.sort(key=_ordem_candidato, reverse=True)
        utilizaveis = [c for c in candidatos if c["avaliacao"].get("ok_flags")]

        if not utilizaveis:
            motivo = "Nenhum candidato PBEV confiável encontrado."
            if candidatos_bloqueados:
                motivo += f" {candidatos_bloqueados} candidato(s) foram bloqueados por status/flags."
            return {
                "encontrou": False,
                "nivel_match": "sem_match",
                "score": 0,
                "motivo": motivo,
                "autopreencher": False,
                "origem": "Inmetro/PBEV",
                "sugestoes_consumo": {},
                "candidato": None,
                "flags": {},
                "diagnostico": {"candidatos_bloqueados": candidatos_bloqueados, "total_candidatos_marca": len(registros_marca)},
            }

        top = utilizaveis[0]
        segundo_score = utilizaveis[1]["score"] if len(utilizaveis) > 1 else None
        diferenca = top["score"] - segundo_score if segundo_score is not None else None
        avaliacao_top = top["avaliacao"]
        candidatos_proximos = [c for c in utilizaveis[1:] if top["score"] - c["score"] < 8]
        dominante = segundo_score is None or (diferenca is not None and diferenca >= 8)
        ambiguidade_proxima = self._candidatos_proximos_bloqueiam_autofill(top, candidatos_proximos)

        if not dominante and avaliacao_top.get("ano_exato"):
            proximos_mesmo_ano = [c for c in candidatos_proximos if (c.get("avaliacao") or {}).get("ano_exato")]
            if not proximos_mesmo_ano:
                # Ano exato desempata candidatos equivalentes de anos adjacentes.
                dominante = True
            elif not ambiguidade_proxima:
                # Candidatos próximos têm a mesma assinatura técnica ou o mesmo consumo.
                dominante = True

        if (
            not dominante
            and avaliacao_top.get("identidade_tecnica_forte")
            and avaliacao_top.get("ano_compativel_fipe_pbev")
            and not ambiguidade_proxima
        ):
            # FIPE usa ano-modelo/zero km; PBEV usa ano da tabela.
            # Se a identidade técnica é a mesma, anos próximos/anteriores não bloqueiam.
            dominante = True

        score_top = float(top["score"])
        score_publico_top = float(top.get("score_publico", min(100.0, score_top)))
        high_conditions = (
            score_top >= 95
            and avaliacao_top.get("fuel_ok")
            and avaliacao_top.get("ano_compativel_fipe_pbev")
            and avaliacao_top.get("identidade_tecnica_forte")
            and float(avaliacao_top.get("modelo_score") or 0) >= 30
            and dominante
        )

        if high_conditions:
            nivel = "alto"
            autopreencher = True
        elif score_top >= 70:
            nivel = "medio"
            autopreencher = False
        elif score_top >= 50:
            nivel = "baixo"
            autopreencher = False
        else:
            nivel = "sem_match"
            autopreencher = False

        # O score bruto pode passar de 100 por acumular evidências técnicas,
        # mas o score exibido deve acompanhar o nível operacional de confiança.
        score_exibido = score_publico_top
        if nivel == "medio":
            score_exibido = min(score_exibido, 89.0)
        elif nivel == "baixo":
            score_exibido = min(score_exibido, 69.0)
        elif nivel == "sem_match":
            score_exibido = 0.0

        motivos = list(avaliacao_top.get("motivos") or [])
        penalidades = list(avaliacao_top.get("penalidades") or [])
        if not dominante:
            penalidades.append("há outro candidato PBEV próximo tecnicamente ambíguo; autofill bloqueado")
        if nivel != "alto" and not penalidades:
            penalidades.append("score insuficiente para autofill automático")

        # O score público acompanha a decisão operacional. Assim, um candidato bom,
        # mas bloqueado por ano/dominância, não aparece como “100” em match médio.
        score_retorno = score_publico_top
        if nivel == "medio":
            score_retorno = min(score_retorno, 89.0)
        elif nivel == "baixo":
            score_retorno = min(score_retorno, 69.0)
        elif nivel == "sem_match":
            score_retorno = 0.0

        motivo_txt = "; ".join(motivos + penalidades) or "Matching PBEV avaliado."
        return {
            "encontrou": nivel != "sem_match",
            "nivel_match": nivel,
            "score": round(score_retorno, 2),
            "score_bruto": round(score_top, 2),
            "motivo": motivo_txt,
            "autopreencher": autopreencher,
            "origem": "Inmetro/PBEV",
            "ano_tabela_pbev": top["registro"].get("ano_tabela"),
            "candidato": self._candidato_publico(top["registro"]),
            "sugestoes_consumo": top["sugestao"],
            "flags": self._flags_publicas(top["registro"]),
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
                "ambiguidade_proxima": bool(ambiguidade_proxima),
                "modelo_score": avaliacao_top.get("modelo_score"),
                "combustivel_detectado_fipe": avaliacao_top.get("req_fuel"),
            },
            "valor_autopreenchido": autopreencher,
        }
