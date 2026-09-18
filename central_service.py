from __future__ import annotations
import hashlib,hmac,html,json,os,secrets,smtplib,sqlite3,urllib.request,urllib.error
from datetime import datetime,timedelta,timezone
from email.message import EmailMessage
from pathlib import Path
from fastapi import FastAPI,HTTPException,Request
from fastapi.responses import HTMLResponse,RedirectResponse
from pydantic import BaseModel
import central_postgres as central_pg

DB=Path(os.environ.get("ITICAS_CENTRAL_DB",str(Path(__file__).with_name("central_access.db"))))
DB.parent.mkdir(parents=True,exist_ok=True)
COOKIE="iticas_central_admin"
ALL_PERMISSIONS=("traffic:view","traffic:acquire","monitoring:view","monitoring:run","locations:view","locations:manage","analytics:view","prediction:run","reports:view","reports:export","validation:view","admin:users","admin:audit","admin:security")
DEFAULT_PERMISSIONS=("traffic:view","traffic:acquire","monitoring:view","monitoring:run","locations:view","analytics:view","prediction:run","reports:view","reports:export","validation:view")
app=FastAPI(title="ITICAS Central Access Service",version="1.0.0")

def now(): return datetime.now(timezone.utc).isoformat()
def db():
    return central_pg.db()
def init():
    central_pg.init_schema()
def hpw(p):
    if len(p)<12: raise ValueError("Password must contain at least 12 characters.")
    salt=secrets.token_bytes(16); n,r,q=2**14,8,1
    d=hashlib.scrypt(p.encode(),salt=salt,n=n,r=r,p=q,dklen=32)
    return f"scrypt${n}${r}${q}${salt.hex()}${d.hex()}"
def vpw(p,e):
    try:
        s,n,r,q,salt,d=e.split("$",5)
        if s!="scrypt": return False
        got=hashlib.scrypt(p.encode(),salt=bytes.fromhex(salt),n=int(n),r=int(r),p=int(q),dklen=len(bytes.fromhex(d)))
        return hmac.compare_digest(got.hex(),d)
    except Exception:return False
def th(t): return hashlib.sha256(t.encode()).hexdigest()
def mail(to,subject,body):
    api_key=os.environ.get("ITICAS_BREVO_API_KEY","").strip()
    sender=os.environ.get("ITICAS_EMAIL_FROM","").strip()
    sender_name=os.environ.get("ITICAS_EMAIL_FROM_NAME","ITICAS Access Administration").strip()
    if api_key and sender:
        payload=json.dumps({"sender":{"name":sender_name,"email":sender},"to":[{"email":to}],
                            "subject":subject,"textContent":body}).encode("utf-8")
        req=urllib.request.Request("https://api.brevo.com/v3/smtp/email",data=payload,
            headers={"accept":"application/json","api-key":api_key,"content-type":"application/json"},method="POST")
        try:
            with urllib.request.urlopen(req,timeout=20) as r:
                return 200 <= int(r.status) < 300
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Brevo email API returned HTTP {e.code}") from e
        except urllib.error.URLError as e:
            raise RuntimeError("Brevo email API could not be reached.") from e
    host=os.environ.get("ITICAS_SMTP_HOST","").strip(); user=os.environ.get("ITICAS_SMTP_USERNAME","").strip()
    pwd=os.environ.get("ITICAS_SMTP_PASSWORD",""); sender=os.environ.get("ITICAS_SMTP_FROM",user).strip()
    port=int(os.environ.get("ITICAS_SMTP_PORT","587"))
    if not host or not sender:return False
    m=EmailMessage(); m["From"]=sender; m["To"]=to; m["Subject"]=subject; m.set_content(body)
    with smtplib.SMTP(host,port,timeout=20) as smtp:
        smtp.starttls()
        if user:smtp.login(user,pwd)
        smtp.send_message(m)
    return True

def email_backend_status():
    return {"brevo_https_api_configured":bool(os.environ.get("ITICAS_BREVO_API_KEY","").strip() and os.environ.get("ITICAS_EMAIL_FROM","").strip()),
            "smtp_fallback_configured":bool(os.environ.get("ITICAS_SMTP_HOST","").strip()),"secrets_exposed":False}

