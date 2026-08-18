from __future__ import annotations

import csv
import math
import re
import sqlite3
import statistics
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from services.seguro_autoseg_service import estimar_seguro_autoseg_referencia

BASE_DIR = Path(__file__).resolve().parents[1]
ARQUIVO_AUTOSEG_V2 = BASE_DIR / "data" / "seguro" / "seguro_autoseg_2021A_curve_compact.sqlite"
ARQUIVO_IPSA_V2 = BASE_DIR / "data" / "seguro" / "ipsa_v2_referencias.csv"

FONTE_V2 = "IPSA/TEx + AUTOSEG/SUSEP"
DATA_BASE_V2 = "IPSA: maio de 2026; AUTOSEG: 2021A"
METODO_V2 = "ipsa_mediana_atual_fatores_autoseg_credibilidade_v2"
ANO_FONTE_AUTOSEG = 2021
COBERTURA_V2 = "Automóvel/CASCO — estimativa estatística de referência"

PESOS_MODELO = {"ALTA": 0.75, "MEDIA": 0.50, "REFERENCIA": 0.25, "BAIXA": 0.0}
PESOS_REGIAO = {"ALTA": 0.60, "MEDIA": 0.40, "REFERENCIA": 0.20, "BAIXA": 0.0}
PESOS_CIDADE = {"ALTA": 0.50, "MEDIA": 0.35, "REFERENCIA": 0.20, "BAIXA": 0.0}

# Suaviza somente a vizinhança dos cortes artificiais das faixas FIPE do IPSA.
# Não cria uma taxa nova de mercado: interpola linearmente entre os dois
# percentuais publicados em uma janela de ±5% do limiar.
IPSA_TRANSICAO_VALOR_PCT = 0.05
IPSA_LIMITES_VALOR = (
    (50_000.0, "31_50", "51_80"),
    (80_000.0, "51_80", "81_150"),
    (150_000.0, "81_150", "151_mais"),
)

IPSA_METRO_POR_CIDADE = {
    "SALVADOR": "salvador",
    "RECIFE": "recife",
    "BELEM": "belem",
    "BELO HORIZONTE": "belo_horizonte",
    "PORTO ALEGRE": "porto_alegre",
    "RIO DE JANEIRO": "rio_de_janeiro",
    "FORTALEZA": "fortaleza",
    "CURITIBA": "curitiba",
    "SAO PAULO": "sao_paulo",
}


@dataclass(frozen=True)
class ReferenciaIpsa:
    dimensao: str
    chave: str
    taxa_percentual: float
    periodo: str
    recorte: str


@dataclass(frozen=True)
class FatorAutoseg:
    origem: str
    fator_bruto: float
    fator_aplicado: float
    exposicao: float
    classe: str
    ano_base: int | None
    diferenca_anos: int | None
    idade_fonte: int | None = None
    codigo_categoria: str = ""
    codigo_regiao: str = ""
    regiao_descricao: str = ""
    cidade: str = ""


def _texto_sem_acento(valor: Any) -> str:
    texto = unicodedata.normalize("NFKD", str(valor or ""))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return texto.upper().strip()


