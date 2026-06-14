from __future__ import annotations

import csv
import json
import os
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import requests
from flask import current_app

from services.tipo_veiculo_service import (
    classificar_tipo_veiculo,
    contexto_fipe,
    marca_permitida_no_contexto,
    tipo_permitido_no_contexto,
)


class FipeApiError(Exception):
    def __init__(self, message: str, status_code: int | None = None, endpoint: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.endpoint = endpoint
        self.message = message

    @property
    def tipo(self) -> str:
        if self.status_code == 429:
            return "limite_requisicoes"
        if self.status_code == 404:
            return "nao_encontrado"
        if self.status_code in (401, 403):
            return "token_ou_acesso"
        if self.status_code is None:
            return "conexao"
        return "erro_api"

    def to_dict(self) -> dict:
        return {
            "erro": self.message,
            "status_code": self.status_code,
            "tipo": self.tipo,
            "fipe_limitada": self.status_code == 429,
            "endpoint": self.endpoint,
        }


class FipeService:
    def _cache_dir(self) -> Path:
        path = Path(current_app.config.get("FIPE_CACHE_DIR") or (current_app.config["PERSISTENT_DIR"] / "fipe_cache"))
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _json_path(self, nome: str) -> Path:
        return self._cache_dir() / nome

    def _bloqueados_path(self) -> Path:
        return self._json_path("modelos_bloqueados.json")

    def _marcas_bloqueadas_path(self) -> Path:
        return self._json_path("marcas_bloqueadas.json")

    def _modelos_zero_km_path(self) -> Path:
        return self._json_path("modelos_zero_km.json")

    def _marcas_varridas_path(self) -> Path:
        return self._json_path("marcas_varridas.json")

    def _usage_path(self) -> Path:
        return self._json_path("requisicoes_fipe.json")

    def _progresso_varredura_path(self) -> Path:
        return self._json_path("progresso_varredura.json")

    def _modelos_novos_path(self) -> Path:
        return self._json_path("modelos_novos.json")

    def _ler_json(self, path: Path, padrao):
        if not path.exists():
            return padrao
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return padrao

    def _salvar_json(self, path: Path, dados) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")

    def _ler_marcas_varridas(self) -> dict:
        return self._ler_json(self._marcas_varridas_path(), {})

    def _salvar_marcas_varridas(self, dados: dict) -> None:
        self._salvar_json(self._marcas_varridas_path(), dados)

    def marca_varrida(self, codigo_marca: str) -> bool:
        return str(codigo_marca) in set(map(str, self._ler_marcas_varridas().keys()))

    def marcar_marca_varrida(self, codigo_marca: str, nome_marca: str = "", modelos_validos: int = 0, modelos_bloqueados: int = 0) -> dict:
        dados = self._ler_marcas_varridas()
        marca_key = str(codigo_marca)
        dados[marca_key] = {
            "codigo_marca": marca_key,
            "marca": nome_marca,
            "modelos_validos": int(modelos_validos or 0),
            "modelos_bloqueados": int(modelos_bloqueados or 0),
            "status": "varrida",
            "atualizado_em": self._agora_iso(),
        }
        self._salvar_marcas_varridas(dados)
        self.limpar_progresso_varredura(marca_key)
        return {"ok": True, "marca_varrida": dados[marca_key]}

    def _ler_modelos_zero_km(self) -> dict:
        return self._ler_json(self._modelos_zero_km_path(), {})

    def _salvar_modelos_zero_km(self, dados: dict) -> None:
        self._salvar_json(self._modelos_zero_km_path(), dados)

    def _ler_modelos_novos(self) -> dict:
        return self._ler_json(self._modelos_novos_path(), {})

    def _salvar_modelos_novos(self, dados: dict) -> None:
        self._salvar_json(self._modelos_novos_path(), dados)

    def modelo_tem_zero_km_salvo(self, codigo_marca: str, codigo_modelo: str) -> bool:
        dados = self._ler_modelos_zero_km()
        return str(codigo_modelo) in set(map(str, dados.get(str(codigo_marca), {}).keys()))

    def marcar_modelo_zero_km(self, codigo_marca: str, codigo_modelo: str, nome_marca: str = "", nome_modelo: str = "") -> dict:
        dados = self._ler_modelos_zero_km()
        marca_key = str(codigo_marca)
        modelo_key = str(codigo_modelo)
        dados.setdefault(marca_key, {})[modelo_key] = {
            "codigo_marca": marca_key,
            "codigo_modelo": modelo_key,
            "marca": nome_marca,
            "modelo": nome_modelo,
            "tem_zero_km": True,
            "atualizado_em": self._agora_iso(),
        }
        self._salvar_modelos_zero_km(dados)
        return {"ok": True, "modelo_zero_km": dados[marca_key][modelo_key]}

    def desmarcar_modelo_zero_km(self, codigo_marca: str, codigo_modelo: str) -> dict:
        dados = self._ler_modelos_zero_km()
        marca_key = str(codigo_marca)
        modelo_key = str(codigo_modelo)
        removido = False
        if marca_key in dados and modelo_key in dados.get(marca_key, {}):
            dados[marca_key].pop(modelo_key, None)
            removido = True
            if not dados[marca_key]:
                dados.pop(marca_key, None)
            self._salvar_modelos_zero_km(dados)
        return {"ok": True, "removido": removido}

    def _ler_marcas_bloqueadas(self) -> dict:
        return self._ler_json(self._marcas_bloqueadas_path(), {})

    def _salvar_marcas_bloqueadas(self, dados: dict) -> None:
        self._salvar_json(self._marcas_bloqueadas_path(), dados)

    def marca_bloqueada(self, codigo_marca: str) -> bool:
        return str(codigo_marca) in set(map(str, self._ler_marcas_bloqueadas().keys()))

    def bloquear_marca_antiga(self, codigo_marca: str, nome_marca: str = "", motivo: str = "sem_modelos_2012_ou_zero_km") -> dict:
        dados = self._ler_marcas_bloqueadas()
        marca_key = str(codigo_marca)
        dados[marca_key] = {
            "codigo_marca": marca_key,
            "marca": nome_marca,
            "motivo": motivo,
            "bloqueado_em": self._agora_iso(),
        }
        self._salvar_marcas_bloqueadas(dados)
        varridas = self._ler_marcas_varridas()
        if marca_key in varridas:
            varridas.pop(marca_key, None)
            self._salvar_marcas_varridas(varridas)
        self.limpar_progresso_varredura(marca_key)
        return {"ok": True, "marca_bloqueada": dados[marca_key]}

    def desbloquear_marca(self, codigo_marca: str) -> dict:
        marca_key = str(codigo_marca)
        marcas_bloq = self._ler_marcas_bloqueadas()
        marca_removida = marcas_bloq.pop(marca_key, None) is not None
        self._salvar_marcas_bloqueadas(marcas_bloq)

        modelos_bloq = self._ler_bloqueados()
        modelos_removidos = len(modelos_bloq.get(marca_key, {}) or {})
        modelos_bloq.pop(marca_key, None)
        self._salvar_bloqueados(modelos_bloq)

        varridas = self._ler_marcas_varridas()
        varrida_removida = varridas.pop(marca_key, None) is not None
        self._salvar_marcas_varridas(varridas)

        self.limpar_progresso_varredura(marca_key)

        return {
            "ok": True,
            "codigo_marca": marca_key,
            "marca_bloqueada_removida": marca_removida,
            "modelos_bloqueados_removidos": modelos_removidos,
            "status_varrida_removido": varrida_removida,
        }

    def _ler_bloqueados(self) -> dict:
        return self._ler_json(self._bloqueados_path(), {})

    def _salvar_bloqueados(self, dados: dict) -> None:
        self._salvar_json(self._bloqueados_path(), dados)

    def modelo_bloqueado(self, codigo_marca: str, codigo_modelo: str) -> bool:
        dados = self._ler_bloqueados()
        return str(codigo_modelo) in set(map(str, dados.get(str(codigo_marca), {}).keys()))

    def bloquear_modelo_antigo(self, codigo_marca: str, codigo_modelo: str, nome_marca: str = "", nome_modelo: str = "", motivo: str = "sem_ano_2012_ou_zero_km") -> dict:
        dados = self._ler_bloqueados()
        marca_key = str(codigo_marca)
        modelo_key = str(codigo_modelo)
        dados.setdefault(marca_key, {})[modelo_key] = {
            "codigo_marca": marca_key,
            "codigo_modelo": modelo_key,
            "marca": nome_marca,
            "modelo": nome_modelo,
            "motivo": motivo,
            "bloqueado_em": self._agora_iso(),
        }
        self._salvar_bloqueados(dados)
        return {"ok": True, "bloqueado": dados[marca_key][modelo_key], "marca_bloqueada": False}

    def _usar_publica_apenas(self) -> bool:
        """Define se deve usar somente a FIPE pública v1.

        V24.7: quando há FIPE_TOKEN configurado, o padrão passa a ser API paga
        oficial v2. O modo público só é usado se FIPE_PUBLIC_ONLY=1 for
        explicitamente configurado.
        """
        bruto = os.environ.get("FIPE_PUBLIC_ONLY")
        if bruto is None:
            bruto = str(current_app.config.get("FIPE_PUBLIC_ONLY", False))
        return str(bruto).strip().lower() in {"1", "true", "sim", "yes", "on"}

    def _base_url(self) -> str:
        if self._usar_publica_apenas():
            return str(current_app.config.get("FIPE_PUBLIC_BASE_URL") or "https://parallelum.com.br/fipe/api/v1/carros")
        return str(current_app.config.get("FIPE_BASE_URL") or "https://fipe.parallelum.com.br/api/v2/cars")

    def _timeout(self) -> int:
        bruto = os.environ.get("FIPE_REQUEST_TIMEOUT") or current_app.config.get("REQUEST_TIMEOUT", 15)
        try:
            return max(5, min(60, int(bruto)))
        except Exception:
            return 15

    def _timeout_historico(self) -> int:
        bruto = os.environ.get("FIPE_HISTORICO_TIMEOUT") or current_app.config.get("FIPE_HISTORICO_TIMEOUT", self._timeout())
        try:
            return max(6, min(45, int(bruto)))
        except Exception:
            return max(12, self._timeout())

    def _token(self) -> str:
        token = os.environ.get("FIPE_TOKEN", "").strip()
        if token:
            return token
        # Alternativa segura: arquivo fora do GitHub, no disco persistente do Render.
        token_file = Path(current_app.config["PERSISTENT_DIR"]) / "fipe_token.txt"
        if token_file.exists():
            return token_file.read_text(encoding="utf-8").strip()
        return ""

    def _endpoint_v2(self, endpoint: str) -> str:
        endpoint = endpoint.strip("/")
        partes = endpoint.split("/") if endpoint else []
        if endpoint == "marcas":
            return "brands"
        if len(partes) == 3 and partes[0] == "marcas" and partes[2] == "modelos":
            return f"brands/{partes[1]}/models"
        if len(partes) == 5 and partes[0] == "marcas" and partes[2] == "modelos" and partes[4] == "anos":
            return f"brands/{partes[1]}/models/{partes[3]}/years"
        if len(partes) == 6 and partes[0] == "marcas" and partes[2] == "modelos" and partes[4] == "anos":
            return f"brands/{partes[1]}/models/{partes[3]}/years/{partes[5]}"
        return endpoint

    def _get_json(self, endpoint: str):
        base_url = self._base_url()
        token = self._token()
        # Se a URL for da API v2, traduzimos os endpoints internos do app.
        endpoint_final = self._endpoint_v2(endpoint) if "/api/v2" in base_url else endpoint
        return self._get_json_cached(base_url, endpoint_final, self._timeout(), token, str(self._cache_dir()))

    @staticmethod
    @lru_cache(maxsize=1024)
    def _get_json_cached(base_url: str, endpoint: str, timeout: int, token: str, cache_dir: str):
        url = f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        headers = {"Accept": "application/json", "User-Agent": "PlugVE-Web/24.7"}
        if token:
            headers["X-Subscription-Token"] = token
            headers["Authorization"] = f"Bearer {token}"
        try:
            FipeService._registrar_requisicao_static(Path(cache_dir), token_ativo=bool(token))
            resp = requests.get(url, timeout=timeout, headers=headers)
            if resp.status_code >= 400:
                FipeService._registrar_erro_static(Path(cache_dir), resp.status_code, url, resp.text[:300])
                if resp.status_code == 429:
                    raise FipeApiError("Limite diário da API FIPE atingido. Aguarde a janela de 24 horas ou use o token premium/gratuito ampliado.", 429, endpoint)
                if resp.status_code == 404:
                    raise FipeApiError("Recurso FIPE não encontrado para esta combinação marca/modelo/ano.", 404, endpoint)
                if resp.status_code in (401, 403):
                    raise FipeApiError("Token FIPE inválido, ausente ou sem permissão para esta consulta.", resp.status_code, endpoint)
                if resp.status_code == 402:
                    raise FipeApiError("API FIPE PRO recusou a consulta. Verifique se o token PRO está ativo e se o header foi aceito.", 402, endpoint)
                raise FipeApiError(f"Erro FIPE {resp.status_code}: {resp.text[:160]}", resp.status_code, endpoint)
            return resp.json()
        except FipeApiError:
            raise
        except requests.exceptions.Timeout:
            FipeService._registrar_erro_static(Path(cache_dir), None, url, "timeout")
            raise FipeApiError("Tempo esgotado ao consultar a FIPE. Tente novamente em alguns minutos.", None, endpoint)
        except requests.exceptions.RequestException as exc:
            FipeService._registrar_erro_static(Path(cache_dir), None, url, str(exc)[:300])
            raise FipeApiError("Falha de conexão ao consultar a FIPE.", None, endpoint)

    @staticmethod
    def _agora_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _ler_usage_static(cache_dir: Path) -> dict:
        path = cache_dir / "requisicoes_fipe.json"
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    @staticmethod
    def _salvar_usage_static(cache_dir: Path, dados: dict) -> None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / "requisicoes_fipe.json").write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _normalizar_janela_usage(dados: dict, token_ativo: bool) -> dict:
        agora = datetime.now(timezone.utc)
        inicio_str = dados.get("window_start")
        try:
            inicio = datetime.fromisoformat(inicio_str) if inicio_str else None
        except Exception:
            inicio = None
        if not inicio or agora - inicio >= timedelta(hours=24):
            dados = {
                "window_start": agora.isoformat(),
                "count": 0,
                "limit": 1000 if token_ativo else 500,
                "token_ativo": bool(token_ativo),
                "last_error": None,
            }
        dados["limit"] = 1000 if token_ativo else 500
        dados["token_ativo"] = bool(token_ativo)
        reset = datetime.fromisoformat(dados["window_start"]) + timedelta(hours=24)
        dados["reset_at"] = reset.isoformat()
        dados["remaining"] = max(0, int(dados.get("limit", 500)) - int(dados.get("count", 0)))
        return dados

    @staticmethod
    def _registrar_requisicao_static(cache_dir: Path, token_ativo: bool) -> None:
        dados = FipeService._normalizar_janela_usage(FipeService._ler_usage_static(cache_dir), token_ativo)
        dados["count"] = int(dados.get("count", 0)) + 1
        dados["last_request_at"] = FipeService._agora_iso()
        dados["remaining"] = max(0, int(dados.get("limit", 500)) - int(dados.get("count", 0)))
        FipeService._salvar_usage_static(cache_dir, dados)

    @staticmethod
    def _registrar_erro_static(cache_dir: Path, status_code: int | None, url: str, detalhe: str) -> None:
        dados = FipeService._normalizar_janela_usage(FipeService._ler_usage_static(cache_dir), token_ativo=True)
        dados["last_error"] = {
            "status_code": status_code,
            "url": url,
            "detalhe": detalhe,
            "at": FipeService._agora_iso(),
        }
        FipeService._salvar_usage_static(cache_dir, dados)


    def _api_root_v2(self) -> str:
        base = self._base_url().rstrip('/')
        if base.endswith('/cars') or base.endswith('/motorcycles') or base.endswith('/trucks'):
            return base.rsplit('/', 1)[0]
        return base

    def _headers(self) -> dict:
        token = self._token()
        if not token:
            return {}
        # A documentação usa X-Subscription-Token. O painel PRO também apresenta
        # a chave como bearer; enviamos ambos para compatibilidade do provedor.
        return {
            "X-Subscription-Token": token,
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "PlugVE-Web/24.7",
        }

    def listar_referencias(self) -> list[dict]:
        """Lista referências mensais da API FIPE v2. Conta como requisição FIPE."""
        cache_dir = self._cache_dir()
        url = f"{self._api_root_v2()}/references"
        try:
            self._registrar_requisicao_static(cache_dir, token_ativo=bool(self._token()))
            resp = requests.get(url, timeout=max(8, min(self._timeout(), 20)), headers=self._headers())
            if resp.status_code >= 400:
                self._registrar_erro_static(cache_dir, resp.status_code, url, resp.text[:300])
                raise FipeApiError(f"Erro FIPE {resp.status_code} ao consultar referências.", resp.status_code, "references")
            dados = resp.json()
            if not isinstance(dados, list):
                return []
            refs = []
            for r in dados:
                code = str(r.get('code') or r.get('codigo') or '').strip()
                month = str(r.get('month') or r.get('mes') or '').strip()
                if code.isdigit():
                    refs.append({'code': code, 'month': month})
            return sorted(refs, key=lambda x: int(x['code']))
        except FipeApiError:
            raise
        except requests.exceptions.Timeout:
            self._registrar_erro_static(cache_dir, None, url, 'timeout')
            raise FipeApiError("Tempo esgotado ao consultar referências da FIPE.", None, "references")
        except requests.exceptions.RequestException as exc:
            self._registrar_erro_static(cache_dir, None, url, str(exc)[:300])
            raise FipeApiError("Falha de conexão ao consultar referências da FIPE.", None, "references")



    def listar_marcas_referencia(self, reference: str) -> list[dict]:
        """Lista marcas dentro de uma referência mensal específica da API FIPE v2."""
        data = self._get_json_referencia("brands", str(reference), timeout_segundos=self._timeout_historico())
        return self._normalizar_marcas(data)

    def listar_anos_marca_referencia(self, codigo_marca: str, reference: str) -> list[dict]:
        """Lista anos disponíveis para uma marca dentro de uma referência mensal.

        Este endpoint é importante para reproduzir o fluxo do painel antigo:
        referência -> marca -> ano -> modelos -> preço.
        """
        data = self._get_json_referencia(f"brands/{codigo_marca}/years", str(reference), timeout_segundos=self._timeout_historico())
        return self._normalizar_anos(data)

    def listar_modelos_por_ano_referencia(self, codigo_marca: str, codigo_ano: str, reference: str) -> dict:
        """Lista modelos de uma marca/ano dentro de uma referência mensal."""
        data = self._get_json_referencia(f"brands/{codigo_marca}/years/{codigo_ano}/models", str(reference), timeout_segundos=self._timeout_historico())
        return self._normalizar_modelos(data)

    def _bases_historico_v2(self) -> list[str]:
        """Bases candidatas da API PRO v2 para histórico mensal.

        A documentação aceita fipe.parallelum.com.br/api/v2; o painel fipe.online
        também mostra api.fipe.online/api/v2. A V24.7 tenta a base configurada
        primeiro e, em timeout de histórico antigo, tenta a alternativa oficial.
        """
        bases = [str(self._base_url()).rstrip('/')]
        alt = os.environ.get("FIPE_ALT_BASE_URL") or current_app.config.get("FIPE_ALT_BASE_URL", "https://api.fipe.online/api/v2/cars")
        if alt:
            bases.append(str(alt).rstrip('/'))
        saida: list[str] = []
        for base in bases:
            if base and base not in saida:
                saida.append(base)
        return saida

    def _get_json_referencia(self, endpoint: str, reference: str, timeout_segundos: int | None = None):
        """GET na API FIPE v2 usando uma referência mensal específica.

        V24.7: histórico antigo pode demorar mais do que 4s. O timeout agora é
        configurável e, em timeout, tentamos uma segunda base oficial antes de
        desistir.
        """
        cache_dir = self._cache_dir()
        endpoint = endpoint.strip("/")
        timeout_real = int(timeout_segundos or self._timeout_historico())
        timeout_real = max(6, min(45, timeout_real))
        ultimo_timeout_url = ""
        ultimo_timeout_base = ""
        for pos, base in enumerate(self._bases_historico_v2(), start=1):
            url = f"{base.rstrip('/')}/{endpoint}"
            try:
                self._registrar_requisicao_static(cache_dir, token_ativo=bool(self._token()))
                resp = requests.get(
                    url,
                    timeout=timeout_real,
                    headers=self._headers(),
                    params={"reference": str(reference)},
                )
                if resp.status_code >= 400:
                    self._registrar_erro_static(cache_dir, resp.status_code, url, resp.text[:300])
                    if resp.status_code == 404:
                        raise FipeApiError("Recurso FIPE não encontrado nesta referência mensal.", 404, endpoint)
                    if resp.status_code == 429:
                        raise FipeApiError("Limite diário da API FIPE atingido durante coleta histórica.", 429, endpoint)
                    if resp.status_code in (401, 403):
                        raise FipeApiError("Token FIPE inválido, ausente ou sem permissão nesta consulta histórica.", resp.status_code, endpoint)
                    if resp.status_code == 402:
                        raise FipeApiError("API FIPE PRO recusou a consulta histórica. Confirme o token PRO no Render e a assinatura ativa.", 402, endpoint)
                    raise FipeApiError(f"Erro FIPE {resp.status_code} na consulta histórica.", resp.status_code, endpoint)
                dados = resp.json()
                if isinstance(dados, dict):
                    dados.setdefault("_plugve_api_base", base)
                return dados
            except FipeApiError:
                raise
            except requests.exceptions.Timeout:
                ultimo_timeout_url = url
                ultimo_timeout_base = base
                self._registrar_erro_static(cache_dir, None, url, f"timeout após {timeout_real}s; endpoint={endpoint}; reference={reference}; tentativa_base={pos}")
                # Tenta a próxima base antes de falhar.
                continue
            except requests.exceptions.RequestException as exc:
                self._registrar_erro_static(cache_dir, None, url, str(exc)[:300])
                raise FipeApiError(f"Falha de conexão ao consultar histórico FIPE em {endpoint} ref={reference}.", None, endpoint)
        detalhe = f"Tempo esgotado ao consultar histórico FIPE em {endpoint} ref={reference} após {timeout_real}s por base"
        if ultimo_timeout_base:
            detalhe += f"; última_base={ultimo_timeout_base}"
        if ultimo_timeout_url:
            detalhe += f"; última_url={ultimo_timeout_url}"
        raise FipeApiError(detalhe, None, endpoint)

    def listar_modelos_referencia(self, codigo_marca: str, reference: str) -> dict:
        """Lista modelos de uma marca em uma referência FIPE antiga."""
        data = self._get_json_referencia(f"brands/{codigo_marca}/models", reference, timeout_segundos=self._timeout_historico())
        return self._normalizar_modelos(data)

    def listar_anos_referencia(self, codigo_marca: str, codigo_modelo: str, reference: str) -> list[dict]:
        """Lista anos de um modelo em uma referência FIPE antiga."""
        data = self._get_json_referencia(f"brands/{codigo_marca}/models/{codigo_modelo}/years", reference, timeout_segundos=self._timeout_historico())
        return self._normalizar_anos(data)

    def consultar_preco_referencia(self, codigo_marca: str, codigo_modelo: str, codigo_ano: str, reference: str):
        """Consulta detalhe FIPE v2 em uma referência mensal específica. Conta como requisição FIPE."""
        endpoint = f"brands/{codigo_marca}/models/{codigo_modelo}/years/{codigo_ano}"
        data = self._get_json_referencia(endpoint, str(reference), timeout_segundos=self._timeout_historico())
        return self._normalizar_preco(data)

    def uso_requisicoes(self) -> dict:
        dados = self._normalizar_janela_usage(self._ler_usage_static(self._cache_dir()), token_ativo=bool(self._token()))
        self._salvar_usage_static(self._cache_dir(), dados)
        return dados


    @staticmethod
    def _contar_itens_aninhados(dados: Any) -> int:
        if not isinstance(dados, dict):
            return 0
        total = 0
        for valor in dados.values():
            if isinstance(valor, dict):
                total += len(valor)
            elif isinstance(valor, list):
                total += len(valor)
            elif valor:
                total += 1
        return total

    def catalogo_estado(self) -> dict:
        """Exporta o estado persistente da varredura FIPE para o painel local.

        Esta função não consulta a FIPE e não calcula depreciação. Ela só lê os
        JSONs persistentes em /var/data/plugve/fipe_cache. O contador de
        requisições FIPE não é incluído por decisão metodológica.
        """
        marcas_varridas = self._ler_marcas_varridas()
        marcas_bloqueadas = self._ler_marcas_bloqueadas()
        modelos_bloqueados = self._ler_bloqueados()
        modelos_zero_km = self._ler_modelos_zero_km()
        modelos_novos = self._ler_modelos_novos()
        progresso_varredura = self._ler_json(self._progresso_varredura_path(), {})

        return {
            "ok": True,
            "tipo": "catalogo_fipe_varredura",
            "schema_version": "catalogo_fipe_render_v1",
            "origem": "render",
            "atualizado_em": self._agora_iso(),
            "fipe_cache_dir": str(self._cache_dir()),
            "arquivos": {
                "marcas_varridas": "fipe_cache/marcas_varridas.json",
                "marcas_bloqueadas": "fipe_cache/marcas_bloqueadas.json",
                "modelos_bloqueados": "fipe_cache/modelos_bloqueados.json",
                "modelos_zero_km": "fipe_cache/modelos_zero_km.json",
                "modelos_novos": "fipe_cache/modelos_novos.json",
                "progresso_varredura": "fipe_cache/progresso_varredura.json",
            },
            "resumo": {
                "marcas_varridas": len(marcas_varridas) if isinstance(marcas_varridas, dict) else 0,
                "marcas_bloqueadas": len(marcas_bloqueadas) if isinstance(marcas_bloqueadas, dict) else 0,
                "modelos_bloqueados": self._contar_itens_aninhados(modelos_bloqueados),
                "modelos_zero_km": self._contar_itens_aninhados(modelos_zero_km),
                "modelos_novos": self._contar_itens_aninhados(modelos_novos),
                "marcas_com_progresso": len(progresso_varredura) if isinstance(progresso_varredura, dict) else 0,
            },
            "marcas_varridas": marcas_varridas if isinstance(marcas_varridas, dict) else {},
            "marcas_bloqueadas": marcas_bloqueadas if isinstance(marcas_bloqueadas, dict) else {},
            "modelos_bloqueados": modelos_bloqueados if isinstance(modelos_bloqueados, dict) else {},
            "modelos_zero_km": modelos_zero_km if isinstance(modelos_zero_km, dict) else {},
            "modelos_novos": modelos_novos if isinstance(modelos_novos, dict) else {},
            "progresso_varredura": progresso_varredura if isinstance(progresso_varredura, dict) else {},
        }

    def exportar_catalogo_estado(self) -> dict:
        """Alias mantido para compatibilidade com janelas/rotas futuras."""
        return self.catalogo_estado()

    def registrar_progresso_varredura(self, codigo_marca: str, dados: dict) -> dict:
        todos = self._ler_json(self._progresso_varredura_path(), {})
        key = str(codigo_marca)
        atual = dict(todos.get(key, {}))
        atual.update(dados or {})
        atual["codigo_marca"] = key
        atual["atualizado_em"] = self._agora_iso()
        todos[key] = atual
        self._salvar_json(self._progresso_varredura_path(), todos)
        return {"ok": True, "progresso": atual}

    def obter_progresso_varredura(self, codigo_marca: str) -> dict:
        todos = self._ler_json(self._progresso_varredura_path(), {})
        return todos.get(str(codigo_marca), {}) or {}

    def limpar_progresso_varredura(self, codigo_marca: str) -> dict:
        todos = self._ler_json(self._progresso_varredura_path(), {})
        removido = todos.pop(str(codigo_marca), None) is not None
        self._salvar_json(self._progresso_varredura_path(), todos)
        return {"ok": True, "removido": removido}

    def _normalizar_marcas(self, marcas: Any) -> list:
        if not isinstance(marcas, list):
            return []
        return [{"codigo": str(m.get("codigo", m.get("code", ""))), "nome": m.get("nome", m.get("name", ""))} for m in marcas]

    def _normalizar_modelos(self, data: Any) -> dict:
        if isinstance(data, dict):
            modelos = data.get("modelos") or data.get("models") or []
        else:
            modelos = data if isinstance(data, list) else []
        return {"modelos": [{"codigo": str(m.get("codigo", m.get("code", ""))), "nome": m.get("nome", m.get("name", ""))} for m in modelos]}

    def _normalizar_anos(self, anos: Any) -> list:
        if not isinstance(anos, list):
            return []
        return [{"codigo": str(a.get("codigo", a.get("code", ""))), "nome": a.get("nome", a.get("name", ""))} for a in anos]

    def _normalizar_preco(self, data: Any) -> dict:
        if not isinstance(data, dict):
            return {}
        if "Valor" in data or "CodigoFipe" in data:
            return data
        return {
            "Marca": data.get("brand", ""),
            "Modelo": data.get("model", ""),
            "AnoModelo": data.get("modelYear", ""),
            "Combustivel": data.get("fuel", ""),
            "CodigoFipe": data.get("codeFipe", ""),
            "Valor": data.get("price", ""),
            "MesReferencia": data.get("referenceMonth", ""),
            "TipoVeiculo": data.get("vehicleType", ""),
            "HistoricoPreco": data.get("priceHistory", []),
        }

    @staticmethod
    @lru_cache(maxsize=8)
    def _ler_marcas_curvas_eletricas_csv(path_str: str) -> tuple[str, ...]:
        marcas: set[str] = set()
        path = Path(path_str)
        if not path.exists():
            return tuple()
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    marca = (row.get("marca") or "").strip()
                    if not marca:
                        titulo = (row.get("titulo") or row.get("\ufefftitulo") or "").strip()
                        if titulo:
                            marca = titulo.split()[0]
                    if marca:
                        marcas.add(marca)
        except Exception:
            return tuple()
        return tuple(sorted(marcas))

    def _marcas_com_curvas_eletricas(self) -> set[str]:
        marcas: set[str] = set()
        for chave in ("ARQUIVO_CURVAS_ELETRICO", "ARQUIVO_CURVAS_ELETRICO_BASE"):
            path = current_app.config.get(chave)
            if path:
                marcas.update(self._ler_marcas_curvas_eletricas_csv(str(path)))
        return marcas

    def _nome_marca_por_codigo(self, codigo_marca: str) -> str:
        codigo_marca = str(codigo_marca or "").strip()
        if not codigo_marca:
            return ""
        try:
            for marca in self._normalizar_marcas(self._get_json("marcas")):
                if str(marca.get("codigo")) == codigo_marca:
                    return str(marca.get("nome") or "")
        except Exception:
            return ""
        return ""

    def listar_marcas(self, contexto: str | None = None):
        ctx = contexto_fipe(contexto or "")
        marcas = self._normalizar_marcas(self._get_json("marcas"))
        bloqueadas = self._ler_marcas_bloqueadas()
        varridas = self._ler_marcas_varridas()
        marcas_ev_extras = self._marcas_com_curvas_eletricas() if ctx == "ve" else set()
        resultado = []
        for marca in marcas:
            codigo = str(marca.get("codigo"))
            nome = marca.get("nome", "")
            if codigo in bloqueadas:
                continue
            if ctx and not marca_permitida_no_contexto(nome, ctx, extras_ve=marcas_ev_extras):
                continue
            item = dict(marca)
            item["marca_varrida"] = codigo in varridas
            item["contexto_fipe"] = ctx or "auto"
            resultado.append(item)
        return resultado

    def listar_modelos(self, codigo_marca: str, filtrar_bloqueados: bool = True, contexto: str | None = None, nome_marca: str = ""):
        ctx = contexto_fipe(contexto or "")
        data = self._normalizar_modelos(self._get_json(f"marcas/{codigo_marca}/modelos"))
        marca_nome = nome_marca or self._nome_marca_por_codigo(str(codigo_marca))
        if not filtrar_bloqueados and not ctx:
            return data
        bloqueados = self._ler_bloqueados().get(str(codigo_marca), {}) if filtrar_bloqueados else {}
        modelos = data.get("modelos", [])
        zero_km = self._ler_modelos_zero_km().get(str(codigo_marca), {})
        novos = self._ler_modelos_novos().get(str(codigo_marca), {})
        varridas = self._ler_marcas_varridas()
        modelos_filtrados = []
        ocultos_bloqueados = 0
        ocultos_contexto = 0
        for modelo in modelos:
            codigo_modelo = str(modelo.get("codigo"))
            if codigo_modelo in bloqueados:
                ocultos_bloqueados += 1
                continue
            item = dict(modelo)
            tipo_modelo = classificar_tipo_veiculo(item.get("nome", ""), marca=marca_nome)
            item["tipo_plugve"] = tipo_modelo
            item["contexto_fipe"] = ctx or "auto"
            if ctx and not tipo_permitido_no_contexto(ctx, tipo_modelo):
                ocultos_contexto += 1
                continue
            if codigo_modelo in zero_km:
                item["tem_zero_km"] = True
            if codigo_modelo in novos:
                item["modelo_novo"] = True
            item["marca_varrida"] = str(codigo_marca) in varridas
            modelos_filtrados.append(item)
        data["modelos"] = modelos_filtrados
        data["marca_varrida"] = str(codigo_marca) in varridas
        data["contexto_fipe"] = ctx or "auto"
        data["modelos_bloqueados_ocultos"] = ocultos_bloqueados
        data["modelos_ocultos_contexto"] = ocultos_contexto
        if filtrar_bloqueados and modelos and not data["modelos"] and bloqueados and not ctx:
            nome_marca = marca_nome
            try:
                if not nome_marca:
                    for marca in self.listar_marcas():
                        if str(marca.get("codigo")) == str(codigo_marca):
                            nome_marca = marca.get("nome", "")
                            break
            except Exception:
                pass
            self.bloquear_marca_antiga(str(codigo_marca), nome_marca)
            data["marca_bloqueada"] = True
        return data

    def listar_anos(self, codigo_marca: str, codigo_modelo: str, contexto: str | None = None):
        anos = self._normalizar_anos(self._get_json(f"marcas/{codigo_marca}/modelos/{codigo_modelo}/anos"))
        ctx = contexto_fipe(contexto or "")
        if ctx:
            for ano in anos:
                ano["contexto_fipe"] = ctx
        return anos

    def consultar_preco(self, codigo_marca: str, codigo_modelo: str, codigo_ano: str):
        return self._normalizar_preco(self._get_json(f"marcas/{codigo_marca}/modelos/{codigo_modelo}/anos/{codigo_ano}"))

    def listar_anos_por_codigo_fipe(self, codigo_fipe: str, reference: str | None = None) -> list[dict]:
        """Lista anos disponíveis usando o código FIPE do veículo.

        Endpoint documentado na API fipe.online/parallelum v2:
        GET /{vehicleType}/{fipeCode}/years

        Quando `reference` é informado, consulta os anos disponíveis naquela
        referência mensal. Isso é importante para montar histórico antigo sem
        depender do código de ano atual em meses passados.
        """
        codigo_fipe = str(codigo_fipe or "").strip()
        if not codigo_fipe:
            return []
        endpoint = f"{codigo_fipe}/years"
        if reference is None:
            data = self._get_json(endpoint)
        else:
            data = self._get_json_referencia(endpoint, str(reference), timeout_segundos=self._timeout_historico())
        return self._normalizar_anos(data)

    def consultar_detalhe_por_codigo_fipe(self, codigo_fipe: str, codigo_ano: str, reference: str | None = None) -> dict:
        """Consulta detalhe usando código FIPE + ano.

        Endpoint documentado:
        GET /{vehicleType}/{fipeCode}/years/{yearId}
        Quando `reference` é informado, consulta naquela referência mensal.
        """
        codigo_fipe = str(codigo_fipe or "").strip()
        codigo_ano = str(codigo_ano or "").strip()
        if not codigo_fipe or not codigo_ano:
            return {}
        endpoint = f"{codigo_fipe}/years/{codigo_ano}"
        if reference is None:
            return self._normalizar_preco(self._get_json(endpoint))
        return self._normalizar_preco(self._get_json_referencia(endpoint, str(reference), timeout_segundos=self._timeout_historico()))

    def consultar_historico_por_codigo_fipe(self, codigo_fipe: str, codigo_ano: str, reference: str | None = None) -> dict:
        """Consulta histórico de preços por código FIPE + ano.

        Este é o caminho prioritário para o novo motor, porque a documentação
        atual da API oferece o histórico diretamente:
        GET /{vehicleType}/{fipeCode}/years/{yearId}/history

        O retorno é normalizado para o padrão interno, mantendo `HistoricoPreco`.
        """
        codigo_fipe = str(codigo_fipe or "").strip()
        codigo_ano = str(codigo_ano or "").strip()
        if not codigo_fipe or not codigo_ano:
            return {}
        endpoint = f"{codigo_fipe}/years/{codigo_ano}/history"
        if reference is None:
            return self._normalizar_preco(self._get_json(endpoint))
        return self._normalizar_preco(self._get_json_referencia(endpoint, str(reference), timeout_segundos=self._timeout_historico()))
