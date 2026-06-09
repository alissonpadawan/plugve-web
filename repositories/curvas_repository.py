from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path
from typing import Any

from flask import current_app

from repositories.familias_repository import FamiliasRepository
from repositories.historico_repository import HistoricoRepository
from core.modelos import VeiculoSelecionado
from core.classificacao import classificar_confianca_combustao, classificar_confianca_eletrico
from services.text_utils import normalizar_texto, parse_float_seguro, parse_int_seguro


class CurvasRepository:
    def __init__(self) -> None:
        self.familias = FamiliasRepository()
        self.historico = HistoricoRepository()

    def status_bases(self) -> dict[str, Any]:
        curvas_c = self._ler_csv(self._arquivo_curvas_combustao())
        curvas_e = self._ler_csv(self._arquivo_curvas_eletrico())
        hist_c = self.historico.carregar_historico_combustao()
        hist_e = self.historico.carregar_historico_eletrico()
        return {
            "curvas_combustao": len(curvas_c),
            "curvas_eletrico": len(curvas_e),
            "historico_combustao": len(hist_c),
            "historico_eletrico": len(hist_e),
            "arquivo_curvas_combustao": str(self._arquivo_curvas_combustao()),
            "arquivo_curvas_eletrico": str(self._arquivo_curvas_eletrico()),
        }

    def buscar_curva_combustao(self, veiculo: VeiculoSelecionado) -> dict[str, Any] | None:
        curvas = self._ler_csv(self._arquivo_curvas_combustao())
        if not curvas:
            return None

        curva = self._buscar_por_codigo_fipe(curvas, veiculo.codigo_fipe)
        if curva:
            return self._montar_resultado_combustao(curva, veiculo, tipo_match="codigo_fipe")

        familia = self.familias.buscar_familia(veiculo.codigo_marca, veiculo.codigo_modelo, veiculo.marca, veiculo.modelo)
        if familia:
            curva = self._buscar_curva_combustao_por_familia(curvas, familia)
            if curva:
                resultado = self._montar_resultado_combustao(curva, veiculo, tipo_match="familia")
                resultado["familia"] = familia
                return resultado

        curva = self._buscar_por_nome(curvas, veiculo.marca, veiculo.modelo)
        if curva:
            return self._montar_resultado_combustao(curva, veiculo, tipo_match="nome_aproximado")

        return None

    def buscar_curva_eletrico(self, veiculo: VeiculoSelecionado) -> dict[str, Any] | None:
        curvas = self._ler_csv(self._arquivo_curvas_eletrico())
        if not curvas:
            return None

        curva = self._buscar_ev_por_codigos(curvas, veiculo.codigo_marca, veiculo.codigo_modelo)
        if curva:
            return self._montar_resultado_eletrico(curva, veiculo, tipo_match="codigo_modelo")

        curva = self._buscar_por_nome(curvas, veiculo.marca, veiculo.modelo)
        if curva:
            return self._montar_resultado_eletrico(curva, veiculo, tipo_match="nome_aproximado")

        curva = self._buscar_ev_por_titulo(curvas, veiculo.marca, veiculo.modelo)
        if curva:
            return self._montar_resultado_eletrico(curva, veiculo, tipo_match="titulo")

        return None


    def salvar_curva_combustao_calculada(self, veiculo: VeiculoSelecionado, resultado: dict[str, Any]) -> dict[str, Any]:
        """Salva uma curva nova de combustão calculada pela V2.

        O CSV original pode ter colunas diferentes entre versões. Por isso,
        a função preserva as colunas existentes e adiciona apenas as colunas
        que faltarem para registrar o resultado mínimo da calculadora web.
        """
        caminho = self._arquivo_curvas_combustao()
        caminho.parent.mkdir(parents=True, exist_ok=True)

        linhas = self._ler_csv(caminho)
        campos_existentes: list[str] = []
        if caminho.exists():
            try:
                with open(caminho, mode="r", encoding="utf-8-sig", newline="") as arquivo:
                    leitor = csv.DictReader(arquivo)
                    campos_existentes = list(leitor.fieldnames or [])
            except Exception:
                campos_existentes = []

        nova_linha = {
            "titulo": resultado.get("veiculo_titulo") or f"{veiculo.marca} {veiculo.modelo} {veiculo.ano_modelo}".strip(),
            "marca": veiculo.marca,
            "modelo": veiculo.modelo,
            "ano_modelo": veiculo.ano_modelo,
            "codigo_fipe": veiculo.codigo_fipe,
            "marca_id": veiculo.codigo_marca,
            "modelo_id": veiculo.codigo_modelo,
            "ano_fipe_codigo": veiculo.codigo_ano,
            "valor_fipe_atual": resultado.get("valor_atual", 0.0),
            "valor_futuro_base": resultado.get("valor_futuro", 0.0),
            "depreciacao_percentual_base": resultado.get("depreciacao_percentual", 0.0),
            "depreciacao_media_anual_principal_percentual": resultado.get("taxa_anual_percentual", 0.0),
            "taxa_mensal_hibrida_percentual": resultado.get("taxa_mensal_percentual", 0.0),
            "observacoes_total": resultado.get("pontos_historicos", 0),
            "observacoes_utilizadas": resultado.get("pontos_historicos", 0),
            "janela_historica_meses": resultado.get("janela_historica_meses", 0),
            "periodo_inicial": resultado.get("periodo_inicial", ""),
            "periodo_final": resultado.get("periodo_final", ""),
            "fonte_ajuste": "calculadora_depreciacao_v2_sob_demanda",
            "origem_curva": "cálculo sob demanda combustão",
            "confianca": resultado.get("confianca", ""),
            "status": "OK",
            "tipo_match": resultado.get("tipo_match", ""),
            "codigo_ano_proxy": resultado.get("codigo_ano_proxy", ""),
            "ano_modelo_proxy": resultado.get("ano_modelo_proxy", ""),
            "nome_proxy": resultado.get("nome_proxy", ""),
        }

        campos_padrao = [
            "titulo", "marca", "modelo", "ano_modelo", "codigo_fipe", "marca_id", "modelo_id", "ano_fipe_codigo",
            "valor_fipe_atual", "valor_futuro_base", "depreciacao_percentual_base",
            "depreciacao_media_anual_principal_percentual", "taxa_mensal_hibrida_percentual",
            "observacoes_total", "observacoes_utilizadas", "janela_historica_meses",
            "periodo_inicial", "periodo_final", "fonte_ajuste", "origem_curva", "confianca", "status",
            "tipo_match", "codigo_ano_proxy", "ano_modelo_proxy", "nome_proxy",
        ]
        campos = list(campos_existentes or campos_padrao)
        for campo in campos_padrao:
            if campo not in campos:
                campos.append(campo)

        # remove curva anterior da V2 para o mesmo código FIPE, se houver
        codigo = str(veiculo.codigo_fipe or "").strip()
        linhas_filtradas = []
        for linha in linhas:
            mesma_curva = codigo and str(linha.get("codigo_fipe", "") or "").strip() == codigo and str(linha.get("fonte_ajuste", "")) == "calculadora_depreciacao_v2_sob_demanda"
            if not mesma_curva:
                linhas_filtradas.append(linha)
        linhas_filtradas.append(nova_linha)

        with open(caminho, mode="w", encoding="utf-8-sig", newline="") as arquivo:
            escritor = csv.DictWriter(arquivo, fieldnames=campos, extrasaction="ignore")
            escritor.writeheader()
            for linha in linhas_filtradas:
                escritor.writerow({campo: linha.get(campo, "") for campo in campos})

        try:
            self._ler_csv_cache.cache_clear()
        except Exception:
            pass

        return nova_linha

    def _arquivo_curvas_combustao(self) -> Path:
        return Path(current_app.config["ARQUIVO_CURVAS_COMBUSTAO"])

    def _arquivo_curvas_eletrico(self) -> Path:
        return Path(current_app.config["ARQUIVO_CURVAS_ELETRICO"])

    @staticmethod
    @lru_cache(maxsize=16)
    def _ler_csv_cache(caminho_str: str) -> tuple[dict[str, Any], ...]:
        caminho = Path(caminho_str)
        if not caminho.exists():
            return tuple()
        with open(caminho, mode="r", encoding="utf-8-sig", newline="") as arquivo:
            return tuple(dict(row) for row in csv.DictReader(arquivo))

    def _ler_csv(self, caminho: Path) -> list[dict[str, Any]]:
        return list(self._ler_csv_cache(str(caminho)))


    def _curva_combustao_v2_invalida(self, curva: dict[str, Any]) -> bool:
        fonte = str(curva.get("fonte_ajuste", "") or "").strip()
        if fonte != "calculadora_depreciacao_v2_sob_demanda":
            return False
        taxa = parse_float_seguro(curva.get("depreciacao_media_anual_principal_percentual"), 0.0)
        valor_futuro = parse_float_seguro(curva.get("valor_futuro_base"), 0.0)
        valor_atual = parse_float_seguro(curva.get("valor_fipe_atual"), 0.0)
        return taxa <= 0.05 or (valor_atual > 0 and abs(valor_atual - valor_futuro) < 1.0)

    def _buscar_por_codigo_fipe(self, curvas: list[dict[str, Any]], codigo_fipe: str) -> dict[str, Any] | None:
        alvo = str(codigo_fipe or "").strip()
        if not alvo:
            return None
        for row in curvas:
            if str(row.get("codigo_fipe", "") or "").strip() == alvo:
                if self._curva_combustao_v2_invalida(row):
                    continue
                return row
        return None

    def _buscar_ev_por_codigos(self, curvas: list[dict[str, Any]], codigo_marca: str, codigo_modelo: str) -> dict[str, Any] | None:
        marca = str(codigo_marca or "").strip()
        modelo = str(codigo_modelo or "").strip()
        if not marca or not modelo:
            return None
        for row in curvas:
            if str(row.get("marca_id", "") or "").strip() == marca and str(row.get("modelo_id", "") or "").strip() == modelo:
                return row
        return None

    def _buscar_curva_combustao_por_familia(self, curvas: list[dict[str, Any]], familia: dict[str, Any]) -> dict[str, Any] | None:
        modelo_base = normalizar_texto(familia.get("modelo_base_curva_combustao") or familia.get("modelo_base_curva"))
        ano_base = str(familia.get("ano_base_curva_combustao") or familia.get("ano_base_curva") or "").strip()
        family_id = str(familia.get("family_id", "") or "").strip()

        if family_id:
            for row in curvas:
                if str(row.get("family_id", "") or "").strip() == family_id:
                    if self._curva_combustao_v2_invalida(row):
                        continue
                    return row

        if modelo_base:
            for row in curvas:
                modelo_row = normalizar_texto(row.get("modelo", ""))
                ano_row = str(row.get("ano_modelo", "") or "").strip()
                if modelo_base in modelo_row or modelo_row in modelo_base:
                    if not ano_base or not ano_row or ano_base == ano_row or ano_row == "32000":
                        if self._curva_combustao_v2_invalida(row):
                            continue
                        return row
        return None

    def _buscar_por_nome(self, curvas: list[dict[str, Any]], marca: str, modelo: str) -> dict[str, Any] | None:
        alvo_modelo = normalizar_texto(modelo)
        alvo_marca = normalizar_texto(marca)
        if not alvo_modelo:
            return None

        melhores: list[tuple[int, dict[str, Any]]] = []
        for row in curvas:
            marca_row = normalizar_texto(row.get("marca", ""))
            modelo_row = normalizar_texto(row.get("modelo", ""))
            titulo_row = normalizar_texto(row.get("titulo", ""))
            texto_row = normalizar_texto(f"{marca_row} {modelo_row} {titulo_row}")

            score = 0
            if alvo_marca and alvo_marca == marca_row:
                score += 20
            if alvo_modelo == modelo_row:
                score += 80
            elif alvo_modelo and modelo_row and (alvo_modelo in modelo_row or modelo_row in alvo_modelo):
                score += 45
            elif alvo_modelo and alvo_modelo in texto_row:
                score += 35

            if score >= 45:
                melhores.append((score, row))

        if not melhores:
            return None
        melhores.sort(key=lambda x: x[0], reverse=True)
        for _score, row in melhores:
            if not self._curva_combustao_v2_invalida(row):
                return row
        return None

    def _buscar_ev_por_titulo(self, curvas: list[dict[str, Any]], marca: str, modelo: str) -> dict[str, Any] | None:
        alvo = normalizar_texto(f"{marca} {modelo}")
        alvo_modelo = normalizar_texto(modelo)
        for row in curvas:
            titulo = normalizar_texto(row.get("titulo", ""))
            if alvo and (alvo in titulo or titulo in alvo):
                return row
            if alvo_modelo and (alvo_modelo in titulo or titulo in alvo_modelo):
                return row
        return None

    def _montar_resultado_combustao(self, curva: dict[str, Any], veiculo: VeiculoSelecionado, tipo_match: str) -> dict[str, Any]:
        horizonte = veiculo.horizonte_anos
        valor_atual = veiculo.valor_atual or parse_float_seguro(curva.get("valor_fipe_atual"), 0.0)
        valor_futuro = parse_float_seguro(curva.get(f"valor_{horizonte}ano"), 0.0)

        if valor_futuro <= 0:
            taxa = parse_float_seguro(curva.get("depreciacao_media_anual_principal_percentual"), 0.0) / 100.0
            valor_futuro = valor_atual * ((1.0 - taxa) ** horizonte) if valor_atual > 0 else 0.0

        pontos = parse_int_seguro(curva.get("observacoes_total"), 0)
        janela = parse_int_seguro(curva.get("janela_historica_meses"), 0)
        taxa_anual = parse_float_seguro(curva.get("depreciacao_media_anual_principal_percentual"), 0.0)
        depreciacao_pct = ((valor_atual - valor_futuro) / valor_atual * 100.0) if valor_atual > 0 else 0.0

        return {
            "tipo": "combustao",
            "tipo_match": tipo_match,
            "curva": curva,
            "valor_atual": round(valor_atual, 2),
            "valor_futuro": round(valor_futuro, 2),
            "depreciacao_percentual": round(max(0.0, depreciacao_pct), 2),
            "taxa_anual_percentual": round(max(0.0, taxa_anual), 2),
            "confianca": classificar_confianca_combustao(pontos, janela),
            "pontos_historicos": pontos,
            "janela_historica_meses": janela,
            "origem_curva": str(curva.get("fonte_ajuste", "curva salva combustão") or "curva salva combustão"),
        }

    def _montar_resultado_eletrico(self, curva: dict[str, Any], veiculo: VeiculoSelecionado, tipo_match: str) -> dict[str, Any]:
        horizonte = veiculo.horizonte_anos
        valor_atual = veiculo.valor_atual or parse_float_seguro(curva.get("valor_fipe_atual"), 0.0)
        valor_futuro = parse_float_seguro(curva.get("valor_futuro_base"), 0.0)
        taxa_anual = parse_float_seguro(curva.get("depreciacao_media_anual_percentual"), 0.0)

        if horizonte != 5 and taxa_anual > 0 and valor_atual > 0:
            valor_futuro = valor_atual * ((1.0 - taxa_anual / 100.0) ** horizonte)

        pontos = parse_int_seguro(curva.get("pontos_historicos"), 0)
        janela = parse_int_seguro(curva.get("janela_historica_meses"), 0)
        depreciacao_pct = ((valor_atual - valor_futuro) / valor_atual * 100.0) if valor_atual > 0 else 0.0

        return {
            "tipo": "eletrico",
            "tipo_match": tipo_match,
            "curva": curva,
            "valor_atual": round(valor_atual, 2),
            "valor_futuro": round(valor_futuro, 2),
            "depreciacao_percentual": round(max(0.0, depreciacao_pct), 2),
            "taxa_anual_percentual": round(max(0.0, taxa_anual), 2),
            "confianca": classificar_confianca_eletrico(curva.get("confianca_ev", ""), pontos, janela),
            "pontos_historicos": pontos,
            "janela_historica_meses": janela,
            "origem_curva": "curva EV salva",
        }
