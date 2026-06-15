from __future__ import annotations

import csv
from datetime import datetime
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
            "persistent_dir": str(current_app.config.get("PERSISTENT_DIR", "")),
            "fipe_cache_dir": str(current_app.config.get("FIPE_CACHE_DIR", "")),
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


    def salvar_curva_eletrica_calculada(self, veiculo: VeiculoSelecionado, resultado: dict[str, Any]) -> dict[str, Any]:
        """Salva curva EV/híbrida calculada sob demanda no CSV elétrico.

        O objetivo é transformar uma consulta sem curva em dado reutilizável:
        calculou uma vez, nas próximas consultas o painel carrega como curva salva.
        """
        caminho = self._arquivo_curvas_eletrico()
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

        taxa_anual = parse_float_seguro(resultado.get("taxa_anual_percentual"), 0.0)
        taxa_mensal = parse_float_seguro(resultado.get("taxa_mensal_percentual"), 0.0)
        valor_atual = parse_float_seguro(resultado.get("valor_atual"), 0.0)
        valor_futuro = parse_float_seguro(resultado.get("valor_futuro"), 0.0)
        horizonte = max(1, parse_int_seguro(resultado.get("horizonte_anos"), veiculo.horizonte_anos or 5))
        meses = horizonte * 12
        taxa_base = taxa_mensal / 100.0
        valor_ot_resultado = parse_float_seguro(resultado.get("valor_futuro_otimista"), 0.0)
        valor_pe_resultado = parse_float_seguro(resultado.get("valor_futuro_pessimista"), 0.0)
        valor_ot = valor_ot_resultado if valor_ot_resultado > 0 else (valor_atual * ((1.0 - max(0.0, taxa_base * 0.85)) ** meses) if valor_atual > 0 else 0.0)
        valor_pe = valor_pe_resultado if valor_pe_resultado > 0 else (valor_atual * ((1.0 - max(0.0, taxa_base * 1.20)) ** meses) if valor_atual > 0 else 0.0)

        nova_linha = {
            "titulo": resultado.get("veiculo_titulo") or f"{veiculo.marca} {veiculo.modelo} {veiculo.ano_modelo}".strip(),
            "marca_id": veiculo.codigo_marca,
            "modelo_id": veiculo.codigo_modelo,
            "ano_fipe_codigo": veiculo.codigo_ano,
            "marca": veiculo.marca,
            "modelo": veiculo.modelo,
            "ano_modelo": "Zero km" if str(veiculo.ano_modelo) == "32000" else veiculo.ano_modelo,
            "categoria": "EV_HIBRIDO",
            "modo_pandemia": "Excluir",
            "preco_zero_km_base": valor_atual,
            "data_preco_zero_km_base": datetime.now().strftime("%Y-%m"),
            "data_origem_idade": datetime.now().strftime("%Y-%m"),
            "garantia_bateria_anos": "8.00",
            "valor_fipe_atual": valor_atual,
            "valor_futuro_base": valor_futuro,
            "valor_futuro_otimista": round(valor_ot, 2),
            "valor_futuro_pessimista": round(valor_pe, 2),
            "taxa_mensal_base_cenario_percentual": taxa_mensal,
            "taxa_mensal_otimista_percentual": round(taxa_mensal * 0.85, 6),
            "taxa_mensal_pessimista_percentual": round(taxa_mensal * 1.20, 6),
            "depreciacao_media_anual_percentual": taxa_anual,
            "confianca_ev": resultado.get("confianca", "MÉDIA"),
            "janela_historica_meses": resultado.get("janela_historica_meses", 0),
            "pontos_historicos": resultado.get("pontos_historicos", 0),
            "zona_bateria": "VALIDACAO_WEB",
            "camada_ev_status": "CALCULADA_WEB",
            "data_salvamento": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "origem_curva": resultado.get("origem_curva", "cálculo sob demanda EV"),
            "tipo_match": resultado.get("tipo_match", ""),
            "fonte_historico": (resultado.get("auditoria_historico") or {}).get("fonte_historico", ""),
            "proxy_aplicado": "Sim" if (resultado.get("auditoria_historico") or {}).get("proxy_aplicado") else "Não",
            "metodo_taxa": (resultado.get("auditoria_historico") or {}).get("metodo_taxa", ""),
            "modo_calculo": (resultado.get("auditoria_historico") or {}).get("modo_calculo", ""),
            "idade_entrada_meses": (resultado.get("auditoria_historico") or {}).get("idade_entrada_meses", ""),
            "idade_projecao_meses": (resultado.get("auditoria_historico") or {}).get("idade_projecao_meses", ""),
            "primeiro_valor_historico": (resultado.get("auditoria_historico") or {}).get("primeiro_valor", ""),
            "ultimo_valor_historico": (resultado.get("auditoria_historico") or {}).get("ultimo_valor", ""),
            "variacao_total_percentual": (resultado.get("auditoria_historico") or {}).get("variacao_total_percentual", ""),
            "observacao_metodologica": (resultado.get("auditoria_historico") or {}).get("observacao", ""),
        }

        campos_padrao = list(nova_linha.keys())
        campos = list(campos_existentes or campos_padrao)
        for campo in campos_padrao:
            if campo not in campos:
                campos.append(campo)

        marca_id = str(veiculo.codigo_marca or "").strip()
        modelo_id = str(veiculo.codigo_modelo or "").strip()
        codigo_ano = str(veiculo.codigo_ano or "").strip()
        linhas_filtradas = []
        for linha in linhas:
            mesma = (
                marca_id and modelo_id
                and str(linha.get("marca_id", "") or "").strip() == marca_id
                and str(linha.get("modelo_id", "") or "").strip() == modelo_id
                and (not codigo_ano or str(linha.get("ano_fipe_codigo", "") or "").strip() == codigo_ano)
                and str(linha.get("camada_ev_status", "") or "") == "CALCULADA_WEB"
            )
            if not mesma:
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


    def importar_curvas_painel(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Importa curvas prontas exportadas pelo painel local.

        O Render não calcula curva aqui. Ele apenas recebe linhas já validadas
        pelo painel local e atualiza os CSVs persistentes em /var/data/plugve.
        """
        curvas_combustao = payload.get("curvas_combustao") or []
        curvas_eletrico = payload.get("curvas_eletrico") or []
        if not isinstance(curvas_combustao, list):
            curvas_combustao = []
        if not isinstance(curvas_eletrico, list):
            curvas_eletrico = []
        return {
            "combustao": self._importar_curvas_csv("combustao", curvas_combustao),
            "eletrico": self._importar_curvas_csv("eletrico", curvas_eletrico),
        }

    def _importar_curvas_csv(self, tipo: str, curvas: list[dict[str, Any]]) -> dict[str, Any]:
        tipo_norm = str(tipo or "").strip().lower()
        caminho = self._arquivo_curvas_eletrico() if tipo_norm == "eletrico" else self._arquivo_curvas_combustao()
        caminho.parent.mkdir(parents=True, exist_ok=True)

        linhas_existentes = self._ler_csv(caminho)
        campos_existentes: list[str] = []
        if caminho.exists():
            try:
                with open(caminho, mode="r", encoding="utf-8-sig", newline="") as arquivo:
                    leitor = csv.DictReader(arquivo)
                    campos_existentes = list(leitor.fieldnames or [])
            except Exception:
                campos_existentes = []

        campos: list[str] = list(campos_existentes)
        for row in linhas_existentes:
            for campo in row.keys():
                if campo not in campos:
                    campos.append(campo)
        for row in curvas:
            if isinstance(row, dict):
                for campo in row.keys():
                    if campo not in campos:
                        campos.append(campo)
        for campo in ["origem_importacao", "data_importacao_render"]:
            if campo not in campos:
                campos.append(campo)

        def chave(row: dict[str, Any]) -> str:
            for campo in ("curve_id", "chave_curva"):
                val = str(row.get(campo, "") or "").strip()
                if val:
                    return f"{campo}:{val}"
            partes = [
                str(row.get("codigo_fipe", "") or "").strip(),
                str(row.get("marca_id", "") or row.get("codigo_marca", "") or "").strip(),
                str(row.get("modelo_id", "") or row.get("codigo_modelo", "") or "").strip(),
                str(row.get("marca", "") or "").strip().lower(),
                str(row.get("modelo", "") or "").strip().lower(),
                str(row.get("ano_modelo", "") or "").strip(),
                str(row.get("modo_pandemia", "") or "").strip().lower(),
            ]
            return "fallback:" + "|".join(partes)

        mapa: dict[str, dict[str, Any]] = {}
        ordem: list[str] = []
        for row in linhas_existentes:
            if not isinstance(row, dict):
                continue
            k = chave(row)
            if k not in mapa:
                ordem.append(k)
            mapa[k] = row

        agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        importadas = 0
        ignoradas = 0
        for row in curvas:
            if not isinstance(row, dict):
                ignoradas += 1
                continue
            status = str(row.get("status", "OK") or "OK").strip().upper()
            if status not in {"", "OK", "HOMOLOGADA", "EXPLORATORIA", "EXPLORATÓRIA"}:
                ignoradas += 1
                continue
            nova = {campo: row.get(campo, "") for campo in campos}
            nova["origem_importacao"] = "painel_local"
            nova["data_importacao_render"] = agora
            k = chave(nova)
            if k not in mapa:
                ordem.append(k)
            mapa[k] = nova
            importadas += 1

        # Backup simples antes da escrita, no disco persistente.
        if caminho.exists():
            try:
                backup = caminho.with_suffix(caminho.suffix + f".bak_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
                backup.write_bytes(caminho.read_bytes())
            except Exception:
                pass

        with open(caminho, mode="w", encoding="utf-8-sig", newline="") as arquivo:
            escritor = csv.DictWriter(arquivo, fieldnames=campos, extrasaction="ignore")
            escritor.writeheader()
            for k in ordem:
                row = mapa.get(k, {})
                escritor.writerow({campo: row.get(campo, "") for campo in campos})

        try:
            self._ler_csv_cache.cache_clear()
        except Exception:
            pass

        return {
            "tipo": tipo_norm,
            "arquivo": str(caminho),
            "recebidas": len(curvas),
            "importadas": importadas,
            "ignoradas": ignoradas,
            "total_final": len(mapa),
        }


    def excluir_curvas_painel(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Exclui curvas no Render a pedido do painel local.

        Endpoint administrativo: usado quando o usuário apaga uma curva no painel
        e quer manter o Render como espelho online da base curada.
        """
        tipo_norm = str(payload.get("tipo", "combustao") or "combustao").strip().lower()
        caminho = self._arquivo_curvas_eletrico() if tipo_norm == "eletrico" else self._arquivo_curvas_combustao()
        chaves = {str(x or "").strip() for x in (payload.get("chaves_curva") or payload.get("chaves") or []) if str(x or "").strip()}
        codigo_fipe = str(payload.get("codigo_fipe", "") or "").strip()
        marca = normalizar_texto(payload.get("marca", ""))
        modelo = normalizar_texto(payload.get("modelo", ""))
        modo = str(payload.get("modo_pandemia", "") or "").strip().lower()

        linhas = self._ler_csv(caminho)
        if not linhas:
            return {"ok": True, "tipo": tipo_norm, "removidas": 0, "mensagem": "Nenhuma curva encontrada no Render."}

        campos = []
        try:
            with open(caminho, mode="r", encoding="utf-8-sig", newline="") as arquivo:
                leitor = csv.DictReader(arquivo)
                campos = list(leitor.fieldnames or [])
        except Exception:
            campos = list(linhas[0].keys()) if linhas else []

        def deve_remover(row: dict[str, Any]) -> bool:
            chave_row = str(row.get("chave_curva", "") or row.get("curve_id", "") or "").strip()
            if chaves and chave_row in chaves:
                return True
            if codigo_fipe and str(row.get("codigo_fipe", "") or "").strip() == codigo_fipe:
                if modo and str(row.get("modo_pandemia", "") or "").strip().lower() not in {"", modo}:
                    return False
                return True
            if marca and modelo:
                if normalizar_texto(row.get("marca", "")) == marca and normalizar_texto(row.get("modelo", "")) == modelo:
                    if modo and str(row.get("modo_pandemia", "") or "").strip().lower() not in {"", modo}:
                        return False
                    return True
            return False

        mantidas = []
        removidas = 0
        for row in linhas:
            if deve_remover(row):
                removidas += 1
            else:
                mantidas.append(row)

        if removidas:
            caminho.parent.mkdir(parents=True, exist_ok=True)
            try:
                backup = caminho.with_suffix(caminho.suffix + f".bak_delete_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
                backup.write_bytes(caminho.read_bytes())
            except Exception:
                pass
            with open(caminho, mode="w", encoding="utf-8-sig", newline="") as arquivo:
                escritor = csv.DictWriter(arquivo, fieldnames=campos, extrasaction="ignore")
                escritor.writeheader()
                for linha in mantidas:
                    escritor.writerow({campo: linha.get(campo, "") for campo in campos})
            try:
                self._ler_csv_cache.cache_clear()
            except Exception:
                pass

        return {
            "ok": True,
            "tipo": tipo_norm,
            "removidas": removidas,
            "mensagem": "Curva(s) removida(s) do Render." if removidas else "Nenhuma curva correspondente encontrada no Render.",
        }

    def apagar_curva_calculada(self, veiculo: VeiculoSelecionado, tipo: str) -> dict[str, Any]:
        """Remove manualmente uma curva criada pela calculadora web.

        Segurança: remove apenas curvas geradas pela camada web/sob demanda,
        preservando as bases originais importadas do painel técnico.
        """
        tipo_norm = str(tipo or "").strip().lower()
        caminho = self._arquivo_curvas_eletrico() if tipo_norm == "eletrico" else self._arquivo_curvas_combustao()
        linhas = self._ler_csv(caminho)
        if not linhas:
            return {"ok": True, "removidas": 0, "mensagem": "Nenhuma curva encontrada."}

        campos = []
        try:
            with open(caminho, mode="r", encoding="utf-8-sig", newline="") as arquivo:
                leitor = csv.DictReader(arquivo)
                campos = list(leitor.fieldnames or [])
        except Exception:
            campos = list(linhas[0].keys()) if linhas else []

        codigo_fipe = str(veiculo.codigo_fipe or "").strip()
        marca_id = str(veiculo.codigo_marca or "").strip()
        modelo_id = str(veiculo.codigo_modelo or "").strip()
        ano_codigo = str(veiculo.codigo_ano or "").strip()

        def eh_calculada_web(row: dict[str, Any]) -> bool:
            fonte = str(row.get("fonte_ajuste", "") or "").lower()
            camada = str(row.get("camada_ev_status", "") or "").lower()
            origem = str(row.get("origem_curva", "") or "").lower()
            return (
                "calculadora_depreciacao_v2" in fonte
                or "calculada_web" in camada
                or "cálculo sob demanda" in origem
                or "calculo sob demanda" in origem
            )

        def mesma_curva(row: dict[str, Any]) -> bool:
            if not eh_calculada_web(row):
                return False
            if tipo_norm == "eletrico":
                if marca_id and modelo_id:
                    if str(row.get("marca_id", "") or "").strip() == marca_id and str(row.get("modelo_id", "") or "").strip() == modelo_id:
                        # Se tiver ano salvo, respeita o ano; se não, remove a curva web do modelo.
                        row_ano = str(row.get("ano_fipe_codigo", "") or "").strip()
                        return not ano_codigo or not row_ano or row_ano == ano_codigo
                return bool(codigo_fipe and str(row.get("codigo_fipe", "") or "").strip() == codigo_fipe)
            return bool(codigo_fipe and str(row.get("codigo_fipe", "") or "").strip() == codigo_fipe)

        mantidas = []
        removidas = 0
        for row in linhas:
            if mesma_curva(row):
                removidas += 1
            else:
                mantidas.append(row)

        if removidas:
            caminho.parent.mkdir(parents=True, exist_ok=True)
            with open(caminho, mode="w", encoding="utf-8-sig", newline="") as arquivo:
                escritor = csv.DictWriter(arquivo, fieldnames=campos, extrasaction="ignore")
                escritor.writeheader()
                for linha in mantidas:
                    escritor.writerow({campo: linha.get(campo, "") for campo in campos})
            try:
                self._ler_csv_cache.cache_clear()
            except Exception:
                pass

        return {
            "ok": True,
            "removidas": removidas,
            "mensagem": "Curva calculada removida." if removidas else "Nenhuma curva calculada pela web foi encontrada para remover.",
        }

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

    def _ordenar_curvas_preferidas(self, linhas: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Prioriza a curva mais recente/importada do painel quando houver duplicidade.

        O Render pode ter curvas antigas no CSV persistente. Para não carregar uma
        curva velha quando o painel enviou uma nova, a busca sempre prefere linhas
        importadas pelo painel, versão mais nova e data de coleta/importação mais recente.
        """
        def versao_num(row: dict[str, Any]) -> float:
            txt = str(row.get("versao_curva", "") or row.get("versao", "") or "").upper().replace("V", "")
            try:
                return float(txt)
            except Exception:
                return 0.0

        def data_txt(row: dict[str, Any]) -> str:
            for campo in ("data_importacao_render", "data_coleta", "data_salvamento", "data_atualizacao", "data_calculo"):
                val = str(row.get(campo, "") or "").strip()
                if val:
                    return val
            return ""

        def prioridade(row: dict[str, Any]) -> tuple:
            origem = str(row.get("origem_importacao", "") or row.get("origem_curva", "") or "").lower()
            fonte = str(row.get("fonte_ajuste", "") or "").lower()
            importada = 1 if ("painel" in origem or "painel" in fonte or "coorte fixa" in fonte) else 0
            status = str(row.get("status", "") or "").upper()
            ok = 1 if status in {"", "OK", "HOMOLOGADA", "EXPLORATORIA", "EXPLORATÓRIA"} else 0
            pontos = parse_int_seguro(row.get("observacoes_total") or row.get("pontos_historicos"), 0)
            janela = parse_int_seguro(row.get("janela_historica_meses") or row.get("janela_meses"), 0)
            return (ok, importada, versao_num(row), data_txt(row), pontos, janela)

        return sorted(linhas, key=prioridade, reverse=True)

    def _buscar_por_codigo_fipe(self, curvas: list[dict[str, Any]], codigo_fipe: str) -> dict[str, Any] | None:
        alvo = str(codigo_fipe or "").strip()
        if not alvo:
            return None
        candidatos = [row for row in curvas if str(row.get("codigo_fipe", "") or "").strip() == alvo and not self._curva_combustao_v2_invalida(row)]
        candidatos = self._ordenar_curvas_preferidas(candidatos)
        return candidatos[0] if candidatos else None

    def _buscar_ev_por_codigos(self, curvas: list[dict[str, Any]], codigo_marca: str, codigo_modelo: str) -> dict[str, Any] | None:
        marca = str(codigo_marca or "").strip()
        modelo = str(codigo_modelo or "").strip()
        if not marca or not modelo:
            return None
        candidatos = [row for row in curvas if str(row.get("marca_id", "") or "").strip() == marca and str(row.get("modelo_id", "") or "").strip() == modelo]
        candidatos = self._ordenar_curvas_preferidas(candidatos)
        return candidatos[0] if candidatos else None

    def _buscar_curva_combustao_por_familia(self, curvas: list[dict[str, Any]], familia: dict[str, Any]) -> dict[str, Any] | None:
        modelo_base = normalizar_texto(familia.get("modelo_base_curva_combustao") or familia.get("modelo_base_curva"))
        ano_base = str(familia.get("ano_base_curva_combustao") or familia.get("ano_base_curva") or "").strip()
        family_id = str(familia.get("family_id", "") or "").strip()

        candidatos: list[dict[str, Any]] = []
        if family_id:
            candidatos.extend([row for row in curvas if str(row.get("family_id", "") or "").strip() == family_id and not self._curva_combustao_v2_invalida(row)])
        if candidatos:
            candidatos = self._ordenar_curvas_preferidas(candidatos)
            return candidatos[0]

        if modelo_base:
            for row in curvas:
                modelo_row = normalizar_texto(row.get("modelo", ""))
                ano_row = str(row.get("ano_modelo", "") or "").strip()
                if modelo_base and modelo_row and (modelo_base in modelo_row or modelo_row in modelo_base):
                    if not ano_base or not ano_row or ano_base == ano_row or ano_row == "32000":
                        if not self._curva_combustao_v2_invalida(row):
                            candidatos.append(row)
        candidatos = self._ordenar_curvas_preferidas(candidatos)
        return candidatos[0] if candidatos else None

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
        validos = [(score, row) for score, row in melhores if not self._curva_combustao_v2_invalida(row)]
        if not validos:
            return None
        score_max = max(score for score, _row in validos)
        candidatos = [row for score, row in validos if score == score_max]
        candidatos = self._ordenar_curvas_preferidas(candidatos)
        return candidatos[0] if candidatos else None

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

    def _valor_cenario_curva(self, curva: dict[str, Any], horizonte: int, tipo: str = "base") -> float:
        tipo_norm = str(tipo or "base").strip().lower()
        if tipo_norm == "base":
            chaves = [
                f"valor_{horizonte}ano",
                "valor_futuro_base",
                "valor_futuro",
                "valor_estimado_futuro_principal",
            ]
        elif tipo_norm == "otimista":
            chaves = [
                f"valor_{horizonte}ano_otimista",
                "valor_futuro_otimista",
                "valor_otimista_final",
            ]
        else:
            chaves = [
                f"valor_{horizonte}ano_pessimista",
                "valor_futuro_pessimista",
                "valor_pessimista_final",
            ]
        for chave in chaves:
            valor = parse_float_seguro(curva.get(chave), 0.0)
            if valor > 0:
                return valor
        return 0.0

    def _montar_resultado_combustao(self, curva: dict[str, Any], veiculo: VeiculoSelecionado, tipo_match: str) -> dict[str, Any]:
        horizonte = veiculo.horizonte_anos
        valor_atual = veiculo.valor_atual or parse_float_seguro(curva.get("valor_fipe_atual"), 0.0)
        taxa_anual = parse_float_seguro(curva.get("depreciacao_media_anual_principal_percentual"), 0.0)
        valor_futuro = self._valor_cenario_curva(curva, horizonte, "base")

        valor_taxa = valor_atual * ((1.0 - taxa_anual / 100.0) ** horizonte) if taxa_anual > 0 and valor_atual > 0 else 0.0
        # Proteção contra curva antiga/distorcida ainda existente no CSV persistente:
        # se o valor salvo divergir demais da taxa técnica exibida, usa a taxa da curva.
        if valor_futuro <= 0:
            valor_futuro = valor_taxa
        elif valor_taxa > 0 and valor_futuro > 0:
            razao = valor_futuro / valor_taxa
            if razao < 0.65 or razao > 1.35:
                valor_futuro = valor_taxa

        valor_futuro_otimista = self._valor_cenario_curva(curva, horizonte, "otimista")
        valor_futuro_pessimista = self._valor_cenario_curva(curva, horizonte, "pessimista")
        if valor_futuro_otimista <= 0 and valor_atual > 0 and taxa_anual > 0:
            valor_futuro_otimista = valor_atual * ((1.0 - (taxa_anual * 0.85) / 100.0) ** horizonte)
        if valor_futuro_pessimista <= 0 and valor_atual > 0 and taxa_anual > 0:
            valor_futuro_pessimista = valor_atual * ((1.0 - (taxa_anual * 1.15) / 100.0) ** horizonte)

        pontos = parse_int_seguro(curva.get("observacoes_total") or curva.get("pontos_historicos"), 0)
        janela = parse_int_seguro(curva.get("janela_historica_meses"), 0)
        depreciacao_pct = ((valor_atual - valor_futuro) / valor_atual * 100.0) if valor_atual > 0 else 0.0
        relatorio_tecnico = str(
            curva.get("relatorio_tecnico")
            or curva.get("relatorio_tecnico_texto")
            or curva.get("relatorio_textual")
            or ""
        ).strip()

        return {
            "tipo": "combustao",
            "tipo_match": tipo_match,
            "curva": curva,
            "valor_atual": round(valor_atual, 2),
            "valor_futuro": round(valor_futuro, 2),
            "valor_futuro_base": parse_float_seguro(curva.get("valor_futuro_base"), 0.0),
            "valor_futuro_otimista": round(valor_futuro_otimista, 2) if valor_futuro_otimista > 0 else 0.0,
            "valor_futuro_pessimista": round(valor_futuro_pessimista, 2) if valor_futuro_pessimista > 0 else 0.0,
            "horizonte_relatorio_anos": curva.get("horizonte_relatorio_anos", ""),
            "data_relatorio_tecnico": curva.get("data_relatorio_tecnico", ""),
            "depreciacao_percentual": round(max(0.0, depreciacao_pct), 2),
            "taxa_anual_percentual": round(max(0.0, taxa_anual), 2),
            "confianca": str(curva.get("confianca") or classificar_confianca_combustao(pontos, janela)),
            "pontos_historicos": pontos,
            "janela_historica_meses": janela,
            "origem_curva": str(curva.get("fonte_ajuste", "curva salva combustão") or "curva salva combustão"),
            "relatorio_tecnico": relatorio_tecnico,
        }

    def _montar_resultado_eletrico(self, curva: dict[str, Any], veiculo: VeiculoSelecionado, tipo_match: str) -> dict[str, Any]:
        horizonte = veiculo.horizonte_anos
        valor_atual = veiculo.valor_atual or parse_float_seguro(curva.get("valor_fipe_atual"), 0.0)
        valor_futuro = parse_float_seguro(curva.get("valor_futuro_base"), 0.0)
        taxa_anual = parse_float_seguro(curva.get("depreciacao_media_anual_percentual"), 0.0)

        if taxa_anual > 0 and valor_atual > 0:
            # Recalcula sempre a partir do valor FIPE atual selecionado e do horizonte do usuário.
            # A curva salva fornece a taxa; o valor projetado precisa respeitar a seleção atual.
            valor_futuro = valor_atual * ((1.0 - taxa_anual / 100.0) ** horizonte)

        valor_otimista = parse_float_seguro(curva.get("valor_futuro_otimista") or curva.get("valor_otimista_final"), 0.0)
        valor_pessimista = parse_float_seguro(curva.get("valor_futuro_pessimista") or curva.get("valor_pessimista_final"), 0.0)
        if taxa_anual > 0 and valor_atual > 0:
            if valor_otimista <= 0:
                valor_otimista = valor_atual * ((1.0 - (taxa_anual * 0.85) / 100.0) ** horizonte)
            if valor_pessimista <= 0:
                valor_pessimista = valor_atual * ((1.0 - (taxa_anual * 1.15) / 100.0) ** horizonte)

        pontos = parse_int_seguro(curva.get("pontos_historicos"), 0)
        janela = parse_int_seguro(curva.get("janela_historica_meses"), 0)
        depreciacao_pct = ((valor_atual - valor_futuro) / valor_atual * 100.0) if valor_atual > 0 else 0.0
        relatorio_tecnico = str(
            curva.get("relatorio_tecnico")
            or curva.get("relatorio_tecnico_texto")
            or curva.get("relatorio_textual")
            or ""
        ).strip()

        return {
            "tipo": "eletrico",
            "tipo_match": tipo_match,
            "curva": curva,
            "valor_atual": round(valor_atual, 2),
            "valor_futuro": round(valor_futuro, 2),
            "valor_futuro_base": parse_float_seguro(curva.get("valor_futuro_base"), 0.0),
            "valor_futuro_otimista": round(valor_otimista, 2) if valor_otimista > 0 else 0.0,
            "valor_futuro_pessimista": round(valor_pessimista, 2) if valor_pessimista > 0 else 0.0,
            "horizonte_relatorio_anos": curva.get("horizonte_relatorio_anos", ""),
            "data_relatorio_tecnico": curva.get("data_relatorio_tecnico", ""),
            "depreciacao_percentual": round(max(0.0, depreciacao_pct), 2),
            "taxa_anual_percentual": round(max(0.0, taxa_anual), 2),
            "confianca": classificar_confianca_eletrico(curva.get("confianca_ev", ""), pontos, janela),
            "pontos_historicos": pontos,
            "janela_historica_meses": janela,
            "origem_curva": str(curva.get("origem_curva", "curva EV salva") or "curva EV salva"),
            "relatorio_tecnico": relatorio_tecnico,
        }
