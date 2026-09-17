from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

from .paths import ASSET_ROOT, DATA_ROOT

SECURITY_TABLES = {
    "users",
    "user_permissions",
    "auth_sessions",
    "audit_logs",
    "password_reset_tokens",
}

def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone() is not None

def _count(conn: sqlite3.Connection, table: str) -> int:
    if not _table_exists(conn, table):
        return 0
    return int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])

def bootstrap_runtime_database() -> None:
    """Seed a fresh/empty runtime database without overwriting local identities.

    The bundled seed is created at build time from the certified operational DB
    after security tables are cleared. If an installed DB already contains user
    accounts but no operational locations, those identity rows are preserved
    while the certified operational seed replaces the empty DB.
    """
    target = DATA_ROOT / "database" / "iticas.db"
    seed = ASSET_ROOT / "runtime_seed" / "iticas_seed.db"
    if not seed.exists():
        return

    target.parent.mkdir(parents=True, exist_ok=True)

    if not target.exists():
        shutil.copy2(seed, target)
        return

    try:
        current = sqlite3.connect(target)
        if _count(current, "monitoring_locations") > 0:
            current.close()
            return

        preserved = {}
        for table in ("users", "user_permissions"):
            if _table_exists(current, table):
                cur = current.execute(f'SELECT * FROM "{table}"')
                cols = [d[0] for d in cur.description]
                preserved[table] = (cols, cur.fetchall())
        current.close()

        shutil.copy2(seed, target)

        if preserved:
            restored = sqlite3.connect(target)
            restored.execute("PRAGMA foreign_keys=OFF")
            for table, (cols, rows) in preserved.items():
                if not rows or not _table_exists(restored, table):
                    continue
                placeholders = ",".join("?" for _ in cols)
                col_sql = ",".join(f'"{c}"' for c in cols)
                restored.executemany(
                    f'INSERT OR REPLACE INTO "{table}" ({col_sql}) VALUES ({placeholders})',
                    rows,
                )
            restored.commit()
            restored.close()
    except Exception:
        # Never destroy an existing runtime DB on a bootstrap error.
        return
