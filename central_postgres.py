from __future__ import annotations
import os
DATABASE_URL=(os.environ.get("ITICAS_CENTRAL_DATABASE_URL") or "").strip()
def connect():
    if not DATABASE_URL:
        raise RuntimeError("ITICAS_CENTRAL_DATABASE_URL is required for production central access.")
    import psycopg
    return psycopg.connect(DATABASE_URL,autocommit=False)
def init_schema():
    statements=[
"""CREATE TABLE IF NOT EXISTS users(id BIGSERIAL PRIMARY KEY,username TEXT NOT NULL,email TEXT NOT NULL,password_hash TEXT NOT NULL,full_name TEXT,organisation TEXT,phone TEXT,intended_use TEXT,role TEXT NOT NULL DEFAULT 'user',status TEXT NOT NULL DEFAULT 'pending',permissions_json TEXT NOT NULL DEFAULT '[]',created_at TEXT,approved_at TEXT,rejected_at TEXT,last_login_at TEXT)""",
"CREATE UNIQUE INDEX IF NOT EXISTS ux_iticas_users_username_lower ON users(lower(username))",
"CREATE UNIQUE INDEX IF NOT EXISTS ux_iticas_users_email_lower ON users(lower(email))",
"""CREATE TABLE IF NOT EXISTS admin_sessions(id BIGSERIAL PRIMARY KEY,token_hash TEXT UNIQUE NOT NULL,user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,expires_at TEXT NOT NULL,created_at TEXT)""",
"""CREATE TABLE IF NOT EXISTS audit(id BIGSERIAL PRIMARY KEY,occurred_at TEXT,action TEXT,actor_user_id BIGINT,target_user_id BIGINT,details_json TEXT)"""
]
    with connect() as c:
        with c.cursor() as cur:
            for s in statements: cur.execute(s)
        c.commit()
class Row(dict): pass
class CursorCompat:
    def __init__(self,cur): self.cur=cur
    def execute(self,sql,params=()):
        self.cur.execute(sql.replace("?","%s"),params); return self
    def fetchone(self):
        r=self.cur.fetchone()
        if r is None:return None
        return Row(zip([d.name for d in self.cur.description],r))
    def fetchall(self):
        rows=self.cur.fetchall(); cols=[d.name for d in self.cur.description]
        return [Row(zip(cols,r)) for r in rows]
class ConnCompat:
    def __init__(self): self.conn=connect(); self.cur=self.conn.cursor()
    def execute(self,sql,params=()): return CursorCompat(self.cur).execute(sql,params)
    def commit(self): self.conn.commit()
    def __enter__(self): return self
    def __exit__(self,t,v,b):
        try:
            if t:self.conn.rollback()
        finally:self.cur.close(); self.conn.close()
def db(): return ConnCompat()
def health():
    with connect() as c:
        with c.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM users WHERE status='pending'"); p=cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM users WHERE status='approved'"); a=cur.fetchone()[0]
    return {"backend":"postgresql","persistent":True,"connection":"ok","pending":p,"approved":a}
