from pathlib import Path
import sqlite3,json
from datetime import datetime,timezone
src=sqlite3.connect(r"C:\iticas\database\iticas.db"); src.row_factory=sqlite3.Row
dst=sqlite3.connect(r"C:\ITICAS_BUILD\ITICAS_v0.26.3_WINDOWS_DISTRIBUTION_KIT\source\ITICAS_v0.26.3_DISTRIBUTION_SOURCE\central_access.db")
dst.executescript("""CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT,username TEXT UNIQUE COLLATE NOCASE,email TEXT UNIQUE COLLATE NOCASE,password_hash TEXT,full_name TEXT,organisation TEXT,phone TEXT,intended_use TEXT,role TEXT DEFAULT 'user',status TEXT DEFAULT 'pending',permissions_json TEXT DEFAULT '[]',created_at TEXT,approved_at TEXT,rejected_at TEXT,last_login_at TEXT);CREATE TABLE IF NOT EXISTS admin_sessions(id INTEGER PRIMARY KEY AUTOINCREMENT,token_hash TEXT UNIQUE,user_id INTEGER,expires_at TEXT,created_at TEXT);CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT,occurred_at TEXT,action TEXT,actor_user_id INTEGER,target_user_id INTEGER,details_json TEXT);""")
perms=["traffic:view","traffic:acquire","monitoring:view","monitoring:run","locations:view","analytics:view","prediction:run","reports:view","reports:export","validation:view"]
for r in src.execute("SELECT username,email,password_hash,role,status FROM users WHERE status='approved'").fetchall():
    dst.execute("INSERT OR IGNORE INTO users(username,email,password_hash,role,status,permissions_json,created_at,approved_at) VALUES(?,?,?,?,?,?,?,?)",(r["username"],r["email"],r["password_hash"],r["role"],"approved",json.dumps([] if r["role"]=="admin" else perms),datetime.now(timezone.utc).isoformat(),datetime.now(timezone.utc).isoformat()))
dst.commit(); print("[PASS] Approved central test identities:",dst.execute("SELECT COUNT(*) FROM users WHERE status='approved'").fetchone()[0]); dst.close(); src.close()
