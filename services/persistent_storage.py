from __future__ import annotations

import shutil
from pathlib import Path
from flask import Flask


def _copy_if_missing(src: Path, dst: Path) -> None:
    """Copia a base inicial versionada para o disco persistente apenas se ainda não existir."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        return
    if src.exists():
        shutil.copy2(src, dst)
    else:
        # cria arquivo vazio só para garantir que o app não quebre ao abrir para escrita
        dst.touch()


def bootstrap_persistent_storage(app: Flask) -> None:
    """Prepara o armazenamento persistente do PlugVE.

    No Render, o disco foi montado em /var/data. Tudo que precisa sobreviver a
    deploy/restart deve ficar em /var/data/plugve. A pasta data/ do GitHub passa
    a ser apenas a base inicial de referência.
    """
    persistent_dir = Path(app.config["PERSISTENT_DIR"])
    persistent_dir.mkdir(parents=True, exist_ok=True)

    # Subpastas persistentes usadas pelo sistema
    for relative in ["combustao", "eletrico", "fipe_cache"]:
        (persistent_dir / relative).mkdir(parents=True, exist_ok=True)

    # Copia as curvas iniciais do GitHub para o disco persistente somente na primeira vez.
    _copy_if_missing(
        Path(app.config["ARQUIVO_CURVAS_COMBUSTAO_BASE"]),
        Path(app.config["ARQUIVO_CURVAS_COMBUSTAO"]),
    )
    _copy_if_missing(
        Path(app.config["ARQUIVO_CURVAS_ELETRICO_BASE"]),
        Path(app.config["ARQUIVO_CURVAS_ELETRICO"]),
    )

    # Arquivos permanentes de aprendizado da FIPE.
    for nome in ["modelos_bloqueados.json", "marcas_bloqueadas.json", "modelos_zero_km.json", "marcas_varridas.json", "requisicoes_fipe.json", "progresso_varredura.json"]:
        path = persistent_dir / "fipe_cache" / nome
        if not path.exists():
            path.write_text("{}", encoding="utf-8")
