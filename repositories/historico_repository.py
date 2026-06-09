from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path
from typing import Any

from flask import current_app

from core.modelos import VeiculoSelecionado
from services.text_utils import normalizar_texto
from services.fipe_historico_service import FipeHistoricoService


class HistoricoRepository:
    def carregar_historico_combustao(self) -> list[dict[str, Any]]:
        return list(self._ler_csv_cache(str(Path(current_app.config["ARQUIVO_HISTORICO_COMBUSTAO"]))))

    def carregar_historico_eletrico(self) -> list[dict[str, Any]]:
        return list(self._ler_csv_cache(str(Path(current_app.config["ARQUIVO_HISTORICO_ELETRICO"]))))

    def buscar_historico_combustao_veiculo(self, veiculo: VeiculoSelecionado) -> list[dict[str, Any]]:
        """Busca histórico local. Se não houver base suficiente, baixa da FIPE web.

        Essa é a correção principal da Etapa 4.1: a existência de vários anos no
        dropdown FIPE não significa que o CSV local já tinha o histórico mensal.
        Agora, quando o CSV local não resolve, baixamos sob demanda e salvamos.
        """
        historico_local = self._buscar_historico_combustao_local(veiculo)
        if len(historico_local) >= 3:
            return historico_local

        historico_baixado = FipeHistoricoService().montar_historico_mensal(veiculo, limite_meses=48)
        if len(historico_baixado) >= 1:
            self.salvar_historico_combustao_sob_demanda(historico_baixado)

        if len(historico_baixado) >= 3:
            return historico_baixado

        # Retorna o melhor disponível para o motor gerar mensagem controlada.
        return historico_baixado or historico_local

    def _buscar_historico_combustao_local(self, veiculo: VeiculoSelecionado) -> list[dict[str, Any]]:
        linhas = self.carregar_historico_combustao()
        if not linhas:
            return []

        codigo_fipe = str(veiculo.codigo_fipe or "").strip()
        if codigo_fipe:
            por_codigo = [r for r in linhas if str(r.get("codigo_fipe", "") or r.get("CodigoFipe", "")).strip() == codigo_fipe]
            if len(por_codigo) >= 3:
                return por_codigo

        marca = normalizar_texto(veiculo.marca)
        modelo = normalizar_texto(veiculo.modelo)
        if not modelo:
            return []

        candidatos: list[dict[str, Any]] = []
        for row in linhas:
            texto = self._texto_linha(row)
            if not texto:
                continue
            if marca and marca not in texto:
                continue
            if modelo in texto or texto in modelo or self._tokens_relevantes_batem(modelo, texto):
                candidatos.append(row)

        return candidatos

    def salvar_historico_combustao_sob_demanda(self, novas_linhas: list[dict[str, Any]]) -> None:
        if not novas_linhas:
            return

        caminho = Path(current_app.config["ARQUIVO_HISTORICO_COMBUSTAO"])
        caminho.parent.mkdir(parents=True, exist_ok=True)

        linhas = []
        campos_existentes: list[str] = []
        if caminho.exists():
            with open(caminho, mode="r", encoding="utf-8-sig", newline="") as arquivo:
                leitor = csv.DictReader(arquivo)
                campos_existentes = list(leitor.fieldnames or [])
                linhas = [dict(row) for row in leitor]

        campos_padrao = [
            "data_referencia", "valor_fipe", "codigo_fipe", "marca", "modelo", "ano_modelo", "combustivel",
            "codigo_marca", "codigo_modelo", "codigo_ano", "origem",
        ]
        campos = list(campos_existentes or campos_padrao)
        for campo in campos_padrao:
            if campo not in campos:
                campos.append(campo)

        existentes = set()
        for row in linhas:
            chave = (
                str(row.get("codigo_fipe", "") or row.get("CodigoFipe", "")).strip(),
                str(row.get("data_referencia", "") or row.get("mes_referencia", "")).strip()[:7],
                str(row.get("codigo_ano", "") or "").strip(),
            )
            existentes.add(chave)

        for row in novas_linhas:
            chave = (
                str(row.get("codigo_fipe", "")).strip(),
                str(row.get("data_referencia", "")).strip()[:7],
                str(row.get("codigo_ano", "")).strip(),
            )
            if chave not in existentes:
                linhas.append(row)
                existentes.add(chave)

        with open(caminho, mode="w", encoding="utf-8-sig", newline="") as arquivo:
            escritor = csv.DictWriter(arquivo, fieldnames=campos, extrasaction="ignore")
            escritor.writeheader()
            for linha in linhas:
                escritor.writerow({campo: linha.get(campo, "") for campo in campos})

        try:
            self._ler_csv_cache.cache_clear()
        except Exception:
            pass

    @staticmethod
    @lru_cache(maxsize=8)
    def _ler_csv_cache(caminho_str: str) -> tuple[dict[str, Any], ...]:
        caminho = Path(caminho_str)
        if not caminho.exists():
            return tuple()
        with open(caminho, mode="r", encoding="utf-8-sig", newline="") as arquivo:
            return tuple(dict(row) for row in csv.DictReader(arquivo))

    @staticmethod
    def _texto_linha(row: dict[str, Any]) -> str:
        partes = []
        for chave in ["codigo_fipe", "CodigoFipe", "marca", "brand", "modelo", "model", "titulo", "veiculo"]:
            valor = row.get(chave)
            if valor:
                partes.append(str(valor))
        return normalizar_texto(" ".join(partes))

    @staticmethod
    def _tokens_relevantes_batem(modelo: str, texto_linha: str) -> bool:
        stop = {"flex", "gasolina", "alcool", "diesel", "automatico", "manual", "aut", "mec", "eletrico", "hibrido", "16v", "8v", "4x2", "4x4"}
        tokens = [t for t in modelo.split() if len(t) >= 3 and t not in stop]
        if not tokens:
            return False
        acertos = sum(1 for t in tokens if t in texto_linha)
        return acertos >= max(1, min(2, len(tokens)))
