from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Iterable


class SQLiteMigrationBackupError(RuntimeError):
    pass


def table_columns(database_path: str | Path, table: str) -> set[str]:
    path = Path(database_path)
    if not path.exists() or path.stat().st_size == 0:
        return set()
    con = sqlite3.connect(path, timeout=10)
    try:
        rows = con.execute(f"PRAGMA table_info({table})").fetchall()
        return {str(row[1]) for row in rows}
    finally:
        con.close()


def needs_columns(database_path: str | Path, requirements: dict[str, Iterable[str]]) -> bool:
    path = Path(database_path)
    if not path.exists() or path.stat().st_size == 0:
        return False
    for table, required in requirements.items():
        existing = table_columns(path, table)
        if existing and any(str(column) not in existing for column in required):
            return True
    return False


def create_sqlite_backup_once(database_path: str | Path, *, migration_label: str) -> Path | None:
    """Cria cópia consistente antes de migração destravadora de schema.

    Usa a API de backup do SQLite, portanto inclui o estado consistente do WAL.
    O nome é estável por migração: reinícios/deploys não produzem cópias infinitas.
    """
    source = Path(database_path)
    if not source.exists() or source.stat().st_size == 0:
        return None

    safe_label = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(migration_label))
    backup_dir = source.parent / "migration_backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"{source.stem}_pre_{safe_label}.sqlite3"
    if target.exists() and target.stat().st_size > 0:
        return target

    tmp = target.with_suffix(target.suffix + ".tmp")
    if tmp.exists():
        tmp.unlink()

    src = sqlite3.connect(source, timeout=15)
    dst = sqlite3.connect(tmp, timeout=15)
    try:
        src.backup(dst)
        row = dst.execute("PRAGMA quick_check").fetchone()
        if not row or str(row[0]).lower() != "ok":
            raise SQLiteMigrationBackupError(f"Backup SQLite inválido para {source.name}: {row}")
        dst.commit()
    except Exception:
        try:
            dst.close()
        finally:
            src.close()
        if tmp.exists():
            tmp.unlink()
        raise
    else:
        dst.close()
        src.close()

    os.replace(tmp, target)
    return target


def verify_sqlite_integrity(database_path: str | Path) -> None:
    path = Path(database_path)
    if not path.exists() or path.stat().st_size == 0:
        return
    con = sqlite3.connect(path, timeout=15)
    try:
        row = con.execute("PRAGMA quick_check").fetchone()
        if not row or str(row[0]).lower() != "ok":
            raise SQLiteMigrationBackupError(f"Falha de integridade SQLite em {path.name}: {row}")
    finally:
        con.close()
