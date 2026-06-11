from __future__ import annotations

import os
from pathlib import Path


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "plugve-depreciacao-v23")

    BASE_DIR = Path(__file__).resolve().parent
    DATA_DIR = BASE_DIR / "data"

    # No Render, o disco persistente foi montado em /var/data.
    # Tudo que for aprendido/calculado em produção deve ser salvo em /var/data/plugve.
    # Localmente, se /var/data não existir, usa data/_runtime apenas para teste.
    _DEFAULT_PERSISTENT_DIR = Path("/var/data/plugve") if Path("/var/data").exists() else DATA_DIR / "_runtime"
    PERSISTENT_DIR = Path(os.environ.get("PLUGVE_PERSISTENT_DIR", str(_DEFAULT_PERSISTENT_DIR)))
    FIPE_CACHE_DIR = PERSISTENT_DIR / "fipe_cache"

    ARQUIVO_FAMILIAS = DATA_DIR / "familias_fipe.xlsx"
    ARQUIVO_IPCA = DATA_DIR / "comum" / "inflacao_ipca.csv"

    # Bases versionadas no GitHub: usadas como semente inicial.
    ARQUIVO_CURVAS_COMBUSTAO_BASE = DATA_DIR / "combustao" / "curvas_depreciacao_v18.csv"
    ARQUIVO_CURVAS_ELETRICO_BASE = DATA_DIR / "eletrico" / "curvas_depreciacao_ev_v20.csv"

    # Bases de trabalho persistentes: lidas e atualizadas pelo sistema online.
    ARQUIVO_CURVAS_COMBUSTAO = PERSISTENT_DIR / "combustao" / "curvas_depreciacao_v18.csv"
    ARQUIVO_CURVAS_ELETRICO = PERSISTENT_DIR / "eletrico" / "curvas_depreciacao_ev_v20.csv"

    # Históricos e IPCA continuam como bases iniciais versionadas.
    ARQUIVO_HISTORICO_COMBUSTAO = DATA_DIR / "combustao" / "historico_fipe_sob_demanda_v18.csv"
    ARQUIVO_HISTORICO_ELETRICO = DATA_DIR / "eletrico" / "historico_fipe_ev_v20.csv"

    FIPE_BASE_URL = os.environ.get("FIPE_BASE_URL", "https://fipe.parallelum.com.br/api/v2/cars")
    # Token da fipe.online deve ficar no Render como FIPE_TOKEN, não no GitHub.
    REQUEST_TIMEOUT = 15

    HORIZONTE_PADRAO_ANOS = 5
