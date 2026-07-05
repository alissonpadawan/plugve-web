from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from flask import current_app

from repositories.familias_repository import FamiliasRepository
from repositories.historico_repository import HistoricoRepository
from core.modelos import VeiculoSelecionado
from core.classificacao import classificar_confianca_combustao, classificar_confianca_eletrico
from services.text_utils import normalizar_texto, parse_float_seguro, parse_int_seguro, formatar_brl


class CurvasRepository:
    def __init__(self) -> None:
        self.familias = FamiliasRepository()
        self.historico = HistoricoRepository()

    def status_bases(self) -> dict[str, Any]:
        curvas_c = self._ler_csv(self._arquivo_curvas_combustao())
        curvas_e = self._ler_csv(self._arquivo_curvas_eletrico())
        vinculos = self.listar_vinculos_similaridade()
        hist_c = self.historico.carregar_historico_combustao()
        hist_e = self.historico.carregar_historico_eletrico()
        return {
            "curvas_combustao": len(curvas_c),
            "curvas_eletrico": len(curvas_e),
            "vinculos_similaridade": len(vinculos),
            "historico_combustao": len(hist_c),
            "historico_eletrico": len(hist_e),
            "arquivo_curvas_combustao": str(self._arquivo_curvas_combustao()),
            "arquivo_curvas_eletrico": str(self._arquivo_curvas_eletrico()),
            "arquivo_vinculos_similaridade": str(self._arquivo_vinculos_similaridade()),
            "persistent_dir": str(current_app.config.get("PERSISTENT_DIR", "")),
            "fipe_cache_dir": str(current_app.config.get("FIPE_CACHE_DIR", "")),
            "snapshot_sync": self._ler_json_seguro(self._arquivo_status_snapshot(), {}),
        }

    def buscar_curva_combustao(self, veiculo: VeiculoSelecionado) -> dict[str, Any] | None:
        curvas = self._ler_csv(self._arquivo_curvas_combustao())
        if not curvas:
            return None

        # Prioridade metodológica: curva própria sempre vence.
        curva = self._buscar_por_codigo_fipe(curvas, veiculo.codigo_fipe)
        if curva:
            return self._montar_resultado_combustao(curva, veiculo, tipo_match="codigo_fipe")

        # Em seguida, usa apenas vínculo explícito vindo do Painel Local.
        vinculo = self._buscar_vinculo_similaridade_veiculo(veiculo, "combustao", curvas)
        if vinculo:
            curva_ref = self.buscar_curva_referencia_por_vinculo(vinculo, curvas)
            if curva_ref:
                return self._montar_resultado_combustao(
                    curva_ref,
                    veiculo,
                    tipo_match="similaridade_manual",
                    similaridade_info=self._montar_info_similaridade(vinculo, curva_ref, veiculo),
                )

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

        # Prioridade metodológica: curva própria sempre vence.
        curva = self._buscar_ev_por_codigos(curvas, veiculo.codigo_marca, veiculo.codigo_modelo)
        if curva:
            return self._montar_resultado_eletrico(curva, veiculo, tipo_match="codigo_modelo")

        # Em seguida, usa apenas vínculo explícito vindo do Painel Local.
        vinculo = self._buscar_vinculo_similaridade_veiculo(veiculo, "eletrico", curvas)
        if vinculo:
            curva_ref = self.buscar_curva_referencia_por_vinculo(vinculo, curvas)
            if curva_ref:
                return self._montar_resultado_eletrico(
                    curva_ref,
                    veiculo,
                    tipo_match="similaridade_manual",
                    similaridade_info=self._montar_info_similaridade(vinculo, curva_ref, veiculo),
                )

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

        V35: o modo padrão da integração Painel → Render passa a ser snapshot
        completo. Nesse modo, o painel local é a fonte da verdade e o Render
        substitui a base publicada pela fotografia enviada, removendo órfãos e
        reconstruindo os marcadores. O merge incremental antigo fica preservado
        apenas como modo legado/diagnóstico.
        """
        modo = str(payload.get("modo") or payload.get("modo_importacao") or "").strip().lower()
        if modo in {"snapshot_completo", "snapshot", "espelho_completo", "full_snapshot"}:
            return self.sincronizar_snapshot_painel(payload)

        curvas_combustao = payload.get("curvas_combustao") or []
        curvas_eletrico = payload.get("curvas_eletrico") or []
        vinculos_similaridade = payload.get("vinculos_similaridade")
        if not isinstance(curvas_combustao, list):
            curvas_combustao = []
        if not isinstance(curvas_eletrico, list):
            curvas_eletrico = []
        resultado = {
            "modo_importacao": "merge_legacy",
            "aviso": (
                "Modo incremental legado: pode preservar curvas antigas no disco persistente. "
                "Use snapshot_completo para manter o Render como espelho fiel do Painel Local."
            ),
            "combustao": self._importar_curvas_csv("combustao", curvas_combustao),
            "eletrico": self._importar_curvas_csv("eletrico", curvas_eletrico),
        }
        if isinstance(vinculos_similaridade, list):
            resultado["vinculos_similaridade"] = self._importar_vinculos_similaridade(vinculos_similaridade)
        else:
            resultado["vinculos_similaridade"] = {
                "recebidos": 0,
                "importados": 0,
                "mantido_arquivo_existente": True,
                "arquivo": str(self._arquivo_vinculos_similaridade()),
            }
        return resultado

    def _agora_sync_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _arquivo_manifest_snapshot(self) -> Path:
        return Path(current_app.config.get("PERSISTENT_DIR", "data/_runtime")) / "sync_manifest_curvas.json"

    def _arquivo_status_snapshot(self) -> Path:
        return Path(current_app.config.get("PERSISTENT_DIR", "data/_runtime")) / "sync_status_curvas.json"

    def _pasta_staging_snapshot(self) -> Path:
        return Path(current_app.config.get("PERSISTENT_DIR", "data/_runtime")) / "_staging"

    def _pasta_backups_snapshot(self) -> Path:
        return Path(current_app.config.get("PERSISTENT_DIR", "data/_runtime")) / "_backups"

    @staticmethod
    def _hash_payload_snapshot(payload: dict[str, Any]) -> str:
        """Hash estável do conteúdo técnico do snapshot.

        Campos voláteis como data_envio_local e manifest ficam fora do hash.
        Esta regra espelha o painel local para permitir validação no Render.
        """
        dados_hash = {
            "modo": "snapshot_completo",
            "schema_snapshot": payload.get("schema_snapshot") or payload.get("schema_version") or "curve_snapshot_v35",
            "schema_auditoria_curva": payload.get("schema_auditoria_curva"),
            "contrato_auditoria_curva": payload.get("contrato_auditoria_curva"),
            "curvas_combustao": payload.get("curvas_combustao", []),
            "curvas_eletrico": payload.get("curvas_eletrico", []),
            "vinculos_similaridade": payload.get("vinculos_similaridade", []),
        }
        bruto = json.dumps(dados_hash, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(bruto.encode("utf-8")).hexdigest()

    def _ler_json_seguro(self, path: Path, padrao: Any) -> Any:
        try:
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8") or "")
        except Exception:
            pass
        return padrao

    def _validar_snapshot_payload(self, payload: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any], str]:
        if not isinstance(payload, dict):
            raise ValueError("Snapshot inválido: payload não é um objeto JSON.")
        modo = str(payload.get("modo") or payload.get("modo_importacao") or "").strip().lower()
        if modo not in {"snapshot_completo", "snapshot", "espelho_completo", "full_snapshot"}:
            raise ValueError("Snapshot inválido: modo deve ser snapshot_completo.")
        if "curvas_combustao" not in payload or "curvas_eletrico" not in payload:
            raise ValueError("Snapshot inválido: curvas_combustao e curvas_eletrico são obrigatórios.")
        curvas_combustao = payload.get("curvas_combustao")
        curvas_eletrico = payload.get("curvas_eletrico")
        vinculos = payload.get("vinculos_similaridade")
        if not isinstance(curvas_combustao, list) or not isinstance(curvas_eletrico, list):
            raise ValueError("Snapshot inválido: listas de curvas em formato incorreto.")
        if vinculos is None:
            vinculos = []
        if not isinstance(vinculos, list):
            raise ValueError("Snapshot inválido: vinculos_similaridade deve ser uma lista.")
        if len(curvas_combustao) + len(curvas_eletrico) <= 0:
            raise ValueError("Snapshot recusado: pacote sem curvas. O Render não substitui a base por snapshot vazio.")

        manifest = payload.get("manifest")
        if not isinstance(manifest, dict):
            raise ValueError("Snapshot recusado: manifest obrigatório ausente ou inválido.")
        hash_calculado = self._hash_payload_snapshot(payload)
        hash_manifest = str(
            manifest.get("hash_payload")
            or manifest.get("hash_payload_curvas")
            or manifest.get("payload_hash_sha256")
            or ""
        ).strip()
        if not hash_manifest:
            raise ValueError("Snapshot recusado: manifest sem hash do payload.")
        if hash_manifest != hash_calculado:
            raise ValueError("Snapshot recusado: hash do manifest não bate com o conteúdo recebido.")

        contagens = manifest.get("contagens") if isinstance(manifest.get("contagens"), dict) else {}
        esperadas = {
            "curvas_combustao": len(curvas_combustao),
            "curvas_eletrico": len(curvas_eletrico),
            "vinculos_similaridade": len(vinculos),
        }
        for chave, valor in esperadas.items():
            if chave in contagens:
                try:
                    if int(contagens.get(chave) or 0) != int(valor):
                        raise ValueError(f"Snapshot recusado: contagem divergente em {chave}.")
                except ValueError:
                    raise
                except Exception as exc:
                    raise ValueError(f"Snapshot recusado: contagem inválida em {chave}.") from exc
        return curvas_combustao, curvas_eletrico, vinculos, manifest, hash_calculado

    def _chave_importacao_curva(self, row: dict[str, Any]) -> str:
        for campo in ("curve_id", "chave_curva", "chave_curva_eletrico", "chave_curva_combustao"):
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

    def _linha_curva_minimamente_valida(self, row: dict[str, Any], tipo: str) -> bool:
        if not isinstance(row, dict):
            return False
        status = str(row.get("status", "OK") or "OK").strip().upper()
        if status not in {"", "OK", "HOMOLOGADA", "EXPLORATORIA", "EXPLORATÓRIA"}:
            return False
        chave = str(row.get("chave_curva") or row.get("curve_id") or row.get("chave_curva_eletrico") or row.get("chave_curva_combustao") or "").strip()
        codigo_fipe = str(row.get("codigo_fipe") or "").strip()
        marca_id = str(row.get("marca_id") or row.get("codigo_marca") or "").strip()
        modelo_id = str(row.get("modelo_id") or row.get("codigo_modelo") or "").strip()
        modelo = str(row.get("modelo") or row.get("titulo") or row.get("veiculo") or "").strip()
        if tipo == "eletrico":
            return bool(chave or codigo_fipe or (marca_id and modelo_id) or modelo)
        return bool(chave or codigo_fipe or modelo)

    def _campos_curvas_snapshot(self, curvas: list[dict[str, Any]]) -> list[str]:
        campos: list[str] = []
        for row in curvas:
            if isinstance(row, dict):
                for campo in row.keys():
                    if campo not in campos:
                        campos.append(campo)
        for campo in ["origem_importacao", "data_importacao_render"]:
            if campo not in campos:
                campos.append(campo)
        return campos or ["origem_importacao", "data_importacao_render"]

    def _preparar_curvas_snapshot(self, tipo: str, curvas: list[dict[str, Any]], data_importacao: str) -> tuple[list[dict[str, Any]], list[str], int]:
        tipo_norm = str(tipo or "").strip().lower()
        campos = self._campos_curvas_snapshot([row for row in curvas if isinstance(row, dict)])
        linhas: list[dict[str, Any]] = []
        ignoradas = 0
        chaves_vistas: set[str] = set()
        for row in curvas:
            if not isinstance(row, dict) or not self._linha_curva_minimamente_valida(row, tipo_norm):
                ignoradas += 1
                continue
            nova = {campo: row.get(campo, "") for campo in campos}
            nova["origem_importacao"] = "painel_local_snapshot"
            nova["data_importacao_render"] = data_importacao
            chave = self._chave_importacao_curva(nova)
            if chave in chaves_vistas:
                # Snapshot deve ser determinístico. Mantém a última linha recebida para a chave.
                linhas = [item for item in linhas if self._chave_importacao_curva(item) != chave]
            chaves_vistas.add(chave)
            linhas.append(nova)
        if curvas and not linhas:
            raise ValueError(f"Snapshot recusado: nenhuma curva válida em {tipo_norm}.")
        return linhas, campos, ignoradas

    def _escrever_csv_snapshot(self, caminho: Path, campos: list[str], linhas: list[dict[str, Any]]) -> None:
        caminho.parent.mkdir(parents=True, exist_ok=True)
        with open(caminho, mode="w", encoding="utf-8-sig", newline="") as arquivo:
            escritor = csv.DictWriter(arquivo, fieldnames=campos, extrasaction="ignore")
            escritor.writeheader()
            for linha in linhas:
                escritor.writerow({campo: linha.get(campo, "") for campo in campos})

    def _chaves_vinculos_snapshot(self, vinculos: list[dict[str, Any]]) -> set[str]:
        chaves: set[str] = set()
        for row in vinculos:
            if not isinstance(row, dict):
                continue
            tipo = str(row.get("tipo") or "combustao").strip().lower()
            marca_id = str(row.get("marca_id") or row.get("codigo_marca") or "").strip()
            modelo_id = str(row.get("modelo_id") or row.get("codigo_modelo") or "").strip()
            marca = normalizar_texto(row.get("marca") or "")
            modelo = normalizar_texto(row.get("modelo") or "")
            chave_ref = str(row.get("chave_curva_referencia") or "").strip()
            chaves.add("|".join([tipo, marca_id, modelo_id, marca, modelo, chave_ref]))
        return chaves

    def _preparar_vinculos_snapshot(self, vinculos: list[dict[str, Any]], curvas_por_tipo: dict[str, list[dict[str, Any]]], data_importacao: str) -> tuple[list[dict[str, Any]], int, int]:
        chaves_ref_por_tipo: dict[str, set[str]] = {}
        for tipo, curvas in curvas_por_tipo.items():
            chaves_ref_por_tipo[tipo] = {
                str(row.get("chave_curva") or row.get("curve_id") or row.get("chave_curva_eletrico") or row.get("chave_curva_combustao") or "").strip()
                for row in curvas
                if str(row.get("chave_curva") or row.get("curve_id") or row.get("chave_curva_eletrico") or row.get("chave_curva_combustao") or "").strip()
            }
        importados: list[dict[str, Any]] = []
        ignorados = 0
        referencias_orfas = 0
        chaves_vistas: set[str] = set()
        for row in vinculos:
            if not isinstance(row, dict):
                ignorados += 1
                continue
            item = self._normalizar_vinculo_similaridade(row)
            item["data_importacao_render"] = data_importacao
            if not item.get("modelo") and not item.get("modelo_id"):
                ignorados += 1
                continue
            chave_ref = str(item.get("chave_curva_referencia") or "").strip()
            if not chave_ref:
                ignorados += 1
                continue
            tipo = str(item.get("tipo") or "combustao").strip().lower()
            if chave_ref not in chaves_ref_por_tipo.get(tipo, set()):
                referencias_orfas += 1
                continue
            chave_item = next(iter(self._chaves_vinculos_snapshot([item])))
            if chave_item in chaves_vistas:
                continue
            chaves_vistas.add(chave_item)
            importados.append(item)
        return importados, ignorados, referencias_orfas

    def _copiar_se_existir(self, origem: Path, destino: Path) -> bool:
        if origem.exists():
            destino.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(origem, destino)
            return True
        return False

    def _criar_backup_snapshot(self, backup_dir: Path) -> dict[str, Any]:
        backup_dir.mkdir(parents=True, exist_ok=True)
        itens = {
            "curvas_combustao": self._arquivo_curvas_combustao(),
            "curvas_eletrico": self._arquivo_curvas_eletrico(),
            "vinculos_similaridade": self._arquivo_vinculos_similaridade(),
            "manifest": self._arquivo_manifest_snapshot(),
            "status": self._arquivo_status_snapshot(),
        }
        copiados: dict[str, str] = {}
        ausentes: list[str] = []
        for nome, origem in itens.items():
            destino = backup_dir / origem.name
            if self._copiar_se_existir(origem, destino):
                copiados[nome] = str(destino)
            else:
                ausentes.append(nome)
        return {"criado": True, "diretorio": str(backup_dir), "copiados": copiados, "ausentes": ausentes}

    def _limpar_caches_curvas(self) -> None:
        try:
            self._ler_csv_cache.cache_clear()
        except Exception:
            pass

    def _resumo_curvas_snapshot(self, tipo: str, caminho: Path, recebidas: int, linhas: list[dict[str, Any]], ignoradas: int, orfaos: int) -> dict[str, Any]:
        return {
            "tipo": tipo,
            "arquivo": str(caminho),
            "recebidas": recebidas,
            "gravadas": len(linhas),
            "importadas": len(linhas),
            "ignoradas": ignoradas,
            "total_final": len(linhas),
            "orfaos_removidos": orfaos,
        }

    def sincronizar_snapshot_painel(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Substitui a base persistente do Render por um snapshot completo do painel.

        Não faz merge. Curvas/vínculos que não vieram no snapshot deixam de existir
        no espelho publicado e, portanto, deixam de gerar checks no site.
        """
        curvas_combustao, curvas_eletrico, vinculos, manifest, hash_calculado = self._validar_snapshot_payload(payload)
        data_importacao = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        persistent_dir = Path(current_app.config.get("PERSISTENT_DIR", "data/_runtime"))
        staging_dir = self._pasta_staging_snapshot() / f"sync_{timestamp}"
        backup_dir = self._pasta_backups_snapshot() / f"sync_{timestamp}"
        staging_dir.mkdir(parents=True, exist_ok=True)
        persistent_dir.mkdir(parents=True, exist_ok=True)

        antigas_combustao = self._ler_csv(self._arquivo_curvas_combustao())
        antigas_eletrico = self._ler_csv(self._arquivo_curvas_eletrico())
        antigos_vinculos = self.listar_vinculos_similaridade()

        linhas_combustao, campos_combustao, ignoradas_combustao = self._preparar_curvas_snapshot("combustao", curvas_combustao, data_importacao)
        linhas_eletrico, campos_eletrico, ignoradas_eletrico = self._preparar_curvas_snapshot("eletrico", curvas_eletrico, data_importacao)
        if len(linhas_combustao) + len(linhas_eletrico) <= 0:
            raise ValueError("Snapshot recusado: nenhuma curva válida após validação.")

        vinculos_importados, vinculos_ignorados, vinculos_orfaos_ref = self._preparar_vinculos_snapshot(
            vinculos,
            {"combustao": linhas_combustao, "eletrico": linhas_eletrico},
            data_importacao,
        )

        chaves_antigas_c = {self._chave_importacao_curva(row) for row in antigas_combustao}
        chaves_novas_c = {self._chave_importacao_curva(row) for row in linhas_combustao}
        chaves_antigas_e = {self._chave_importacao_curva(row) for row in antigas_eletrico}
        chaves_novas_e = {self._chave_importacao_curva(row) for row in linhas_eletrico}
        chaves_vinculos_antigos = self._chaves_vinculos_snapshot(antigos_vinculos)
        chaves_vinculos_novos = self._chaves_vinculos_snapshot(vinculos_importados)

        staging_combustao = staging_dir / self._arquivo_curvas_combustao().name
        staging_eletrico = staging_dir / self._arquivo_curvas_eletrico().name
        staging_vinculos = staging_dir / self._arquivo_vinculos_similaridade().name
        staging_manifest = staging_dir / "sync_manifest_curvas.json"
        staging_status = staging_dir / "sync_status_curvas.json"
        staging_payload = staging_dir / "payload_snapshot_recebido.json"

        self._escrever_csv_snapshot(staging_combustao, campos_combustao, linhas_combustao)
        self._escrever_csv_snapshot(staging_eletrico, campos_eletrico, linhas_eletrico)
        staging_vinculos.write_text(json.dumps(vinculos_importados, ensure_ascii=False, indent=2), encoding="utf-8")

        status_sync = {
            "ok": True,
            "modo": "snapshot_completo",
            "schema_snapshot": payload.get("schema_snapshot") or payload.get("schema_version") or "curve_snapshot_v35",
            "data_sincronizacao_render": self._agora_sync_iso(),
            "data_envio_local": payload.get("data_envio_local"),
            "hash_payload": hash_calculado,
            "manifest_recebido": manifest,
            "contagens": {
                "curvas_combustao_recebidas": len(curvas_combustao),
                "curvas_combustao_gravadas": len(linhas_combustao),
                "curvas_eletrico_recebidas": len(curvas_eletrico),
                "curvas_eletrico_gravadas": len(linhas_eletrico),
                "vinculos_similaridade_recebidos": len(vinculos),
                "vinculos_similaridade_gravados": len(vinculos_importados),
            },
            "orfaos_removidos": {
                "curvas_combustao": len(chaves_antigas_c - chaves_novas_c),
                "curvas_eletrico": len(chaves_antigas_e - chaves_novas_e),
                "vinculos_similaridade": len(chaves_vinculos_antigos - chaves_vinculos_novos),
            },
            "ignorados": {
                "curvas_combustao": ignoradas_combustao,
                "curvas_eletrico": ignoradas_eletrico,
                "vinculos_similaridade": vinculos_ignorados,
                "vinculos_referencia_orfa": vinculos_orfaos_ref,
            },
        }
        staging_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        staging_status.write_text(json.dumps(status_sync, ensure_ascii=False, indent=2), encoding="utf-8")
        staging_payload.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

        backup_info = self._criar_backup_snapshot(backup_dir)

        # Troca controlada: só substitui arquivos oficiais depois de validar e preparar staging.
        self._arquivo_curvas_combustao().parent.mkdir(parents=True, exist_ok=True)
        self._arquivo_curvas_eletrico().parent.mkdir(parents=True, exist_ok=True)
        self._arquivo_vinculos_similaridade().parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(staging_combustao, self._arquivo_curvas_combustao())
        shutil.copy2(staging_eletrico, self._arquivo_curvas_eletrico())
        shutil.copy2(staging_vinculos, self._arquivo_vinculos_similaridade())
        shutil.copy2(staging_manifest, self._arquivo_manifest_snapshot())
        shutil.copy2(staging_status, self._arquivo_status_snapshot())
        self._limpar_caches_curvas()

        resultado = {
            "ok": True,
            "modo_importacao": "snapshot_completo",
            "mensagem": "Snapshot completo sincronizado. Render agora é espelho do Painel Local.",
            "hash_payload": hash_calculado,
            "staging": {"diretorio": str(staging_dir)},
            "backup": backup_info,
            "combustao": self._resumo_curvas_snapshot(
                "combustao",
                self._arquivo_curvas_combustao(),
                len(curvas_combustao),
                linhas_combustao,
                ignoradas_combustao,
                len(chaves_antigas_c - chaves_novas_c),
            ),
            "eletrico": self._resumo_curvas_snapshot(
                "eletrico",
                self._arquivo_curvas_eletrico(),
                len(curvas_eletrico),
                linhas_eletrico,
                ignoradas_eletrico,
                len(chaves_antigas_e - chaves_novas_e),
            ),
            "vinculos_similaridade": {
                "arquivo": str(self._arquivo_vinculos_similaridade()),
                "recebidos": len(vinculos),
                "importados": len(vinculos_importados),
                "ignorados": vinculos_ignorados,
                "referencia_orfa": vinculos_orfaos_ref,
                "total_final": len(vinculos_importados),
                "orfaos_removidos": len(chaves_vinculos_antigos - chaves_vinculos_novos),
            },
            "status_sincronizacao": status_sync,
        }
        return resultado

    def _importar_curvas_csv(self, tipo: str, curvas: list[dict[str, Any]]) -> dict[str, Any]:
        """Modo incremental legado. Não usar como sincronização principal."""
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

        mapa: dict[str, dict[str, Any]] = {}
        ordem: list[str] = []
        for row in linhas_existentes:
            if not isinstance(row, dict):
                continue
            k = self._chave_importacao_curva(row)
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
            nova["origem_importacao"] = "painel_local_merge_legacy"
            nova["data_importacao_render"] = agora
            k = self._chave_importacao_curva(nova)
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

        self._limpar_caches_curvas()

        return {
            "tipo": tipo_norm,
            "arquivo": str(caminho),
            "recebidas": len(curvas),
            "importadas": importadas,
            "ignoradas": ignoradas,
            "total_final": len(mapa),
            "modo_importacao": "merge_legacy",
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

    def _arquivo_vinculos_similaridade(self) -> Path:
        return Path(current_app.config.get("PERSISTENT_DIR", "data/_runtime")) / "vinculos_similaridade_curvas.json"

    def _normalizar_vinculo_similaridade(self, row: dict[str, Any]) -> dict[str, Any]:
        tipo = str(row.get("tipo") or row.get("tipo_curva") or "combustao").strip().lower()
        if tipo in {"ev", "eletrico", "elétrico", "phev", "bev"}:
            tipo = "eletrico"
        else:
            tipo = "combustao"
        modelo_id = str(row.get("modelo_id") or row.get("codigo_modelo") or "").strip()
        marca_id = str(row.get("marca_id") or row.get("codigo_marca") or "").strip()
        chave = str(row.get("chave_curva_referencia") or row.get("chave_curva") or row.get("curve_id_referencia") or "").strip()
        return {
            "tipo": tipo,
            "marca": str(row.get("marca") or row.get("marca_nome") or "").strip(),
            "marca_id": marca_id,
            "modelo": str(row.get("modelo") or row.get("modelo_nome") or "").strip(),
            "modelo_id": modelo_id,
            "codigo_marca": marca_id,
            "codigo_modelo": modelo_id,
            "codigo_fipe": str(row.get("codigo_fipe") or "").strip(),
            "chave_curva_referencia": chave,
            "similaridade_status": str(row.get("similaridade_status") or row.get("status_similaridade") or row.get("status") or "").strip(),
            "modelo_referencia": str(row.get("modelo_referencia") or row.get("modelo_base") or row.get("modelo_pai") or "").strip(),
            "modelo_referencia_id": str(row.get("modelo_referencia_id") or row.get("modelo_id_referencia") or "").strip(),
            "marca_referencia": str(row.get("marca_referencia") or row.get("marca") or "").strip(),
            "origem_similaridade": str(row.get("origem_similaridade") or row.get("origem") or "painel_local_similaridade").strip(),
            "origem": str(row.get("origem") or "painel_local_similaridade").strip(),
            "data_importacao_render": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    def _importar_vinculos_similaridade(self, vinculos: list[dict[str, Any]]) -> dict[str, Any]:
        caminho = self._arquivo_vinculos_similaridade()
        caminho.parent.mkdir(parents=True, exist_ok=True)
        importados: list[dict[str, Any]] = []
        ignorados = 0
        for row in vinculos:
            if not isinstance(row, dict):
                ignorados += 1
                continue
            item = self._normalizar_vinculo_similaridade(row)
            if not item.get("modelo") and not item.get("modelo_id"):
                ignorados += 1
                continue
            if not item.get("chave_curva_referencia"):
                ignorados += 1
                continue
            importados.append(item)
        try:
            if caminho.exists():
                backup = caminho.with_suffix(caminho.suffix + f".bak_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
                backup.write_bytes(caminho.read_bytes())
        except Exception:
            pass
        caminho.write_text(json.dumps(importados, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "arquivo": str(caminho),
            "recebidos": len(vinculos),
            "importados": len(importados),
            "ignorados": ignorados,
        }

    def listar_vinculos_similaridade(self) -> list[dict[str, Any]]:
        caminho = self._arquivo_vinculos_similaridade()
        if not caminho.exists():
            return []
        try:
            dados = json.loads(caminho.read_text(encoding="utf-8") or "[]")
            if isinstance(dados, dict):
                dados = dados.get("vinculos") or dados.get("items") or []
            if not isinstance(dados, list):
                return []
            return [self._normalizar_vinculo_similaridade(row) for row in dados if isinstance(row, dict)]
        except Exception:
            return []

    def _vinculo_eh_similaridade_aplicavel(self, vinculo: dict[str, Any]) -> bool:
        status = normalizar_texto(vinculo.get("similaridade_status") or vinculo.get("status") or "")
        if status not in {"sim", "similar", "similaridade"}:
            return False
        return bool(str(vinculo.get("chave_curva_referencia") or "").strip())

    @staticmethod
    def _chave_curva_linha(row: dict[str, Any]) -> str:
        return str(row.get("chave_curva") or row.get("curve_id") or row.get("chave_curva_eletrico") or row.get("chave_curva_combustao") or "").strip()

    def _curva_valida_para_similaridade(self, row: dict[str, Any]) -> bool:
        if not isinstance(row, dict):
            return False
        status = str(row.get("status", "OK") or "OK").strip().upper()
        if status not in {"", "OK", "HOMOLOGADA", "EXPLORATORIA", "EXPLORATÓRIA"}:
            return False
        return not self._curva_combustao_v2_invalida(row)

    def buscar_curva_referencia_por_vinculo(self, vinculo: dict[str, Any], curvas: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
        if not self._vinculo_eh_similaridade_aplicavel(vinculo):
            return None
        tipo = str(vinculo.get("tipo") or "combustao").strip().lower()
        if curvas is None:
            caminho = self._arquivo_curvas_eletrico() if tipo == "eletrico" else self._arquivo_curvas_combustao()
            curvas = self._ler_csv(caminho)
        chave = str(vinculo.get("chave_curva_referencia") or "").strip()
        if not chave:
            return None
        candidatos = [row for row in curvas if self._chave_curva_linha(row) == chave and self._curva_valida_para_similaridade(row)]
        candidatos = self._ordenar_curvas_preferidas(candidatos)
        return candidatos[0] if candidatos else None

    def _vinculo_corresponde_veiculo(self, vinculo: dict[str, Any], veiculo: VeiculoSelecionado, tipo: str) -> bool:
        tipo_v = str(vinculo.get("tipo") or "").strip().lower()
        if tipo_v and tipo_v != tipo:
            return False
        marca_id_v = str(vinculo.get("marca_id") or vinculo.get("codigo_marca") or "").strip()
        modelo_id_v = str(vinculo.get("modelo_id") or vinculo.get("codigo_modelo") or "").strip()
        marca_id = str(veiculo.codigo_marca or "").strip()
        modelo_id = str(veiculo.codigo_modelo or "").strip()
        if marca_id_v and modelo_id_v and marca_id and modelo_id:
            return marca_id_v == marca_id and modelo_id_v == modelo_id
        marca_v = normalizar_texto(vinculo.get("marca", ""))
        modelo_v = normalizar_texto(vinculo.get("modelo", ""))
        marca = normalizar_texto(veiculo.marca)
        modelo = normalizar_texto(veiculo.modelo)
        return bool(marca_v and modelo_v and marca_v == marca and modelo_v == modelo)

    def _buscar_vinculo_similaridade_veiculo(self, veiculo: VeiculoSelecionado, tipo: str, curvas: list[dict[str, Any]]) -> dict[str, Any] | None:
        candidatos: list[dict[str, Any]] = []
        for vinculo in self.listar_vinculos_similaridade():
            if not self._vinculo_eh_similaridade_aplicavel(vinculo):
                continue
            if not self._vinculo_corresponde_veiculo(vinculo, veiculo, tipo):
                continue
            if not self.buscar_curva_referencia_por_vinculo(vinculo, curvas):
                continue
            candidatos.append(vinculo)
        return candidatos[0] if candidatos else None

    def _montar_info_similaridade(self, vinculo: dict[str, Any], curva_referencia: dict[str, Any], veiculo: VeiculoSelecionado) -> dict[str, Any]:
        modelo_ref = str(
            vinculo.get("modelo_referencia")
            or curva_referencia.get("modelo")
            or curva_referencia.get("titulo")
            or ""
        ).strip()
        marca_ref = str(vinculo.get("marca_referencia") or curva_referencia.get("marca") or vinculo.get("marca") or "").strip()
        if marca_ref and modelo_ref and marca_ref.lower() not in modelo_ref.lower():
            modelo_ref_titulo = f"{marca_ref} {modelo_ref}".strip()
        else:
            modelo_ref_titulo = modelo_ref or str(curva_referencia.get("titulo") or "").strip()
        return {
            "tipo_curva_aplicada": "similaridade",
            "curva_propria": False,
            "curva_por_similaridade": True,
            "similaridade_curva": True,
            "modelo_selecionado": " ".join(parte for parte in [veiculo.marca, veiculo.modelo] if parte).strip(),
            "modelo_referencia_similaridade": modelo_ref_titulo,
            "modelo_referencia": modelo_ref_titulo,
            "modelo_referencia_id": str(vinculo.get("modelo_referencia_id") or curva_referencia.get("modelo_id") or "").strip(),
            "chave_curva_referencia": str(vinculo.get("chave_curva_referencia") or self._chave_curva_linha(curva_referencia) or "").strip(),
            "origem_similaridade": str(vinculo.get("origem_similaridade") or "painel_local_similaridade").strip(),
            "similaridade_status": str(vinculo.get("similaridade_status") or "sim").strip(),
        }

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

    @staticmethod
    def _parse_data_base_operacao(texto: Any) -> datetime | None:
        """Converte a referência FIPE para o primeiro dia do mês.

        O painel local calcula a idade de entrada usando a data-base FIPE
        da operação. A API pode retornar formatos como ``2026-06``,
        ``junho de 2026`` ou ``junho/2026``.
        """
        txt = str(texto or "").strip().lower()
        if not txt:
            return None
        m = re.search(r"((?:19|20)\d{2})[-/](\d{1,2})", txt)
        if m:
            try:
                ano = int(m.group(1))
                mes = int(m.group(2))
                if 1 <= mes <= 12:
                    return datetime(ano, mes, 1)
            except Exception:
                pass
        meses = {
            "janeiro": 1, "jan": 1,
            "fevereiro": 2, "fev": 2,
            "março": 3, "marco": 3, "mar": 3,
            "abril": 4, "abr": 4,
            "maio": 5, "mai": 5,
            "junho": 6, "jun": 6,
            "julho": 7, "jul": 7,
            "agosto": 8, "ago": 8,
            "setembro": 9, "set": 9,
            "outubro": 10, "out": 10,
            "novembro": 11, "nov": 11,
            "dezembro": 12, "dez": 12,
        }
        ano_match = re.search(r"((?:19|20)\d{2})", txt)
        if ano_match:
            for nome, mes in meses.items():
                if nome in txt:
                    try:
                        return datetime(int(ano_match.group(1)), mes, 1)
                    except Exception:
                        return None
        return None

    def _data_base_operacao(self, curva: dict[str, Any], veiculo: VeiculoSelecionado) -> datetime:
        candidatos = [
            getattr(veiculo, "mes_referencia", ""),
            getattr(veiculo, "referencia_fipe", ""),
            curva.get("mes_referencia"),
            curva.get("referencia_fipe"),
            curva.get("referenceMonth"),
            curva.get("data_base_fipe"),
            curva.get("data_coleta"),
            curva.get("data_importacao_render"),
            curva.get("data_salvamento"),
        ]
        for item in candidatos:
            data = self._parse_data_base_operacao(item)
            if data is not None:
                return data
        agora = datetime.now()
        return datetime(agora.year, agora.month, 1)

    @staticmethod
    def _ano_modelo_int_selecionado(veiculo: VeiculoSelecionado) -> int | None:
        codigo_ano = str(veiculo.codigo_ano or "").strip()
        texto_ano = str(veiculo.ano_modelo or "").strip()
        if codigo_ano.startswith("32000") or "zero" in texto_ano.lower():
            return None
        for valor in (texto_ano, codigo_ano):
            m = re.search(r"(19|20)\d{2}", str(valor or ""))
            if m:
                try:
                    return int(m.group(0))
                except Exception:
                    return None
        return None

    def _idade_entrada_meses_combustao(self, curva: dict[str, Any], veiculo: VeiculoSelecionado) -> tuple[int, float, str]:
        ano_modelo = self._ano_modelo_int_selecionado(veiculo)
        data_base = self._data_base_operacao(curva, veiculo)
        if not ano_modelo:
            return 0, 0.0, data_base.strftime("%Y-%m")
        idade_meses = (data_base.year - int(ano_modelo)) * 12 + max(0, data_base.month - 1)
        idade_meses = max(0, int(idade_meses))
        return idade_meses, idade_meses / 12.0, data_base.strftime("%Y-%m")

    @staticmethod
    def _fator_taper_idade(idade_meses: int) -> float:
        idade_anos = max(0.0, float(idade_meses) / 12.0)
        if idade_anos <= 1.0:
            return 1.00
        if idade_anos <= 3.0:
            return 1.00 - ((idade_anos - 1.0) / 2.0) * 0.15
        if idade_anos <= 5.0:
            return 0.85 - ((idade_anos - 3.0) / 2.0) * 0.15
        if idade_anos <= 8.0:
            return 0.70 - ((idade_anos - 5.0) / 3.0) * 0.15
        if idade_anos <= 12.0:
            return 0.55 - ((idade_anos - 8.0) / 4.0) * 0.10
        return 0.45

    def _fator_cumulativo_por_idade(self, taxa_mensal_percentual: float, idade_entrada_meses: int, horizonte_meses: int) -> float:
        taxa_base = max(0.0, float(taxa_mensal_percentual or 0.0) / 100.0)
        fator = 1.0
        for passo in range(max(0, int(horizonte_meses or 0))):
            idade_mes_atual = max(0, int(idade_entrada_meses or 0)) + passo
            taxa_mes = max(0.0, taxa_base * self._fator_taper_idade(idade_mes_atual))
            fator *= (1.0 - taxa_mes)
        return fator

    @staticmethod
    def _taxa_anual_efetiva_do_fator(fator: float, horizonte_meses: int) -> float:
        try:
            meses = max(0, int(horizonte_meses or 0))
            fator_float = float(fator or 0.0)
            if meses <= 0 or fator_float <= 0:
                return 0.0
            anos = meses / 12.0
            if anos <= 0:
                return 0.0
            taxa = (1.0 - (fator_float ** (1.0 / anos))) * 100.0
            return max(0.0, taxa)
        except Exception:
            return 0.0

    def _projecao_mensal_combustao(self, valor_atual: float, taxa_mensal_hibrida: float, idade_entrada_meses: int, horizonte_meses: int) -> list[dict[str, Any]]:
        pontos: list[dict[str, Any]] = []
        if valor_atual <= 0 or horizonte_meses < 0:
            return pontos
        for mes in range(max(0, int(horizonte_meses)) + 1):
            fator_base = self._fator_cumulativo_por_idade(taxa_mensal_hibrida, idade_entrada_meses, mes)
            fator_ot = self._fator_cumulativo_por_idade(taxa_mensal_hibrida * 0.80, idade_entrada_meses, mes)
            fator_pe = self._fator_cumulativo_por_idade(taxa_mensal_hibrida * 1.20, idade_entrada_meses, mes)
            pontos.append({
                "mes": mes,
                "idade_meses": max(0, int(idade_entrada_meses or 0)) + mes,
                "valor_base": round(valor_atual * fator_base, 2),
                "valor_otimista": round(valor_atual * fator_ot, 2),
                "valor_pessimista": round(valor_atual * fator_pe, 2),
                "fator_base": round(fator_base, 10),
                "fator_otimista": round(fator_ot, 10),
                "fator_pessimista": round(fator_pe, 10),
            })
        return pontos

    def _projecao_mensal_anual_equivalente(self, valor_atual: float, taxa_anual_base: float, taxa_anual_otimista: float, taxa_anual_pessimista: float, horizonte_meses: int, idade_entrada_meses: int = 0) -> list[dict[str, Any]]:
        """Monta a memória mensal de projeção a partir das taxas anuais já calculadas.

        Não recalcula a curva. Apenas expõe, mês a mês, a mesma progressão
        equivalente usada para chegar aos valores finais dos cenários.
        """
        pontos: list[dict[str, Any]] = []
        if valor_atual <= 0 or horizonte_meses < 0:
            return pontos
        taxa_base = max(0.0, float(taxa_anual_base or 0.0) / 100.0)
        taxa_ot = max(0.0, float(taxa_anual_otimista or 0.0) / 100.0)
        taxa_pe = max(0.0, float(taxa_anual_pessimista or 0.0) / 100.0)
        for mes in range(max(0, int(horizonte_meses or 0)) + 1):
            anos = float(mes) / 12.0
            fator_base = (1.0 - taxa_base) ** anos
            fator_ot = (1.0 - taxa_ot) ** anos
            fator_pe = (1.0 - taxa_pe) ** anos
            pontos.append({
                "mes": mes,
                "idade_meses": max(0, int(idade_entrada_meses or 0)) + mes,
                "valor_base": round(valor_atual * fator_base, 2),
                "valor_otimista": round(valor_atual * fator_ot, 2),
                "valor_pessimista": round(valor_atual * fator_pe, 2),
                "fator_base": round(fator_base, 10),
                "fator_otimista": round(fator_ot, 10),
                "fator_pessimista": round(fator_pe, 10),
            })
        return pontos

    def _montar_relatorio_combustao_reaplicado(
        self,
        curva: dict[str, Any],
        veiculo: VeiculoSelecionado,
        origem_curva: str,
        valor_atual: float,
        valor_futuro: float,
        valor_futuro_otimista: float,
        valor_futuro_pessimista: float,
        taxa_mensal_hibrida: float,
        taxa_anual_referencia: float,
        taxa_anual_efetiva: float,
        idade_entrada_meses: int,
        idade_entrada_anos: float,
        horizonte: int,
        horizonte_meses: int,
        data_base_fipe: str,
        pontos: int,
        janela: int,
        confianca: str,
        relatorio_original: str,
        similaridade_info: dict[str, Any] | None = None,
    ) -> str:
        titulo = " ".join(parte for parte in [veiculo.marca, veiculo.modelo, str(veiculo.ano_modelo or "").strip()] if parte).strip()
        codigo_fipe = str(veiculo.codigo_fipe or curva.get("codigo_fipe") or "").strip()
        modelo_base = str(curva.get("veiculo") or curva.get("modelo") or curva.get("titulo") or "").strip()
        ano_base = str(curva.get("ano_base") or curva.get("ano_modelo") or curva.get("data_base_modelo") or "").strip()
        depreciacao_pct = ((valor_atual - valor_futuro) / valor_atual * 100.0) if valor_atual > 0 else 0.0
        linhas = [
            "RELATÓRIO TÉCNICO DE AUDITORIA DA DEPRECIAÇÃO",
            "",
            "1. RESULTADO APLICADO AO VEÍCULO CONSULTADO",
            f"Veículo consultado: {titulo or '-'}",
            f"Código FIPE: {codigo_fipe or '-'}",
            f"Valor FIPE atual selecionado: {formatar_brl(valor_atual)}",
            f"Referência/Data-base FIPE: {data_base_fipe or '-'}",
            f"Horizonte da análise: {horizonte} ano(s) ({horizonte_meses} meses)",
            f"Idade de entrada na curva: {idade_entrada_anos:.2f} ano(s) ({idade_entrada_meses} meses)",
            "",
            "2. CURVA UTILIZADA",
            f"Origem da curva: {origem_curva or 'curva salva combustão'}",
            f"Modelo-base/curva de referência: {modelo_base or '-'}",
            f"Ano/coorte base: {ano_base or '-'}",
            f"Pontos históricos: {pontos}",
            f"Janela histórica: {janela} meses",
            f"Confiança: {confianca or '-'}",
        ]
        if similaridade_info and similaridade_info.get("curva_por_similaridade"):
            linhas.extend([
                "",
                "2.1. HERANÇA POR SIMILARIDADE",
                "Tipo de curva aplicada: curva herdada por similaridade",
                f"Modelo selecionado pelo usuário: {similaridade_info.get('modelo_selecionado') or titulo or '-'}",
                f"Modelo referência da curva: {similaridade_info.get('modelo_referencia_similaridade') or similaridade_info.get('modelo_referencia') or '-'}",
                f"Origem do vínculo: {similaridade_info.get('origem_similaridade') or '-'}",
                f"Chave da curva referência: {similaridade_info.get('chave_curva_referencia') or '-'}",
                "Observação: o valor FIPE inicial permanece sendo o do veículo selecionado; somente a função/taxa de depreciação é herdada do modelo referência.",
            ])
        linhas.extend([
            "",
            "3. TAXAS E PROJEÇÃO",
            f"Taxa mensal híbrida base da curva: {taxa_mensal_hibrida:.4f}% a.m.",
            f"Taxa anual equivalente de referência da curva: {taxa_anual_referencia:.2f}% a.a.",
            f"Taxa anual efetiva aplicada ao horizonte: {taxa_anual_efetiva:.2f}% a.a.",
            f"Taxa de depreciação total no horizonte: {depreciacao_pct:.2f}%",
            f"Valor futuro base: {formatar_brl(valor_futuro)}",
            f"Valor futuro otimista: {formatar_brl(valor_futuro_otimista)}",
            f"Valor futuro pessimista: {formatar_brl(valor_futuro_pessimista)}",
            "",
            "4. OBSERVAÇÃO METODOLÓGICA",
            "O site aplicou a curva salva sobre o valor FIPE do ano/combustível selecionado. Para veículos usados, a projeção começa na idade atual do veículo dentro da curva, usando o mesmo offset de idade e o mesmo taper mensal do painel local.",
        ])
        original = str(relatorio_original or "").strip()
        if original:
            linhas.extend([
                "",
                "5. RELATÓRIO TÉCNICO ORIGINAL EXPORTADO COM A CURVA",
                original,
            ])
        return "\n".join(linhas).strip()

    def _montar_resultado_combustao(self, curva: dict[str, Any], veiculo: VeiculoSelecionado, tipo_match: str, similaridade_info: dict[str, Any] | None = None) -> dict[str, Any]:
        """Aplica a curva salva ao valor FIPE selecionado.

        Esta rotina replica a etapa leve do painel local: a curva já existe e
        não é recalculada; o site apenas reaplica a taxa mensal híbrida sobre o
        valor FIPE atual escolhido, considerando o offset de idade quando o ano
        selecionado não é zero km.
        """
        horizonte = max(1, int(veiculo.horizonte_anos or 5))
        horizonte_meses = int(round(float(horizonte) * 12))
        valor_atual = float(veiculo.valor_atual or parse_float_seguro(curva.get("valor_fipe_atual"), 0.0))
        taxa_mensal_hibrida = parse_float_seguro(curva.get("taxa_mensal_hibrida_percentual"), 0.0)
        taxa_anual_referencia = parse_float_seguro(curva.get("depreciacao_media_anual_principal_percentual"), 0.0)
        idade_entrada_meses, idade_entrada_anos, data_base_fipe = self._idade_entrada_meses_combustao(curva, veiculo)

        if taxa_mensal_hibrida <= 0 and taxa_anual_referencia > 0:
            taxa_mensal_hibrida = (1.0 - ((1.0 - taxa_anual_referencia / 100.0) ** (1.0 / 12.0))) * 100.0

        if taxa_mensal_hibrida > 0 and valor_atual > 0:
            fator_base = self._fator_cumulativo_por_idade(taxa_mensal_hibrida, idade_entrada_meses, horizonte_meses)
            fator_ot = self._fator_cumulativo_por_idade(taxa_mensal_hibrida * 0.80, idade_entrada_meses, horizonte_meses)
            fator_pe = self._fator_cumulativo_por_idade(taxa_mensal_hibrida * 1.20, idade_entrada_meses, horizonte_meses)
            valor_futuro = valor_atual * fator_base
            valor_futuro_otimista = valor_atual * fator_ot
            valor_futuro_pessimista = valor_atual * fator_pe
            taxa_anual_efetiva = self._taxa_anual_efetiva_do_fator(fator_base, horizonte_meses)
            taxa_anual_ot = self._taxa_anual_efetiva_do_fator(fator_ot, horizonte_meses)
            taxa_anual_pe = self._taxa_anual_efetiva_do_fator(fator_pe, horizonte_meses)
            projecao_mensal = self._projecao_mensal_combustao(valor_atual, taxa_mensal_hibrida, idade_entrada_meses, horizonte_meses)
        else:
            valor_futuro = self._valor_cenario_curva(curva, horizonte, "base")
            valor_taxa = valor_atual * ((1.0 - taxa_anual_referencia / 100.0) ** horizonte) if taxa_anual_referencia > 0 and valor_atual > 0 else 0.0
            if valor_futuro <= 0:
                valor_futuro = valor_taxa
            elif valor_taxa > 0:
                razao = valor_futuro / valor_taxa
                if razao < 0.65 or razao > 1.35:
                    valor_futuro = valor_taxa
            valor_futuro_otimista = self._valor_cenario_curva(curva, horizonte, "otimista")
            valor_futuro_pessimista = self._valor_cenario_curva(curva, horizonte, "pessimista")
            if valor_futuro_otimista <= 0 and valor_atual > 0 and taxa_anual_referencia > 0:
                valor_futuro_otimista = valor_atual * ((1.0 - (taxa_anual_referencia * 0.80) / 100.0) ** horizonte)
            if valor_futuro_pessimista <= 0 and valor_atual > 0 and taxa_anual_referencia > 0:
                valor_futuro_pessimista = valor_atual * ((1.0 - (taxa_anual_referencia * 1.20) / 100.0) ** horizonte)
            fator_base = (valor_futuro / valor_atual) if valor_atual > 0 and valor_futuro > 0 else 0.0
            fator_ot = (valor_futuro_otimista / valor_atual) if valor_atual > 0 and valor_futuro_otimista > 0 else 0.0
            fator_pe = (valor_futuro_pessimista / valor_atual) if valor_atual > 0 and valor_futuro_pessimista > 0 else 0.0
            taxa_anual_efetiva = self._taxa_anual_efetiva_do_fator(fator_base, horizonte_meses) or taxa_anual_referencia
            taxa_anual_ot = self._taxa_anual_efetiva_do_fator(fator_ot, horizonte_meses)
            taxa_anual_pe = self._taxa_anual_efetiva_do_fator(fator_pe, horizonte_meses)
            projecao_mensal = []

        pontos = parse_int_seguro(curva.get("observacoes_total") or curva.get("pontos_historicos"), 0)
        janela = parse_int_seguro(curva.get("janela_historica_meses"), 0)
        depreciacao_pct = ((valor_atual - valor_futuro) / valor_atual * 100.0) if valor_atual > 0 else 0.0
        relatorio_tecnico = str(
            curva.get("relatorio_tecnico")
            or curva.get("relatorio_tecnico_texto")
            or curva.get("relatorio_textual")
            or ""
        ).strip()

        origem_curva = str(curva.get("fonte_ajuste", "curva salva combustão") or "curva salva combustão")
        if similaridade_info and similaridade_info.get("curva_por_similaridade"):
            modelo_ref = similaridade_info.get("modelo_referencia_similaridade") or similaridade_info.get("modelo_referencia") or "modelo referência"
            origem_curva = f"Curva herdada por similaridade manual do modelo {modelo_ref}"
        if idade_entrada_meses > 0:
            origem_curva = f"{origem_curva} | reaplicada com offset de idade de {idade_entrada_anos:.2f} ano(s)"

        confianca_resultado = str(curva.get("confianca") or classificar_confianca_combustao(pontos, janela))
        relatorio_tecnico = self._montar_relatorio_combustao_reaplicado(
            curva=curva,
            veiculo=veiculo,
            origem_curva=origem_curva,
            valor_atual=valor_atual,
            valor_futuro=valor_futuro,
            valor_futuro_otimista=valor_futuro_otimista,
            valor_futuro_pessimista=valor_futuro_pessimista,
            taxa_mensal_hibrida=taxa_mensal_hibrida,
            taxa_anual_referencia=taxa_anual_referencia,
            taxa_anual_efetiva=taxa_anual_efetiva,
            idade_entrada_meses=idade_entrada_meses,
            idade_entrada_anos=idade_entrada_anos,
            horizonte=horizonte,
            horizonte_meses=horizonte_meses,
            data_base_fipe=data_base_fipe,
            pontos=pontos,
            janela=janela,
            confianca=confianca_resultado,
            relatorio_original=relatorio_tecnico,
            similaridade_info=similaridade_info,
        )

        valor_base_salvo = self._valor_cenario_curva(curva, horizonte, "base")
        valor_ot_salvo = self._valor_cenario_curva(curva, horizonte, "otimista")
        valor_pe_salvo = self._valor_cenario_curva(curva, horizonte, "pessimista")

        curva_aplicada = dict(curva)
        metadados_similaridade = dict(similaridade_info or {})
        curva_aplicada.update({
            **metadados_similaridade,
            "tipo_curva_aplicada": "similaridade" if metadados_similaridade else "propria",
            "curva_propria": False if metadados_similaridade else True,
            "curva_por_similaridade": bool(metadados_similaridade),
            "valor_fipe_atual": round(valor_atual, 2),
            "valor_futuro_base": round(valor_futuro, 2),
            "valor_futuro_otimista": round(valor_futuro_otimista, 2) if valor_futuro_otimista > 0 else 0.0,
            "valor_futuro_pessimista": round(valor_futuro_pessimista, 2) if valor_futuro_pessimista > 0 else 0.0,
            "valor_futuro_base_curva_salva": round(valor_base_salvo, 2) if valor_base_salvo > 0 else 0.0,
            "valor_futuro_otimista_curva_salva": round(valor_ot_salvo, 2) if valor_ot_salvo > 0 else 0.0,
            "valor_futuro_pessimista_curva_salva": round(valor_pe_salvo, 2) if valor_pe_salvo > 0 else 0.0,
            "horizonte_relatorio_anos": horizonte,
            "horizonte_meses": horizonte_meses,
            "inicio_curva_meses": idade_entrada_meses,
            "fim_curva_meses": idade_entrada_meses + horizonte_meses,
            "taxa_anual_efetiva_percentual": round(max(0.0, taxa_anual_efetiva), 6),
            "taxa_anual_referencia_percentual": round(max(0.0, taxa_anual_referencia), 6),
            "idade_entrada_meses": idade_entrada_meses,
            "idade_entrada_anos": round(idade_entrada_anos, 4),
            "data_base_fipe": data_base_fipe,
        })

        auditoria_historico = {
            **metadados_similaridade,
            "modo_calculo": "curva_salva_similaridade_usado_com_offset" if metadados_similaridade and idade_entrada_meses > 0 else ("curva_salva_similaridade_zero_km" if metadados_similaridade else ("curva_salva_usado_com_offset" if idade_entrada_meses > 0 else "curva_salva_zero_km")),
            "idade_entrada_meses": idade_entrada_meses,
            "idade_entrada_anos": round(idade_entrada_anos, 4),
            "data_base_fipe": data_base_fipe,
            "horizonte_meses": horizonte_meses,
            "inicio_curva_meses": idade_entrada_meses,
            "fim_curva_meses": idade_entrada_meses + horizonte_meses,
            "taxa_mensal_hibrida_percentual": round(max(0.0, taxa_mensal_hibrida), 8),
            "taxa_anual_referencia_percentual": round(max(0.0, taxa_anual_referencia), 6),
            "taxa_anual_efetiva_percentual": round(max(0.0, taxa_anual_efetiva), 6),
            "taxa_anual_otimista_percentual": round(max(0.0, taxa_anual_ot), 6),
            "taxa_anual_pessimista_percentual": round(max(0.0, taxa_anual_pe), 6),
            "fator_base": round(max(0.0, fator_base), 10),
            "fator_otimista": round(max(0.0, fator_ot), 10),
            "fator_pessimista": round(max(0.0, fator_pe), 10),
            "fator_transferencia_base": round(max(0.0, fator_base), 10),
            "fator_transferencia_otimista": round(max(0.0, fator_ot), 10),
            "fator_transferencia_pessimista": round(max(0.0, fator_pe), 10),
            "observacao_metodologica": "Valor FIPE selecionado projetado pela taxa mensal híbrida da curva salva, com taper por idade igual ao painel local.",
        }

        return {
            "tipo": "combustao",
            "tipo_match": "similaridade_manual" if metadados_similaridade else tipo_match,
            "tipo_curva_aplicada": "similaridade" if metadados_similaridade else "propria",
            "curva_propria": False if metadados_similaridade else True,
            "curva_por_similaridade": bool(metadados_similaridade),
            "similaridade_curva": bool(metadados_similaridade),
            **metadados_similaridade,
            "curva": curva_aplicada,
            "valor_atual": round(valor_atual, 2),
            "valor_futuro": round(valor_futuro, 2),
            "valor_futuro_base": round(valor_futuro, 2),
            "valor_futuro_otimista": round(valor_futuro_otimista, 2) if valor_futuro_otimista > 0 else 0.0,
            "valor_futuro_pessimista": round(valor_futuro_pessimista, 2) if valor_futuro_pessimista > 0 else 0.0,
            "valor_futuro_base_curva_salva": round(valor_base_salvo, 2) if valor_base_salvo > 0 else 0.0,
            "valor_futuro_otimista_curva_salva": round(valor_ot_salvo, 2) if valor_ot_salvo > 0 else 0.0,
            "valor_futuro_pessimista_curva_salva": round(valor_pe_salvo, 2) if valor_pe_salvo > 0 else 0.0,
            "horizonte_relatorio_anos": horizonte,
            "horizonte_meses": horizonte_meses,
            "inicio_curva_meses": idade_entrada_meses,
            "fim_curva_meses": idade_entrada_meses + horizonte_meses,
            "data_relatorio_tecnico": curva.get("data_relatorio_tecnico", ""),
            "data_base_fipe": data_base_fipe,
            "idade_entrada_meses": idade_entrada_meses,
            "idade_entrada_anos": round(idade_entrada_anos, 4),
            "depreciacao_percentual": round(max(0.0, depreciacao_pct), 2),
            "taxa_anual_percentual": round(max(0.0, taxa_anual_efetiva), 2),
            "taxa_anual_efetiva_percentual": round(max(0.0, taxa_anual_efetiva), 6),
            "taxa_anual_base_efetiva_percentual": round(max(0.0, taxa_anual_efetiva), 6),
            "taxa_anual_otimista_efetiva_percentual": round(max(0.0, taxa_anual_ot), 6),
            "taxa_anual_pessimista_efetiva_percentual": round(max(0.0, taxa_anual_pe), 6),
            "taxa_anual_referencia_percentual": round(max(0.0, taxa_anual_referencia), 6),
            "taxa_anual_otimista_percentual": round(max(0.0, taxa_anual_ot), 6),
            "taxa_anual_pessimista_percentual": round(max(0.0, taxa_anual_pe), 6),
            "taxa_mensal_hibrida_percentual": round(max(0.0, taxa_mensal_hibrida), 8),
            "fator_transferencia_base": round(max(0.0, fator_base), 10),
            "fator_transferencia_otimista": round(max(0.0, fator_ot), 10),
            "fator_transferencia_pessimista": round(max(0.0, fator_pe), 10),
            "fator_depreciacao_base": round(max(0.0, fator_base), 10),
            "fator_depreciacao_otimista": round(max(0.0, fator_ot), 10),
            "fator_depreciacao_pessimista": round(max(0.0, fator_pe), 10),
            "projecao_mensal": projecao_mensal,
            "confianca": confianca_resultado,
            "pontos_historicos": pontos,
            "janela_historica_meses": janela,
            "origem_curva": origem_curva,
            "relatorio_tecnico": relatorio_tecnico,
            "auditoria_historico": auditoria_historico,
        }

    def _montar_resultado_eletrico(self, curva: dict[str, Any], veiculo: VeiculoSelecionado, tipo_match: str, similaridade_info: dict[str, Any] | None = None) -> dict[str, Any]:
        horizonte = veiculo.horizonte_anos
        valor_atual = veiculo.valor_atual or parse_float_seguro(curva.get("valor_fipe_atual"), 0.0)
        valor_futuro = parse_float_seguro(curva.get("valor_futuro_base"), 0.0)
        taxa_anual = parse_float_seguro(curva.get("depreciacao_media_anual_percentual"), 0.0)
        taxa_anual_otimista = max(0.0, taxa_anual * 0.85)
        taxa_anual_pessimista = max(0.0, taxa_anual * 1.15)

        if taxa_anual > 0 and valor_atual > 0:
            # Recalcula sempre a partir do valor FIPE atual selecionado e do horizonte do usuário.
            # A curva salva fornece a taxa; o valor projetado precisa respeitar a seleção atual.
            valor_futuro = valor_atual * ((1.0 - taxa_anual / 100.0) ** horizonte)
            valor_otimista = valor_atual * ((1.0 - taxa_anual_otimista / 100.0) ** horizonte)
            valor_pessimista = valor_atual * ((1.0 - taxa_anual_pessimista / 100.0) ** horizonte)
        else:
            valor_otimista = parse_float_seguro(curva.get("valor_futuro_otimista") or curva.get("valor_otimista_final"), 0.0)
            valor_pessimista = parse_float_seguro(curva.get("valor_futuro_pessimista") or curva.get("valor_pessimista_final"), 0.0)

        horizonte_meses = int(horizonte * 12)
        projecao_mensal = self._projecao_mensal_anual_equivalente(
            valor_atual=float(valor_atual or 0.0),
            taxa_anual_base=taxa_anual,
            taxa_anual_otimista=taxa_anual_otimista,
            taxa_anual_pessimista=taxa_anual_pessimista,
            horizonte_meses=horizonte_meses,
            idade_entrada_meses=0,
        )
        fator_base = (valor_futuro / valor_atual) if valor_atual > 0 and valor_futuro > 0 else 0.0
        fator_ot = (valor_otimista / valor_atual) if valor_atual > 0 and valor_otimista > 0 else 0.0
        fator_pe = (valor_pessimista / valor_atual) if valor_atual > 0 and valor_pessimista > 0 else 0.0
        taxa_mensal_equivalente = (1.0 - ((1.0 - max(0.0, taxa_anual) / 100.0) ** (1.0 / 12.0))) * 100.0 if taxa_anual > 0 else 0.0

        pontos = parse_int_seguro(curva.get("pontos_historicos"), 0)
        janela = parse_int_seguro(curva.get("janela_historica_meses"), 0)
        depreciacao_pct = ((valor_atual - valor_futuro) / valor_atual * 100.0) if valor_atual > 0 else 0.0
        relatorio_tecnico = str(
            curva.get("relatorio_tecnico")
            or curva.get("relatorio_tecnico_texto")
            or curva.get("relatorio_textual")
            or ""
        ).strip()
        metadados_similaridade = dict(similaridade_info or {})
        origem_curva = str(curva.get("origem_curva", "curva EV salva") or "curva EV salva")
        if metadados_similaridade:
            modelo_ref = metadados_similaridade.get("modelo_referencia_similaridade") or metadados_similaridade.get("modelo_referencia") or "modelo referência"
            origem_curva = f"Curva herdada por similaridade manual do modelo {modelo_ref}"
            bloco = [
                "RELATÓRIO TÉCNICO DE AUDITORIA DA DEPRECIAÇÃO",
                "",
                "1. HERANÇA POR SIMILARIDADE",
                "Tipo de curva aplicada: curva herdada por similaridade",
                f"Modelo selecionado pelo usuário: {metadados_similaridade.get('modelo_selecionado') or f'{veiculo.marca} {veiculo.modelo}'.strip() or '-'}",
                f"Modelo referência da curva: {modelo_ref or '-'}",
                f"Origem do vínculo: {metadados_similaridade.get('origem_similaridade') or '-'}",
                f"Chave da curva referência: {metadados_similaridade.get('chave_curva_referencia') or '-'}",
                "Observação: o valor FIPE inicial permanece sendo o do veículo selecionado; somente a função/taxa de depreciação é herdada do modelo referência.",
            ]
            if relatorio_tecnico:
                bloco.extend(["", "2. RELATÓRIO TÉCNICO ORIGINAL EXPORTADO COM A CURVA", relatorio_tecnico])
            relatorio_tecnico = "\n".join(bloco).strip()

        curva_aplicada = dict(curva)
        curva_aplicada.update({
            **metadados_similaridade,
            "tipo_curva_aplicada": "similaridade" if metadados_similaridade else "propria",
            "curva_propria": False if metadados_similaridade else True,
            "curva_por_similaridade": bool(metadados_similaridade),
            "valor_fipe_atual": round(valor_atual, 2),
            "valor_futuro_base": round(valor_futuro, 2),
            "valor_futuro_otimista": round(valor_otimista, 2) if valor_otimista > 0 else 0.0,
            "valor_futuro_pessimista": round(valor_pessimista, 2) if valor_pessimista > 0 else 0.0,
            "horizonte_relatorio_anos": horizonte,
            "horizonte_meses": horizonte_meses,
        })

        return {
            "tipo": "eletrico",
            "tipo_match": "similaridade_manual" if metadados_similaridade else tipo_match,
            "tipo_curva_aplicada": "similaridade" if metadados_similaridade else "propria",
            "curva_propria": False if metadados_similaridade else True,
            "curva_por_similaridade": bool(metadados_similaridade),
            "similaridade_curva": bool(metadados_similaridade),
            **metadados_similaridade,
            "curva": curva_aplicada,
            "valor_atual": round(valor_atual, 2),
            "valor_futuro": round(valor_futuro, 2),
            "valor_futuro_base": round(valor_futuro, 2),
            "valor_futuro_otimista": round(valor_otimista, 2) if valor_otimista > 0 else 0.0,
            "valor_futuro_pessimista": round(valor_pessimista, 2) if valor_pessimista > 0 else 0.0,
            "horizonte_relatorio_anos": horizonte,
            "horizonte_meses": horizonte_meses,
            "inicio_curva_meses": 0,
            "fim_curva_meses": horizonte_meses,
            "idade_entrada_meses": 0,
            "idade_entrada_anos": 0.0,
            "taxa_mensal_hibrida_percentual": round(max(0.0, taxa_mensal_equivalente), 8),
            "fator_transferencia_base": round(max(0.0, fator_base), 10),
            "fator_transferencia_otimista": round(max(0.0, fator_ot), 10),
            "fator_transferencia_pessimista": round(max(0.0, fator_pe), 10),
            "fator_depreciacao_base": round(max(0.0, fator_base), 10),
            "fator_depreciacao_otimista": round(max(0.0, fator_ot), 10),
            "fator_depreciacao_pessimista": round(max(0.0, fator_pe), 10),
            "projecao_mensal": projecao_mensal,
            "taxa_anual_efetiva_percentual": round(max(0.0, taxa_anual), 6),
            "taxa_anual_base_efetiva_percentual": round(max(0.0, taxa_anual), 6),
            "taxa_anual_otimista_efetiva_percentual": round(max(0.0, taxa_anual_otimista), 6),
            "taxa_anual_pessimista_efetiva_percentual": round(max(0.0, taxa_anual_pessimista), 6),
            "data_relatorio_tecnico": curva.get("data_relatorio_tecnico", ""),
            "depreciacao_percentual": round(max(0.0, depreciacao_pct), 2),
            "taxa_anual_percentual": round(max(0.0, taxa_anual), 2),
            "confianca": classificar_confianca_eletrico(curva.get("confianca_ev", ""), pontos, janela),
            "pontos_historicos": pontos,
            "janela_historica_meses": janela,
            "origem_curva": origem_curva,
            "auditoria_historico": {
                **metadados_similaridade,
                "modo_calculo": "curva_ev_salva_por_similaridade_taxa_anual_equivalente" if metadados_similaridade else "curva_ev_salva_taxa_anual_equivalente",
                "horizonte_meses": horizonte_meses,
                "inicio_curva_meses": 0,
                "fim_curva_meses": horizonte_meses,
                "taxa_anual_efetiva_percentual": round(max(0.0, taxa_anual), 6),
                "taxa_mensal_hibrida_percentual": round(max(0.0, taxa_mensal_equivalente), 8),
                "fator_base": round(max(0.0, fator_base), 10),
                "fator_otimista": round(max(0.0, fator_ot), 10),
                "fator_pessimista": round(max(0.0, fator_pe), 10),
                "observacao_metodologica": "Memória mensal gerada pela taxa anual equivalente exportada com a curva EV salva.",
            },
            "relatorio_tecnico": relatorio_tecnico,
        }
