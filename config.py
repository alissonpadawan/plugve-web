from __future__ import annotations

import os
from pathlib import Path


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "plugve-depreciacao-v23")

    BASE_DIR = Path(__file__).resolve().parent
    DATA_DIR = BASE_DIR / "data"

    ARQUIVO_FAMILIAS = DATA_DIR / "familias_fipe.xlsx"
    ARQUIVO_IPCA = DATA_DIR / "comum" / "inflacao_ipca.csv"

    ARQUIVO_CURVAS_COMBUSTAO = DATA_DIR / "combustao" / "curvas_depreciacao_v18.csv"
    ARQUIVO_HISTORICO_COMBUSTAO = DATA_DIR / "combustao" / "historico_fipe_sob_demanda_v18.csv"

    ARQUIVO_CURVAS_ELETRICO = DATA_DIR / "eletrico" / "curvas_depreciacao_ev_v20.csv"
    ARQUIVO_HISTORICO_ELETRICO = DATA_DIR / "eletrico" / "historico_fipe_ev_v20.csv"

    FIPE_BASE_URL = "https://parallelum.com.br/fipe/api/v1/carros"
    REQUEST_TIMEOUT = 15

    HORIZONTE_PADRAO_ANOS = 5