def _normalizar_cidade(valor: Any) -> str:
    texto = _texto_sem_acento(valor)
    texto = re.sub(r"\([^)]*\)", " ", texto)
    texto = re.sub(r"[^A-Z0-9]+", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


def normalizar_codigo_fipe(valor: Any) -> str:
    digitos = re.sub(r"\D", "", str(valor or ""))
    if len(digitos) == 7:
        return f"{digitos[:6]}-{digitos[6]}"
    texto = str(valor or "").strip().upper()
    return texto if re.fullmatch(r"\d{6}-\d", texto) else ""


def normalizar_tecnologia_v2(valor: Any) -> str:
    bruto = _texto_sem_acento(valor).lower()
    aliases = {
        "bev": "eletrico", "ev": "eletrico", "eletrico": "eletrico",
        "phev": "hibrido", "hev": "hibrido", "mhev": "hibrido", "hibrido": "hibrido",
        "diesel": "diesel", "gasolina": "gasolina", "flex": "gasolina", "etanol": "gasolina",
        "combustao": "gasolina", "icev": "gasolina",
    }
    return aliases.get(bruto, bruto or "gasolina")


def _ano_modelo_info(valor: Any) -> tuple[int | None, bool]:
    texto = _texto_sem_acento(valor)
    zero_km = "ZERO" in texto or texto in {"0 KM", "0KM", "32000"}
    anos = [int(x) for x in re.findall(r"\b(19\d{2}|20\d{2})\b", texto)]
    ano = anos[0] if anos else None
    if zero_km and ano is None:
        ano = datetime.now().year
    return ano, zero_km


@lru_cache(maxsize=1)
def carregar_ipsa_v2() -> tuple[ReferenciaIpsa, ...]:
    if not ARQUIVO_IPSA_V2.exists():
        raise RuntimeError(f"Base IPSA V2 não encontrada: {ARQUIVO_IPSA_V2}")
    refs: list[ReferenciaIpsa] = []
    with ARQUIVO_IPSA_V2.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                taxa = float(row.get("taxa_percentual") or 0)
            except (TypeError, ValueError):
                continue
            if taxa <= 0:
                continue
            refs.append(ReferenciaIpsa(
                dimensao=str(row.get("dimensao") or "").strip(),
                chave=str(row.get("chave") or "").strip(),
                taxa_percentual=taxa,
                periodo=str(row.get("periodo") or "").strip(),
                recorte=str(row.get("recorte") or "").strip(),
            ))
    if not refs:
        raise RuntimeError("Base IPSA V2 vazia.")
    return tuple(refs)


def _ref_ipsa(dimensao: str, chave: str) -> ReferenciaIpsa | None:
    for ref in carregar_ipsa_v2():
        if ref.dimensao == dimensao and ref.chave == chave:
            return ref
    return None


def _referencia_regiao_ipsa(municipio: Any) -> ReferenciaIpsa | None:
    chave = IPSA_METRO_POR_CIDADE.get(_normalizar_cidade(municipio))
    return _ref_ipsa("regiao_metro", chave) if chave else None


def _referencia_valor_fipe(valor: float) -> ReferenciaIpsa | None:
    """Retorna a referência de valor FIPE com transição contínua nos cortes.

    O IPSA publica faixas discretas. Para evitar que R$ 1 de diferença no valor
    do carro cause um salto artificial relevante na estimativa, a CurVE mistura
    apenas as faixas adjacentes dentro de ±5% de cada limiar. Fora dessas
    janelas, preserva exatamente a taxa publicada da faixa correspondente.
    """
    valor = max(0.0, float(valor or 0.0))
    if valor < 31_000:
        return None

    for limite, chave_esq, chave_dir in IPSA_LIMITES_VALOR:
        largura = limite * IPSA_TRANSICAO_VALOR_PCT
        inicio, fim = limite - largura, limite + largura
        if inicio <= valor <= fim:
            esq = _ref_ipsa("valor_fipe", chave_esq)
            dire = _ref_ipsa("valor_fipe", chave_dir)
            if esq and dire:
                alpha = (valor - inicio) / (fim - inicio)
                taxa = esq.taxa_percentual + (dire.taxa_percentual - esq.taxa_percentual) * alpha
                return ReferenciaIpsa(
                    dimensao="valor_fipe",
                    chave=f"transicao_{chave_esq}_{chave_dir}",
                    taxa_percentual=taxa,
                    periodo=esq.periodo or dire.periodo,
                    recorte=f"transição contínua entre as faixas {esq.recorte} e {dire.recorte}",
                )

    if valor <= 50_000:
        chave = "31_50"
    elif valor <= 80_000:
        chave = "51_80"
    elif valor <= 150_000:
        chave = "81_150"
    else:
        chave = "151_mais"
    return _ref_ipsa("valor_fipe", chave)


def referencias_ipsa_aplicaveis(*, valor_fipe: float, ano_modelo: Any, tecnologia: Any, ano_referencia: int | None = None) -> tuple[list[ReferenciaIpsa], dict[str, Any]]:
    valor = max(0.0, float(valor_fipe or 0.0))
    ano, zero_km = _ano_modelo_info(ano_modelo)
    ano_atual = int(ano_referencia or datetime.now().year)
    idade = None if ano is None else max(0, ano_atual - ano)
    refs: list[ReferenciaIpsa] = []

    if zero_km:
        ref = _ref_ipsa("idade", "zero_km")
        if ref: refs.append(ref)
    elif idade is not None:
        chave_idade = "0_2" if idade <= 2 else "3_5" if idade <= 5 else "6_10" if idade <= 10 else ""
        ref = _ref_ipsa("idade", chave_idade) if chave_idade else None
        if ref: refs.append(ref)

    ref = _referencia_valor_fipe(valor)
    if ref:
        refs.append(ref)

    # O comparativo por propulsão do IPSA é restrito a veículos com até 2 anos.
    if zero_km or (idade is not None and idade <= 2):
        tec = normalizar_tecnologia_v2(tecnologia)
        ref = _ref_ipsa("tecnologia", tec)
        if ref: refs.append(ref)

    # Acima de 10 anos o relatório detalhado não publica uma faixa etária
    # específica. Em vez de voltar para a tabela regional antiga, preserva-se
    # somente o que continua diretamente sustentado pelo IPSA atual: mercado
    # geral + faixa de valor FIPE. A confiança final é rebaixada para Referência.
    if idade is not None and idade > 10:
        geral = _ref_ipsa("mercado", "geral")
        if geral and all(r.dimensao != "mercado" for r in refs):
            refs.append(geral)

    if not refs:
        geral = _ref_ipsa("mercado", "geral")
        if geral: refs.append(geral)

    return refs, {"ano_modelo": ano, "zero_km": zero_km, "idade": idade}


def _conexao_autoseg() -> sqlite3.Connection:
    if not ARQUIVO_AUTOSEG_V2.exists():
        raise RuntimeError(f"Base AUTOSEG V2 não encontrada: {ARQUIVO_AUTOSEG_V2}")
    uri = f"file:{ARQUIVO_AUTOSEG_V2.as_posix()}?mode=ro"
    con = sqlite3.connect(uri, uri=True, timeout=2.0)
    con.row_factory = sqlite3.Row
    return con


@lru_cache(maxsize=1)
def _catalogo_regioes() -> dict[str, str]:
    with _conexao_autoseg() as con:
        return {str(r["codigo_regiao"]): str(r["descricao_regiao"] or "") for r in con.execute(
            "SELECT codigo_regiao, descricao_regiao FROM regiao_catalogo"
        )}


@lru_cache(maxsize=1)
def _mapa_cidade_regiao() -> dict[str, tuple[tuple[str, str], ...]]:
    regioes = _catalogo_regioes()
    mapa: dict[str, set[tuple[str, str]]] = {}
    with _conexao_autoseg() as con:
        for r in con.execute("SELECT DISTINCT cidade_nome, codigo_regiao FROM modelo_cidade WHERE cidade_nome IS NOT NULL"):
            nome = _normalizar_cidade(r["cidade_nome"])
            if not nome:
                continue
            codigo = str(r["codigo_regiao"] or "")
            mapa.setdefault(nome, set()).add((codigo, regioes.get(codigo, "")))
    return {k: tuple(sorted(v)) for k, v in mapa.items()}


def _regioes_para_localizacao(uf: str, municipio: str) -> list[tuple[str, str, str]]:
    uf_norm = _texto_sem_acento(uf)
    cidade_norm = _normalizar_cidade(municipio)
    regioes = _catalogo_regioes()
    saida: list[tuple[str, str, str]] = []

    if cidade_norm:
        candidatos = _mapa_cidade_regiao().get(cidade_norm, ())
        for codigo, desc in candidatos:
            if not uf_norm or _texto_sem_acento(desc).startswith(f"{uf_norm} ") or _texto_sem_acento(desc).startswith(f"{uf_norm}-"):
                saida.append((codigo, desc, cidade_norm))
        if saida:
            return saida

    for codigo, desc in regioes.items():
        d = _texto_sem_acento(desc)
        if uf_norm and (d.startswith(f"{uf_norm} ") or d.startswith(f"{uf_norm}-")):
            saida.append((codigo, desc, cidade_norm))
    return sorted(saida)


def _peso_recencia(ano_base: int | None, ano_alvo: int | None) -> tuple[float, int | None]:
    if ano_base is None or ano_alvo is None:
        return 0.65, None
    delta = abs(int(ano_alvo) - int(ano_base))
    return max(0.35, 1.0 - 0.08 * delta), delta


def _peso_fonte_autoseg(ano_referencia: int | None) -> tuple[float, int | None]:
    if ano_referencia is None:
        return 0.60, None
    idade_fonte = max(0, int(ano_referencia) - ANO_FONTE_AUTOSEG)
    return max(0.35, 1.0 - 0.08 * idade_fonte), idade_fonte


def _recencia_combinada(ano_base: int | None, ano_alvo: int | None, ano_referencia: int | None) -> tuple[float, int | None, int | None]:
    peso_modelo, delta_modelo = _peso_recencia(ano_base, ano_alvo)
    peso_fonte, idade_fonte = _peso_fonte_autoseg(ano_referencia)
    return min(peso_modelo, peso_fonte), delta_modelo, idade_fonte


def _shrink_fator(fator: float, classe: str, pesos: dict[str, float], recencia: float, minimo: float, maximo: float) -> float:
    fator = max(minimo, min(maximo, float(fator or 1.0)))
    peso = max(0.0, min(1.0, float(pesos.get(str(classe or "").upper(), 0.0)) * recencia))
    if peso <= 0:
        return 1.0
    return math.exp(math.log(fator) * peso)


def _escolher_linha_por_ano(rows: Iterable[sqlite3.Row], ano_alvo: int | None) -> sqlite3.Row | None:
    rows = list(rows)
    if not rows:
        return None
    def chave(r: sqlite3.Row):
        ano = int(r["ano_modelo"] or 0)
        delta = abs(ano - ano_alvo) if ano_alvo else 9999
        return (delta, -float(r["exposicao"] or 0.0))
    return min(rows, key=chave)


def _fatores_autoseg(
    *, codigo_fipe: str, ano_alvo: int | None, ano_referencia: int | None, uf: str, municipio: str
) -> tuple[FatorAutoseg | None, FatorAutoseg | None, FatorAutoseg | None, dict[str, Any]]:
    """Resolve fatores históricos de modelo, região e cidade sem usar 2021 como preço atual.

    Decomposição aplicada ao IPSA contemporâneo:
      - modelo: veículo (ou grupo) versus categoria comparável;
      - região: categoria naquela região versus a mesma categoria no Brasil;
      - cidade: prêmio médio do modelo/cidade versus modelo/região.

    Todos os fatores são reduzidos em direção a 1 conforme exposição e distância
    temporal, para evitar que células históricas pequenas dominem a estimativa.
    """
    codigo = normalizar_codigo_fipe(codigo_fipe)
    if not codigo:
        return None, None, None, {"codigo_fipe_encontrado": False}

    regioes = _regioes_para_localizacao(uf, municipio)
    codigos_regiao = [r[0] for r in regioes]
    regioes_dict = {r[0]: r[1] for r in regioes}
    cidade_norm = _normalizar_cidade(municipio)

    with _conexao_autoseg() as con:
        # 1) Modelo exato + região, priorizando ano mais próximo e, em empate,
        # a categoria com maior exposição. Isso elimina categorias residuais.
        rows = []
        if codigos_regiao:
            placeholders = ",".join("?" for _ in codigos_regiao)
            rows = con.execute(
                f"SELECT * FROM modelo_regiao WHERE codigo_fipe=? AND codigo_regiao IN ({placeholders})",
                (codigo, *codigos_regiao),
            ).fetchall()
        linha_modelo = _escolher_linha_por_ano(rows, ano_alvo)

        # Fallback nacional específico do modelo.
        origem_modelo = "modelo_regiao"
        if linha_modelo is None:
            rows_nat = con.execute("SELECT * FROM modelo_nacional WHERE codigo_fipe=?", (codigo,)).fetchall()
            linha_modelo = _escolher_linha_por_ano(rows_nat, ano_alvo)
            origem_modelo = "modelo_nacional"

        # Fallback por grupo/marca histórica somente quando o código existe no
        # catálogo AUTOSEG, mas não atingiu exposição mínima no nível de modelo.
        linha_grupo = None
        if linha_modelo is None and codigos_regiao:
            cat_modelo = con.execute(
                "SELECT codigo_grupo FROM modelo_catalogo WHERE codigo_fipe=? LIMIT 1", (codigo,)
            ).fetchone()
            codigo_grupo = str(cat_modelo[0] or "") if cat_modelo else ""
            if codigo_grupo:
                placeholders = ",".join("?" for _ in codigos_regiao)
                rows_grupo = con.execute(
                    f"SELECT * FROM grupo_regiao WHERE codigo_grupo=? AND codigo_regiao IN ({placeholders})",
                    (codigo_grupo, *codigos_regiao),
                ).fetchall()
                linha_grupo = _escolher_linha_por_ano(rows_grupo, ano_alvo)
                if linha_grupo is not None:
                    linha_modelo = linha_grupo
                    origem_modelo = "grupo_regiao"

        fator_modelo = None
        if linha_modelo is not None:
            classe = str(linha_modelo["classe_exposicao"] or "REFERENCIA").upper()
            ano_base = int(linha_modelo["ano_modelo"] or 0) or None
            rec, delta, idade_fonte = _recencia_combinada(ano_base, ano_alvo, ano_referencia)
            codigo_categoria = str(linha_modelo["codigo_categoria"] or "")
            codigo_regiao = str(linha_modelo["codigo_regiao"] or "") if origem_modelo != "modelo_nacional" else ""

            if origem_modelo in {"modelo_regiao", "modelo_nacional"}:
                bruto = float(linha_modelo["fator_modelo_vs_categoria"] or 1.0)
            else:
                # grupo_regiao não armazena fator pronto; calcula contra a
                # categoria/região equivalente no mesmo ano-modelo.
                cat_ref = con.execute(
                    "SELECT * FROM categoria_regiao WHERE codigo_categoria=? AND codigo_regiao=? AND ano_modelo=? LIMIT 1",
                    (codigo_categoria, codigo_regiao, ano_base),
                ).fetchone()
                taxa_grupo = float(linha_modelo["taxa_premio_is"] or 0.0)
                taxa_cat = float(cat_ref["taxa_premio_is"] or 0.0) if cat_ref else 0.0
                bruto = (taxa_grupo / taxa_cat) if taxa_grupo > 0 and taxa_cat > 0 else 1.0

            aplicado = _shrink_fator(bruto, classe, PESOS_MODELO, rec, 0.55, 1.80)
            fator_modelo = FatorAutoseg(
                origem=origem_modelo,
                fator_bruto=bruto,
                fator_aplicado=aplicado,
                exposicao=float(linha_modelo["exposicao"] or 0.0),
                classe=classe,
                ano_base=ano_base,
                diferenca_anos=delta,
                idade_fonte=idade_fonte,
                codigo_categoria=codigo_categoria,
                codigo_regiao=codigo_regiao,
                regiao_descricao=regioes_dict.get(codigo_regiao, ""),
            )

        # 2) Fator regional da categoria: região versus Brasil. Este componente
        # é necessário porque "modelo vs categoria na região" sozinho não carrega
        # o nível de risco geográfico para o IPSA nacional.
        fator_regiao = None
        if fator_modelo and fator_modelo.codigo_categoria and codigos_regiao:
            regioes_alvo = [fator_modelo.codigo_regiao] if fator_modelo.codigo_regiao else codigos_regiao
            regioes_alvo = [x for x in regioes_alvo if x]
            if regioes_alvo:
                placeholders = ",".join("?" for _ in regioes_alvo)
                rows_cat_reg = con.execute(
                    f"SELECT * FROM categoria_regiao WHERE codigo_categoria=? AND codigo_regiao IN ({placeholders})",
                    (fator_modelo.codigo_categoria, *regioes_alvo),
                ).fetchall()
                linha_cat_reg = _escolher_linha_por_ano(rows_cat_reg, ano_alvo)
                if linha_cat_reg is not None:
                    ano_reg = int(linha_cat_reg["ano_modelo"] or 0) or None
                    rows_cat_nat = con.execute(
                        "SELECT * FROM categoria_nacional WHERE codigo_categoria=?",
                        (fator_modelo.codigo_categoria,),
                    ).fetchall()
                    linha_cat_nat = _escolher_linha_por_ano(rows_cat_nat, ano_reg or ano_alvo)
                    taxa_reg = float(linha_cat_reg["taxa_premio_is"] or 0.0)
                    taxa_nat = float(linha_cat_nat["taxa_premio_is"] or 0.0) if linha_cat_nat else 0.0
                    if taxa_reg > 0 and taxa_nat > 0:
                        classe = str(linha_cat_reg["classe_exposicao"] or "REFERENCIA").upper()
                        rec, delta, idade_fonte = _recencia_combinada(ano_reg, ano_alvo, ano_referencia)
                        bruto = taxa_reg / taxa_nat
                        aplicado = _shrink_fator(bruto, classe, PESOS_REGIAO, rec, 0.70, 1.40)
                        codigo_reg = str(linha_cat_reg["codigo_regiao"] or "")
                        fator_regiao = FatorAutoseg(
                            origem="categoria_regiao",
                            fator_bruto=bruto,
                            fator_aplicado=aplicado,
                            exposicao=float(linha_cat_reg["exposicao"] or 0.0),
                            classe=classe,
                            ano_base=ano_reg,
                            diferenca_anos=delta,
                            idade_fonte=idade_fonte,
                            codigo_categoria=fator_modelo.codigo_categoria,
                            codigo_regiao=codigo_reg,
                            regiao_descricao=regioes_dict.get(codigo_reg, ""),
                        )

        # 3) Ajuste municipal do mesmo modelo/categoria/região. Não usamos a
        # tabela municipal para taxa absoluta porque ela não possui IS média.
        fator_cidade = None
        if (
            fator_modelo
            and fator_modelo.origem == "modelo_regiao"
            and fator_modelo.codigo_regiao
            and cidade_norm
        ):
            rows_city = con.execute(
                "SELECT * FROM modelo_cidade WHERE codigo_fipe=? AND codigo_regiao=? AND codigo_categoria=?",
                (codigo, fator_modelo.codigo_regiao, fator_modelo.codigo_categoria),
            ).fetchall()
            rows_city = [r for r in rows_city if _normalizar_cidade(r["cidade_nome"]) == cidade_norm]
            linha_city = _escolher_linha_por_ano(rows_city, ano_alvo)
            if linha_city is not None:
                classe = str(linha_city["classe_exposicao"] or "REFERENCIA").upper()
                ano_base = int(linha_city["ano_modelo"] or 0) or None
                rec, delta, idade_fonte = _recencia_combinada(ano_base, ano_alvo, ano_referencia)
                bruto = float(linha_city["fator_cidade_vs_regiao"] or 1.0)
                aplicado = _shrink_fator(bruto, classe, PESOS_CIDADE, rec, 0.80, 1.25)
                fator_cidade = FatorAutoseg(
                    origem="modelo_cidade",
                    fator_bruto=bruto,
                    fator_aplicado=aplicado,
                    exposicao=float(linha_city["exposicao"] or 0.0),
                    classe=classe,
                    ano_base=ano_base,
                    diferenca_anos=delta,
                    idade_fonte=idade_fonte,
                    codigo_categoria=str(linha_city["codigo_categoria"] or ""),
                    codigo_regiao=str(linha_city["codigo_regiao"] or ""),
                    regiao_descricao=regioes_dict.get(str(linha_city["codigo_regiao"] or ""), ""),
                    cidade=str(linha_city["cidade_nome"] or ""),
                )

        return fator_modelo, fator_regiao, fator_cidade, {
            "codigo_fipe_encontrado": linha_modelo is not None and origem_modelo != "grupo_regiao",
            "grupo_historico_usado": origem_modelo == "grupo_regiao",
            "regioes_candidatas": [r[1] for r in regioes],
            "cidade_normalizada": cidade_norm,
        }

def _confianca_v2(
    fator_modelo: FatorAutoseg | None,
    fator_regiao: FatorAutoseg | None,
    fator_cidade: FatorAutoseg | None,
    municipio: str = "",
) -> str:
    if fator_modelo is None:
        return "referencia"
    if fator_modelo.origem == "grupo_regiao":
        return "referencia"

    delta_modelo = fator_modelo.diferenca_anos if fator_modelo.diferenca_anos is not None else 99
    delta_regiao = fator_regiao.diferenca_anos if fator_regiao and fator_regiao.diferenca_anos is not None else 99
    delta_cidade = fator_cidade.diferenca_anos if fator_cidade and fator_cidade.diferenca_anos is not None else 99
    cidade_pedida = bool(_normalizar_cidade(municipio))

    modelo_forte = fator_modelo.classe == "ALTA" and delta_modelo <= 2
    regiao_forte = fator_regiao is not None and fator_regiao.classe in {"ALTA", "MEDIA"} and delta_regiao <= 2
    cidade_ok = (
        not cidade_pedida
        or (fator_cidade is not None and fator_cidade.classe in {"ALTA", "MEDIA"} and delta_cidade <= 2)
    )
    idade_fonte = fator_modelo.idade_fonte if fator_modelo.idade_fonte is not None else 99
    if modelo_forte and regiao_forte and cidade_ok and idade_fonte <= 2:
        return "alta"
    # Com AUTOSEG 2021A, a evidência específica é histórica. Mesmo com alta
    # exposição, a confiança final é limitada a Média até existir fonte atual
    # por código FIPE/modelo.
    if fator_modelo.classe in {"ALTA", "MEDIA"} and delta_modelo <= 5 and idade_fonte <= 8:
        return "media"
    return "referencia"

def status_seguro_v2() -> dict[str, Any]:
    refs = carregar_ipsa_v2()
    if not ARQUIVO_AUTOSEG_V2.exists():
        return {"configured": True, "autoseg": False, "ipsa_referencias": len(refs), "schema": ""}
    try:
        with _conexao_autoseg() as con:
            row = con.execute("SELECT valor FROM metadata WHERE chave='schema_version'").fetchone()
            total_modelos = int(con.execute("SELECT COUNT(*) FROM modelo_catalogo").fetchone()[0])
        return {
            "configured": True,
            "autoseg": True,
            "ipsa_referencias": len(refs),
            "schema": str(row[0] if row else ""),
            "modelos_autoseg": total_modelos,
        }
    except sqlite3.Error as exc:
        return {"configured": True, "autoseg": False, "ipsa_referencias": len(refs), "schema": "", "error": str(exc)}


def estimar_seguro_v2(
    *,
    valor_fipe: float,
    uf: str,
    municipio: str = "",
    ano_modelo: Any = None,
    tecnologia: Any = "gasolina",
    codigo_fipe: Any = "",
    ano_referencia: int | None = None,
) -> dict[str, Any]:
    """Seguro V2: IPSA contemporâneo + fatores AUTOSEG históricos com credibilidade.

    O IPSA fornece o nível atual do mercado. O AUTOSEG/SUSEP não é utilizado como
    preço de 2026: fornece somente fatores relativos do modelo e da localização,
    reduzidos em direção a 1 conforme exposição e distância temporal.
    """
    valor = max(0.0, float(valor_fipe or 0.0))
    if valor <= 0:
        raise ValueError("Valor FIPE inválido para estimativa de seguro.")

    try:
        refs, info_ano = referencias_ipsa_aplicaveis(
            valor_fipe=valor, ano_modelo=ano_modelo, tecnologia=tecnologia, ano_referencia=ano_referencia
        )
    except RuntimeError:
        # Fallback técnico legado somente se a base IPSA V2 não estiver disponível.
        legado = estimar_seguro_autoseg_referencia(
            valor_fipe=valor, uf=uf, ano_modelo=ano_modelo, tecnologia=tecnologia
        ).to_dict()
        legado.update({"confianca": "fallback", "versao_estimador": "v1_fallback"})
        return legado

    taxas = [r.taxa_percentual for r in refs]
    taxa_ipsa_percent = statistics.median(taxas)
    taxa_ipsa = taxa_ipsa_percent / 100.0

    ref_regiao_ipsa = _referencia_regiao_ipsa(municipio)
    ref_mercado_ipsa = _ref_ipsa("mercado", "geral")
    fator_regiao_ipsa = 1.0
    if ref_regiao_ipsa and ref_mercado_ipsa and ref_mercado_ipsa.taxa_percentual > 0:
        fator_regiao_ipsa = ref_regiao_ipsa.taxa_percentual / ref_mercado_ipsa.taxa_percentual

    # Para veículos acima de 10 anos, referências_ipsa_aplicaveis() usa
    # mercado geral + valor FIPE, sem extrapolar uma faixa etária inexistente.
    # O AUTOSEG continua apenas como fator histórico reduzido por credibilidade.

    fator_modelo = fator_regiao = fator_cidade = None
    autoseg_meta: dict[str, Any] = {"codigo_fipe_encontrado": False}
    try:
        fator_modelo, fator_regiao, fator_cidade, autoseg_meta = _fatores_autoseg(
            codigo_fipe=str(codigo_fipe or ""),
            ano_alvo=info_ano.get("ano_modelo"),
            ano_referencia=int(ano_referencia or datetime.now().year),
            uf=str(uf or "").upper(),
            municipio=str(municipio or ""),
        )
    except (RuntimeError, sqlite3.Error):
        # A estimativa IPSA continua funcional mesmo se o arquivo histórico estiver ausente/corrompido.
        fator_modelo = fator_regiao = fator_cidade = None

    ajuste_modelo = fator_modelo.fator_aplicado if fator_modelo else 1.0
    if ref_regiao_ipsa:
        # O recorte regional atual do IPSA substitui os ajustes geográficos
        # históricos para evitar dupla contagem. O fator específico do modelo
        # AUTOSEG continua válido como efeito relativo dentro da categoria.
        ajuste_regiao = fator_regiao_ipsa
        ajuste_cidade = 1.0
    else:
        ajuste_regiao = fator_regiao.fator_aplicado if fator_regiao else 1.0
        ajuste_cidade = fator_cidade.fator_aplicado if fator_cidade else 1.0
    taxa_final = taxa_ipsa * ajuste_regiao * ajuste_modelo * ajuste_cidade

    # Guardrail estatístico amplo: evita extrapolações extremas de células históricas residuais.
    taxa_final = max(0.010, min(0.120, taxa_final))
    confianca = _confianca_v2(fator_modelo, fator_regiao, fator_cidade, municipio)
    if info_ano.get("idade") is not None and int(info_ano["idade"]) > 10:
        confianca = "referencia"

    nivel = "IPSA maio/2026"
    if info_ano.get("idade") is not None and int(info_ano["idade"]) > 10:
        nivel += " (sem faixa etária específica >10 anos)"
    if ref_regiao_ipsa:
        nivel += f" + {ref_regiao_ipsa.recorte}"
    elif fator_regiao:
        nivel += " + ajuste regional AUTOSEG"
    if fator_modelo:
        if fator_modelo.origem == "grupo_regiao":
            nivel += " + grupo histórico AUTOSEG"
        else:
            nivel += " + código FIPE histórico AUTOSEG"
    if fator_cidade and not ref_regiao_ipsa:
        nivel += " + ajuste municipal AUTOSEG"

    referencias = [
        {"dimensao": r.dimensao, "chave": r.chave, "taxa_percentual": r.taxa_percentual, "recorte": r.recorte}
        for r in refs
    ]
    if ref_regiao_ipsa:
        referencias.append({
            "dimensao": ref_regiao_ipsa.dimensao,
            "chave": ref_regiao_ipsa.chave,
            "taxa_percentual": ref_regiao_ipsa.taxa_percentual,
            "recorte": ref_regiao_ipsa.recorte,
        })
    detalhes_autoseg: dict[str, Any] = {
        "codigo_fipe": normalizar_codigo_fipe(codigo_fipe),
        "modelo": None,
        "cidade": str(municipio or ""),
        "uf": str(uf or "").upper(),
        "fator_modelo": None,
        "fator_regiao": None,
        "fator_cidade": None,
    }
    if fator_modelo:
        detalhes_autoseg["fator_modelo"] = {
            "origem": fator_modelo.origem,
            "bruto": round(fator_modelo.fator_bruto, 6),
            "aplicado": round(fator_modelo.fator_aplicado, 6),
            "exposicao": round(fator_modelo.exposicao, 3),
            "classe": fator_modelo.classe,
            "ano_base": fator_modelo.ano_base,
            "diferenca_anos": fator_modelo.diferenca_anos,
            "idade_fonte": fator_modelo.idade_fonte,
            "regiao": fator_modelo.regiao_descricao,
        }
    if fator_regiao:
        detalhes_autoseg["fator_regiao"] = {
            "bruto": round(fator_regiao.fator_bruto, 6),
            "aplicado": round(fator_regiao.fator_aplicado, 6),
            "exposicao": round(fator_regiao.exposicao, 3),
            "classe": fator_regiao.classe,
            "ano_base": fator_regiao.ano_base,
            "diferenca_anos": fator_regiao.diferenca_anos,
            "idade_fonte": fator_regiao.idade_fonte,
            "regiao": fator_regiao.regiao_descricao,
        }

    if fator_cidade:
        detalhes_autoseg["fator_cidade"] = {
            "bruto": round(fator_cidade.fator_bruto, 6),
            "aplicado": round(fator_cidade.fator_aplicado, 6),
            "exposicao": round(fator_cidade.exposicao, 3),
            "classe": fator_cidade.classe,
            "ano_base": fator_cidade.ano_base,
            "diferenca_anos": fator_cidade.diferenca_anos,
            "idade_fonte": fator_cidade.idade_fonte,
            "cidade_base": fator_cidade.cidade,
        }

    return {
        "valor_anual": round(valor * taxa_final, 2),
        "taxa_efetiva": round(taxa_final * 100.0, 4),
        "taxa_ipsa_base": round(taxa_ipsa_percent, 4),
        "fator_modelo": round(ajuste_modelo, 6),
        "fator_regiao": round(ajuste_regiao, 6),
        "fator_cidade": round(ajuste_cidade, 6),
        "fator_regiao_fonte": "IPSA maio/2026" if ref_regiao_ipsa else ("AUTOSEG/SUSEP" if fator_regiao else "nenhum"),
        "regiao_ipsa": ({
            "chave": ref_regiao_ipsa.chave,
            "taxa_percentual": ref_regiao_ipsa.taxa_percentual,
            "recorte": ref_regiao_ipsa.recorte,
            "fator_vs_mercado": round(fator_regiao_ipsa, 6),
        } if ref_regiao_ipsa else None),
        "uf_solicitada": str(uf or "").strip().upper(),
        "municipio_solicitado": str(municipio or "").strip(),
        "codigo_fipe": normalizar_codigo_fipe(codigo_fipe),
        "ano_modelo": info_ano.get("ano_modelo"),
        "idade": info_ano.get("idade"),
        "ano_referencia": int(ano_referencia or datetime.now().year),
        "tecnologia_solicitada": normalizar_tecnologia_v2(tecnologia),
        "fonte": FONTE_V2,
        "data_base": DATA_BASE_V2,
        "cobertura_referencia": COBERTURA_V2,
        "metodo": METODO_V2,
        "nivel_agregacao": nivel,
        "confianca": confianca,
        "versao_estimador": "seguro_v2",
        "referencias_ipsa": referencias,
        "autoseg": detalhes_autoseg,
        "autoseg_meta": autoseg_meta,
        "observacao": (
            "Estimativa estatística de referência. O IPSA define o patamar atual e, quando disponível, "
            "o recorte regional contemporâneo. O AUTOSEG/SUSEP é utilizado somente como fator relativo "
            "histórico com redução por credibilidade. "
            "Não representa cotação individual; valor editável pelo usuário."
        ),
        "resumo": f"Seguro estimado · mai/2026 · {'Média' if confianca == 'media' else 'Alta' if confianca == 'alta' else 'Referência' if confianca == 'referencia' else 'Fallback'}",
    }
