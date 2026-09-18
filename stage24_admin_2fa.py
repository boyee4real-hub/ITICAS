import base64, io, secrets, hashlib
from datetime import datetime, timedelta, timezone
from fastapi import Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
import pyotp, qrcode
ISSUER="ITICAS"
PENDING_COOKIE="iticas_2fa_pending"
def _now(): return datetime.now(timezone.utc)
def _hash(x): return hashlib.sha256(x.encode()).hexdigest()
def _qr(uri):
    img=qrcode.make(uri); b=io.BytesIO(); img.save(b,format="PNG")
    return "data:image/png;base64,"+base64.b64encode(b.getvalue()).decode()
def install(app,db,COOKIE):
    with db() as c:
        c.execute("CREATE TABLE IF NOT EXISTS admin_totp (user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE, secret TEXT NOT NULL, enabled BOOLEAN NOT NULL DEFAULT FALSE, enrolled_at TEXT, last_verified_at TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS admin_2fa_challenges (token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, expires_at TEXT NOT NULL, purpose TEXT NOT NULL)")
        c.commit()
    def eligible(c,uid):
        u=c.execute("SELECT * FROM users WHERE id=?",(uid,)).fetchone()
        if not u or u["role"] not in ("admin","primary_admin") or u["status"]!="approved": raise HTTPException(403,"Administrator access required")
        return u
    def challenge(c,uid):
        raw=secrets.token_urlsafe(32); exp=(_now()+timedelta(minutes=5)).isoformat()
        c.execute("DELETE FROM admin_2fa_challenges WHERE user_id=?",(uid,))
        c.execute("INSERT INTO admin_2fa_challenges(token_hash,user_id,expires_at,purpose) VALUES(?,?,?,?)",(_hash(raw),uid,exp,"login")); c.commit()
        return raw
    def pending(req,c):
        raw=req.cookies.get(PENDING_COOKIE)
        if not raw: raise HTTPException(401,"Authentication challenge expired")
        r=c.execute("SELECT * FROM admin_2fa_challenges WHERE token_hash=?",(_hash(raw),)).fetchone()
        if not r: raise HTTPException(401,"Authentication challenge expired")
        if datetime.fromisoformat(r["expires_at"])<_now(): raise HTTPException(401,"Authentication challenge expired")
        return r
    @app.get("/admin/2fa",response_class=HTMLResponse)
    def page(request:Request):
        with db() as c:
            ch=pending(request,c); u=eligible(c,ch["user_id"])
            t=c.execute("SELECT * FROM admin_totp WHERE user_id=?",(u["id"],)).fetchone()
            if not t:
                sec=pyotp.random_base32(); c.execute("INSERT INTO admin_totp(user_id,secret,enabled) VALUES(?,?,FALSE)",(u["id"],sec)); c.commit()
                t=c.execute("SELECT * FROM admin_totp WHERE user_id=?",(u["id"],)).fetchone()
            if not t["enabled"]:
                uri=pyotp.TOTP(t["secret"]).provisioning_uri(name=u["username"],issuer_name=ISSUER)
                body='<h1>ITICAS Administrator Authenticator Setup</h1><p>Scan this QR code once, then enter the current 6-digit code.</p><img src="'+_qr(uri)+'" width="260" height="260" alt="Authenticator QR">'
            else:
                body='<h1>ITICAS Administrator Verification</h1><p>Enter the current 6-digit code from your authenticator app.</p>'
            body += '<form method="post" action="/admin/2fa/verify"><input name="code" maxlength="6" pattern="[0-9]{6}" inputmode="numeric" autocomplete="one-time-code" required><button>Verify</button></form>'
        return HTMLResponse("<!doctype html><html><head><title>ITICAS Admin 2FA</title></head><body>"+body+"</body></html>",headers={"Cache-Control":"no-store","Pragma":"no-cache"})
    @app.post("/admin/2fa/verify")
    def verify(request:Request,code:str=Form(...)):
        if len(code)!=6 or not code.isdigit(): raise HTTPException(400,"Enter a valid 6-digit code")
        with db() as c:
            ch=pending(request,c); u=eligible(c,ch["user_id"]); t=c.execute("SELECT * FROM admin_totp WHERE user_id=?",(u["id"],)).fetchone()
            if not t or not pyotp.TOTP(t["secret"]).verify(code,valid_window=1): raise HTTPException(401,"Invalid authentication code")
            stamp=_now().isoformat(); c.execute("UPDATE admin_totp SET enabled=TRUE,enrolled_at=COALESCE(enrolled_at,?),last_verified_at=? WHERE user_id=?",(stamp,stamp,u["id"]))
            c.execute("DELETE FROM admin_2fa_challenges WHERE token_hash=?",(_hash(request.cookies.get(PENDING_COOKIE)),))
            raw=secrets.token_urlsafe(32); exp=(_now()+timedelta(hours=12)).isoformat()
            c.execute("INSERT INTO admin_sessions(token_hash,user_id,expires_at) VALUES(?,?,?)",(_hash(raw),u["id"],exp)); c.commit()
        r=RedirectResponse("/admin",303); r.set_cookie(COOKIE,raw,httponly=True,samesite="strict",secure=True,max_age=43200); r.delete_cookie(PENDING_COOKIE); return r
    app.state.iticas_2fa_challenge=challenge
    app.state.iticas_2fa_cookie=PENDING_COOKIE
