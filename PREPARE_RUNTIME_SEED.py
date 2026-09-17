from __future__ import annotations
import shutil
import sqlite3
from pathlib import Path

SOURCE = Path(r"C:\iticas\database\iticas.db")
OUT = Path("runtime_seed") / "iticas_seed.db"

if not SOURCE.exists():
    raise SystemExit(f"[FAIL] Certified source database not found: {SOURCE}")

OUT.parent.mkdir(parents=True, exist_ok=True)
shutil.copy2(SOURCE, OUT)

conn = sqlite3.connect(OUT)
conn.execute("PRAGMA foreign_keys=OFF")
tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}

for table in ("auth_sessions", "user_permissions", "audit_logs", "password_reset_tokens", "users"):
    if table in tables:
        conn.execute(f'DELETE FROM "{table}"')

if "sqlite_sequence" in tables:
    for table in ("auth_sessions", "user_permissions", "audit_logs", "password_reset_tokens", "users"):
        conn.execute("DELETE FROM sqlite_sequence WHERE name=?", (table,))

conn.commit()
conn.execute("VACUUM")

loc = conn.execute("SELECT COUNT(*) FROM monitoring_locations").fetchone()[0] if "monitoring_locations" in tables else 0
obs = conn.execute("SELECT COUNT(*) FROM traffic_observations").fetchone()[0] if "traffic_observations" in tables else 0
usr = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] if "users" in tables else 0
conn.close()

print(f"[PASS] Sanitized runtime seed created: {OUT}")
print(f"       LOCATIONS={loc}")
print(f"       TRAFFIC_OBSERVATIONS={obs}")
print(f"       USERS={usr} (must be 0)")