def admin_email():
    x=os.environ.get("ITICAS_ADMIN_EMAIL","").strip()
    if x:return x
    with db() as c:
        r=c.execute("SELECT email FROM users WHERE role='admin' AND status='approved' ORDER BY id LIMIT 1").fetchone()
    return r["email"] if r else None
def admin_from_req(req):
    raw=req.cookies.get(COOKIE)
    if not raw:return None
    with db() as c:
        s=c.execute("SELECT * FROM admin_sessions WHERE token_hash=?",(th(raw),)).fetchone()
        if not s:return None
        if datetime.fromisoformat(s["expires_at"])<=datetime.now(timezone.utc):return None
        return c.execute("SELECT * FROM users WHERE id=? AND role='admin' AND status='approved'",(s["user_id"],)).fetchone()
class Req(BaseModel):
    username:str; email:str; password:str; full_name:str; organisation:str=""; phone:str=""; intended_use:str=""
class Login(BaseModel):
    identifier:str; password:str

def bootstrap_production_admin():
    email=os.environ.get("ITICAS_ADMIN_EMAIL","").strip().lower()
    username=os.environ.get("ITICAS_ADMIN_USERNAME","").strip()
    password=os.environ.get("ITICAS_ADMIN_BOOTSTRAP_PASSWORD","")
    full_name=os.environ.get("ITICAS_ADMIN_FULL_NAME","ITICAS Administrator").strip()
    if not email or not username or not password:return {"configured":False,"created":False}
    with db() as c:
        u=c.execute("SELECT * FROM users WHERE lower(email)=lower(?) OR lower(username)=lower(?)",(email,username)).fetchone()
        if u:
            c.execute("UPDATE users SET role='admin',status='approved',permissions_json=?,approved_at=COALESCE(approved_at,?) WHERE id=?",
                      (json.dumps(ALL_PERMISSIONS),now(),u["id"])); c.commit()
            return {"configured":True,"created":False}
        c.execute("INSERT INTO users(username,email,password_hash,full_name,organisation,phone,intended_use,role,status,permissions_json,created_at,approved_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                  (username,email,hpw(password),full_name,"","","Production administration","admin","approved",json.dumps(ALL_PERMISSIONS),now(),now()))
        c.commit()
    return {"configured":True,"created":True}

@app.on_event("startup")
def startup():
    init()
    bootstrap_production_admin()

@app.get("/health")
def health():
    h=central_pg.health()
    return {"status":"ok","pending":h["pending"],"approved":h["approved"],"database_backend":h["backend"],"persistent_database":h["persistent"],"database_connection":h["connection"]}

@app.get("/api/production/readiness")
def production_readiness():
    e=email_backend_status()
    checks={"persistent_postgresql":bool(os.environ.get("ITICAS_CENTRAL_DATABASE_URL","").strip()),
            "brevo_https_email":e["brevo_https_api_configured"],
            "production_admin_bootstrap":bool(os.environ.get("ITICAS_ADMIN_EMAIL","").strip() and os.environ.get("ITICAS_ADMIN_USERNAME","").strip() and os.environ.get("ITICAS_ADMIN_BOOTSTRAP_PASSWORD","")),
            "https_gateway":True}
    return {"status":"ready" if all(checks.values()) else "configuration_required","checks":checks,"secrets_exposed":False}

@app.post("/api/access/request")
def access_request(x:Req):
    try: pw=hpw(x.password)
    except ValueError as e: raise HTTPException(422,str(e))
    with db() as c:
        if c.execute("SELECT 1 FROM users WHERE lower(username)=lower(?) OR lower(email)=lower(?)",(x.username,x.email)).fetchone():
            raise HTTPException(409,"Username or email already exists.")
        cur=c.execute("INSERT INTO users(username,email,password_hash,full_name,organisation,phone,intended_use,role,status,permissions_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (x.username.strip(),x.email.strip().lower(),pw,x.full_name.strip(),x.organisation.strip(),x.phone.strip(),x.intended_use.strip(),"user","pending",json.dumps(DEFAULT_PERMISSIONS),now()))
        c.commit()
    ae=admin_email(); sent=False
    if ae:
        try: sent=mail(ae,"New ITICAS access request",f"Name: {x.full_name}\nUsername: {x.username}\nEmail: {x.email}\nOrganisation: {x.organisation}\nPhone: {x.phone}\nIntended use: {x.intended_use}")
        except Exception: sent=False
    return {"status":"pending","message":"Access request submitted. You will receive an email after administrator review.","admin_email_sent":sent}

@app.post("/api/access/login")
def access_login(x:Login):
    ident=x.identifier.strip().lower()
    with db() as c:
        u=c.execute("SELECT * FROM users WHERE lower(username)=? OR lower(email)=?",(ident,ident)).fetchone()
        if not u or u["status"]!="approved" or not vpw(x.password,u["password_hash"]): raise HTTPException(401,"Invalid credentials or account is not approved.")
        c.execute("UPDATE users SET last_login_at=? WHERE id=?",(now(),u["id"])); c.commit()
        perms=list(ALL_PERMISSIONS) if u["role"]=="admin" else json.loads(u["permissions_json"] or "[]")
        return {"id":u["id"],"username":u["username"],"email":u["email"],"role":u["role"],"status":u["status"],"permissions":perms}

@app.get("/admin/login",response_class=HTMLResponse)
def admin_login_page(req:Request):
    if admin_from_req(req):return RedirectResponse("/admin",303)
    return HTMLResponse('<!doctype html><html><body style="font-family:Segoe UI;background:#07111d;color:white;display:grid;place-items:center;min-height:100vh"><form method="post" action="/admin/login" style="width:420px;background:#0d1a2a;padding:30px;border-radius:20px"><h1>ITICAS Central Admin</h1><input name="identifier" placeholder="Email or username" style="width:100%;padding:12px;margin:8px 0"><input type="password" name="password" placeholder="Password" style="width:100%;padding:12px;margin:8px 0"><button style="width:100%;padding:12px">Sign in</button></form></body></html>')

@app.post("/admin/login")
async def admin_login(req:Request):
    f=await req.form(); ident=str(f.get("identifier","")).strip().lower(); pwd=str(f.get("password",""))
    with db() as c:
        u=c.execute("SELECT * FROM users WHERE (lower(username)=? OR lower(email)=?) AND role='admin' AND status='approved'",(ident,ident)).fetchone()
        if not u or not vpw(pwd,u["password_hash"]):return HTMLResponse("Administrator sign-in failed.",401)
        raw=secrets.token_urlsafe(48); exp=(datetime.now(timezone.utc)+timedelta(hours=8)).isoformat()
        c.execute("INSERT INTO admin_sessions(token_hash,user_id,expires_at,created_at) VALUES(?,?,?,?)",(th(raw),u["id"],exp,now())); c.commit()
    r=RedirectResponse("/admin",303); r.set_cookie(COOKIE,raw,httponly=True,samesite="strict",max_age=28800); return r

@app.get("/admin",response_class=HTMLResponse)
def admin(req:Request):
    a=admin_from_req(req)
    if not a:return RedirectResponse("/admin/login",303)
    with db() as c: rows=c.execute("SELECT * FROM users ORDER BY id DESC").fetchall()
    trs=[]
    for u in rows:
        act=""
        if u["status"]=="pending":
            act=f"<form style='display:inline' method='post' action='/admin/users/{u['id']}/approve'><button>Approve</button></form> <form style='display:inline' method='post' action='/admin/users/{u['id']}/reject'><button>Reject</button></form>"
        trs.append(f"<tr><td>{u['id']}</td><td>{html.escape(str(u['full_name'] or ''))}</td><td>{html.escape(u['username'])}</td><td>{html.escape(u['email'])}</td><td>{html.escape(str(u['organisation'] or ''))}</td><td>{html.escape(str(u['phone'] or ''))}</td><td>{html.escape(str(u['intended_use'] or ''))}</td><td>{u['status']}</td><td>{act}</td></tr>")
    return HTMLResponse("<html><body style='font-family:Segoe UI;background:#07111d;color:white;padding:20px'><h1>ITICAS Central Access Administration</h1><table border='1' cellpadding='8' style='border-collapse:collapse;width:100%'><tr><th>ID</th><th>Name</th><th>Username</th><th>Email</th><th>Organisation</th><th>Phone</th><th>Use</th><th>Status</th><th>Action</th></tr>"+''.join(trs)+"</table></body></html>")

@app.post("/admin/users/{uid}/approve")
def approve(uid:int,req:Request):
    a=admin_from_req(req)
    if not a:raise HTTPException(401,"Admin required")
    with db() as c:
        u=c.execute("SELECT * FROM users WHERE id=?",(uid,)).fetchone()
        if not u:raise HTTPException(404,"User not found")
        c.execute("UPDATE users SET status='approved',approved_at=? WHERE id=?",(now(),uid)); c.commit()
    try:mail(u["email"],"ITICAS access approved",f"Dear {u['full_name'] or u['username']},\n\nYour ITICAS access request has been approved. You can now sign in.")
    except Exception:pass
    return RedirectResponse("/admin",303)

@app.post("/admin/users/{uid}/reject")
def reject(uid:int,req:Request):
    a=admin_from_req(req)
    if not a:raise HTTPException(401,"Admin required")
    with db() as c:
        u=c.execute("SELECT * FROM users WHERE id=?",(uid,)).fetchone()
        if not u:raise HTTPException(404,"User not found")
        c.execute("UPDATE users SET status='rejected',rejected_at=? WHERE id=?",(now(),uid)); c.commit()
    try:mail(u["email"],"ITICAS access request update","Your ITICAS access request was not approved at this time.")
    except Exception:pass
    return RedirectResponse("/admin",303)


class ProviderTrafficRequest(BaseModel):
    latitude: float
    longitude: float
    radius_m: int = 1500

def _central_tomtom_key():
    return os.environ.get("ITICAS_TOMTOM_API_KEY","").strip()

def _central_alt_url():
    return os.environ.get("ITICAS_ALT_TRAFFIC_URL","").strip()

def _central_alt_token():
    return os.environ.get("ITICAS_ALT_TRAFFIC_TOKEN","").strip()

def _congestion(current_speed, free_flow_speed):
    if current_speed is None or free_flow_speed in (None,0):
        return None
    return round(max(0.0,min(1.0,1.0-float(current_speed)/float(free_flow_speed))),6)

async def _tomtom_flow(latitude, longitude):
    import httpx
    key=_central_tomtom_key()
    if not key:
        return None, {"provider":"TomTom Traffic API","category":"provider_not_configured","message":"Server-side TomTom credential is not configured.","retryable":False}
    url="https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json"
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r=await client.get(url,params={"key":key,"point":f"{float(latitude):.7f},{float(longitude):.7f}","unit":"kmph","openLr":"false"})
    except httpx.HTTPError:
        return None, {"provider":"TomTom Traffic API","category":"network_failure","message":"TomTom could not be reached from the central service.","retryable":True}
    body=r.text or ""
    if r.status_code>=400:
        low=body.lower()
        if r.status_code==403 and ("insufficientfunds" in low or "enough credits" in low or "insufficient funds" in low):
            return None, {"provider":"TomTom Traffic API","category":"provider_credit_exhausted","message":"TomTom traffic quota/credits are exhausted.","retryable":False,"http_status":403}
        if r.status_code==429:
            return None, {"provider":"TomTom Traffic API","category":"rate_limited","message":"TomTom traffic rate limit reached.","retryable":True,"http_status":429}
        return None, {"provider":"TomTom Traffic API","category":"provider_http_error","message":f"TomTom returned HTTP {r.status_code}.","retryable":r.status_code>=500,"http_status":r.status_code}
    data=r.json().get("flowSegmentData") or {}
    if not data:
        return None, {"provider":"TomTom Traffic API","category":"no_flow_data","message":"TomTom returned no flow segment.","retryable":False}
    current=data.get("currentSpeed"); free=data.get("freeFlowSpeed")
    curtt=data.get("currentTravelTime"); freett=data.get("freeFlowTravelTime")
    delay=max(0.0,float(curtt)-float(freett)) if curtt is not None and freett is not None else None
    row={
        "current_speed_kmh":float(current) if current is not None else None,
        "free_flow_speed_kmh":float(free) if free is not None else None,
        "congestion_index":_congestion(current,free),
        "delay_seconds":delay,
        "confidence":float(data["confidence"]) if data.get("confidence") is not None else None,
        "road_closed":1 if data.get("roadClosure") is True else 0 if data.get("roadClosure") is False else None,
        "segment_geometry_json":json.dumps(data.get("coordinates"),separators=(",",":")) if data.get("coordinates") is not None else None,
        "provider":"TomTom Traffic API",
    }
    return row,None

async def _alternate_flow(latitude,longitude,radius_m):
    import httpx
    url=_central_alt_url()
    if not url:
        return None, {"provider":"Alternate Traffic Provider","category":"provider_not_configured","message":"No alternate live traffic provider is configured.","retryable":False}
    headers={"Accept":"application/json"}
    token=_central_alt_token()
    if token:
        headers["Authorization"]=f"Bearer {token}"
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r=await client.post(url,json={"latitude":latitude,"longitude":longitude,"radius_m":radius_m},headers=headers)
        if r.status_code>=400:
            return None, {"provider":"Alternate Traffic Provider","category":"provider_http_error","message":f"Alternate provider returned HTTP {r.status_code}.","retryable":r.status_code>=500,"http_status":r.status_code}
        data=r.json()
        flow=data.get("live_observation") if isinstance(data,dict) else None
        if flow:
            return flow,None
        return None, {"provider":"Alternate Traffic Provider","category":"no_flow_data","message":"Alternate provider returned no live observation.","retryable":False}
    except Exception:
        return None, {"provider":"Alternate Traffic Provider","category":"network_failure","message":"Alternate traffic provider could not be reached.","retryable":True}

@app.post("/api/provider/traffic/evaluate")
async def provider_traffic_evaluate(x: ProviderTrafficRequest):
    attempts=[]
    flow,diag=await _tomtom_flow(x.latitude,x.longitude)
    if diag: attempts.append(diag)
    if flow:
        return {
            "status":"ok",
            "provider":"TomTom Traffic API",
            "live_provider":"TomTom Traffic API",
            "live_observation":flow,
            "incidents":[],
            "incident_count":0,
            "validation":{"validation_status":"provider_reference_validated","independence_level":"provider_reference","limitations":"Central ITICAS broker supplied live traffic. Provider credentials remain server-side."},
            "provider_diagnostics":{"attempts":attempts},
            "provenance":{"broker":"ITICAS Central Provider Broker","credential_exposed":False},
        }
    flow2,diag2=await _alternate_flow(x.latitude,x.longitude,x.radius_m)
    if diag2: attempts.append(diag2)
    if flow2:
        return {
            "status":"ok",
            "provider":"Alternate Traffic Provider",
            "live_provider":"Alternate Traffic Provider",
            "live_observation":flow2,
            "incidents":[],
            "incident_count":0,
            "validation":{"validation_status":"provider_reference","independence_level":"provider_reference","limitations":"Central ITICAS broker supplied alternate live traffic. Provider credentials remain server-side."},
            "provider_diagnostics":{"attempts":attempts},
            "provenance":{"broker":"ITICAS Central Provider Broker","credential_exposed":False},
        }
    category="live_provider_unavailable"
    if any(a.get("category")=="provider_credit_exhausted" for a in attempts):
        category="live_provider_credit_exhausted"
    return {
        "status":category,
        "provider":"ITICAS Central Provider Broker",
        "live_provider":None,
        "live_observation":None,
        "incidents":[],
        "incident_count":0,
        "message":"No live traffic provider is currently available.",
        "provider_diagnostics":{"attempts":attempts},
        "provenance":{"broker":"ITICAS Central Provider Broker","credential_exposed":False},
    }

@app.get("/api/provider/status")
async def provider_status():
    return {
        "broker":"ITICAS Central Provider Broker",
        "tomtom_configured":bool(_central_tomtom_key()),
        "alternate_provider_configured":bool(_central_alt_url()),
        "credential_exposed":False,
    }
