from __future__ import annotations

import os
from pathlib import Path
from datetime import timedelta


def _is_production_runtime() -> bool:
    return (
        str(os.environ.get("RENDER", "")).strip().lower() in {"1", "true", "yes", "on"}
        or str(os.environ.get("FLASK_ENV", "")).strip().lower() == "production"
    )


def _resolve_secret_key() -> str:
    configured = str(os.environ.get("SECRET_KEY", "") or "").strip()
    if configured:
        return configured
    if _is_production_runtime():
        raise RuntimeError(
            "SECRET_KEY não configurada no ambiente de produção. "
            "Defina um segredo exclusivo no Render antes de iniciar a aplicação."
        )
    # Fallback exclusivamente local/teste. Nunca deve ser usado em produção.
    return "curve-local-dev-only-secret"


class Config:
    SECRET_KEY = _resolve_secret_key()

    BASE_DIR = Path(__file__).resolve().parent
    DATA_DIR = BASE_DIR / "data"

    # No Render, o disco persistente foi montado em /var/data.
    # Tudo que for aprendido/calculado em produção deve ser salvo em /var/data/plugve.
    # Localmente, se /var/data não existir, usa data/_runtime apenas para teste.
    _DEFAULT_PERSISTENT_DIR = Path("/var/data/plugve") if Path("/var/data").exists() else DATA_DIR / "_runtime"
    PERSISTENT_DIR = Path(os.environ.get("PLUGVE_PERSISTENT_DIR", str(_DEFAULT_PERSISTENT_DIR)))
    ARQUIVO_SOBRE_ENGAJAMENTO = PERSISTENT_DIR / "institucional" / "sobre_engagement.sqlite3"
    ARQUIVO_USO_SITE = PERSISTENT_DIR / "institucional" / "site_usage.sqlite3"
    ARQUIVO_MENSAGENS_CONTATO = PERSISTENT_DIR / "institucional" / "contact_messages.sqlite3"

    PERMANENT_SESSION_LIFETIME = timedelta(days=365)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    FIPE_CACHE_DIR = PERSISTENT_DIR / "fipe_cache"

    ARQUIVO_FAMILIAS = DATA_DIR / "familias_fipe.xlsx"
    ARQUIVO_IPCA = DATA_DIR / "comum" / "inflacao_ipca.csv"

    # Base PBEV/Inmetro saneada V1 usada apenas pelo site para sugerir consumo editável.
    PBEV_DIR = DATA_DIR / "pbev"
    ARQUIVO_PBEV_BASE = PBEV_DIR / "pbev_base_saneada_v1.json"
    ARQUIVO_PBEV_MANIFEST = PBEV_DIR / "pbev_manifest_validacao_v1.json"

    # Bases versionadas no GitHub: usadas como semente inicial.
    ARQUIVO_CURVAS_COMBUSTAO_BASE = DATA_DIR / "combustao" / "curvas_depreciacao_v18.csv"
    ARQUIVO_CURVAS_ELETRICO_BASE = DATA_DIR / "eletrico" / "curvas_depreciacao_ev_v20.csv"

    # Bases de trabalho persistentes: lidas e atualizadas pelo sistema online.
    ARQUIVO_CURVAS_COMBUSTAO = PERSISTENT_DIR / "combustao" / "curvas_depreciacao_v18.csv"
    ARQUIVO_CURVAS_ELETRICO = PERSISTENT_DIR / "eletrico" / "curvas_depreciacao_ev_v20.csv"

    # Históricos e IPCA continuam como bases iniciais versionadas.
    ARQUIVO_HISTORICO_COMBUSTAO = DATA_DIR / "combustao" / "historico_fipe_sob_demanda_v18.csv"
    ARQUIVO_HISTORICO_ELETRICO = DATA_DIR / "eletrico" / "historico_fipe_ev_v20.csv"

    # V24.7: motor V19.17 online usando API PRO oficial por referência mensal.
    # A FIPE Web pública funciona no desktop local, mas bloqueia o Render com 403.
    # Mantemos a pública v1 apenas como fallback para telas simples quando não houver token.
    FIPE_PUBLIC_BASE_URL = "https://parallelum.com.br/fipe/api/v1/carros"
    FIPE_PUBLIC_ONLY = os.environ.get("FIPE_PUBLIC_ONLY", "0").strip().lower() in {"1", "true", "sim", "yes", "on"}
    FIPE_BASE_URL = os.environ.get("FIPE_BASE_URL", "https://fipe.parallelum.com.br/api/v2/cars")
    # Base alternativa mostrada no painel fipe.online. Usada apenas se a base principal der timeout em histórico antigo.
    FIPE_ALT_BASE_URL = os.environ.get("FIPE_ALT_BASE_URL", "https://api.fipe.online/api/v2/cars")
    REQUEST_TIMEOUT = int(os.environ.get("FIPE_REQUEST_TIMEOUT", "15"))
    FIPE_HISTORICO_TIMEOUT = int(os.environ.get("FIPE_HISTORICO_TIMEOUT", "12"))
    # Catálogo (marcas/modelos/anos) é estável e pode ser mantido no disco
    # persistente do Render. O preço final também recebe cache curto para evitar
    # travamentos em cold start, sem alterar códigos ou metodologia FIPE.
    FIPE_CATALOG_CACHE_TTL_SECONDS = int(os.environ.get("FIPE_CATALOG_CACHE_TTL_SECONDS", "604800"))
    FIPE_PRICE_CACHE_TTL_SECONDS = int(os.environ.get("FIPE_PRICE_CACHE_TTL_SECONDS", "21600"))

    # Token simples para sincronização de leitura painel local -> Render.
    # Configure PLUGVE_SYNC_TOKEN no Render com o mesmo valor do painel local.
    PLUGVE_SYNC_TOKEN = os.environ.get("PLUGVE_SYNC_TOKEN", "").strip()
    # O token administrativo é deliberadamente separado do token de sincronização.
    # Não faça fallback para PLUGVE_SYNC_TOKEN: quem pode sincronizar dados não deve
    # ganhar acesso ao painel de telemetria por consequência.
    PLUGVE_ADMIN_TOKEN = os.environ.get("PLUGVE_ADMIN_TOKEN", "").strip()

    # Envio direto da página Contato. Para Gmail, use uma senha de aplicativo
    # e mantenha as credenciais apenas nas variáveis de ambiente do Render.
    CONTACT_TO_EMAIL = os.environ.get("CONTACT_TO_EMAIL", "sv.alisson@gmail.com").strip()
    CONTACT_FROM_EMAIL = os.environ.get("CONTACT_FROM_EMAIL", CONTACT_TO_EMAIL).strip()
    CONTACT_SMTP_HOST = os.environ.get("CONTACT_SMTP_HOST", "smtp.gmail.com").strip()
    CONTACT_SMTP_PORT = int(os.environ.get("CONTACT_SMTP_PORT", "587"))
    CONTACT_SMTP_USERNAME = os.environ.get("CONTACT_SMTP_USERNAME", "").strip()
    CONTACT_SMTP_PASSWORD = os.environ.get("CONTACT_SMTP_PASSWORD", "").strip()
    CONTACT_SMTP_USE_TLS = os.environ.get("CONTACT_SMTP_USE_TLS", "1").strip().lower() in {"1", "true", "sim", "yes", "on"}
    CONTACT_SMTP_USE_SSL = os.environ.get("CONTACT_SMTP_USE_SSL", "0").strip().lower() in {"1", "true", "sim", "yes", "on"}
    CONTACT_SMTP_TIMEOUT = int(os.environ.get("CONTACT_SMTP_TIMEOUT", "20"))
    CONTACT_RATE_LIMIT_SECONDS = int(os.environ.get("CONTACT_RATE_LIMIT_SECONDS", "60"))

    HORIZONTE_PADRAO_ANOS = 5
