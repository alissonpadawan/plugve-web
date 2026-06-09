from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path

from flask import current_app

from services.text_utils import parse_float_seguro


class IpcaRepository:
    def carregar_indices(self) -> dict[str, float]:
        caminho = Path(current_app.config["ARQUIVO_IPCA"])
        return dict(self._carregar_indices_cache(str(caminho)))

    @staticmethod
    @lru_cache(maxsize=4)
    def _carregar_indices_cache(caminho_str: str) -> tuple[tuple[str, float], ...]:
        caminho = Path(caminho_str)
        if not caminho.exists():
            return tuple()
        indices: dict[str, float] = {}
        with open(caminho, mode="r", encoding="utf-8-sig", newline="") as arquivo:
            for row in csv.DictReader(arquivo):
                data = str(row.get("data_referencia", "") or "").strip()
                if data:
                    indices[data] = parse_float_seguro(row.get("indice_ipca"), 0.0)
        return tuple(indices.items())
