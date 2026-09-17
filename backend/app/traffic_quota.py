from __future__ import annotations
import json, os, sqlite3, time
from datetime import datetime, timezone
from .paths import DATA_ROOT
DB=DATA_ROOT/"data"/"provider_state"/"traffic_quota.sqlite3"; DB.parent.mkdir(parents=True,exist_ok=True)
TTL=int(os.getenv("ITICAS_TRAFFIC_CACHE_TTL_SECONDS","300")); CIRCUIT=int(os.getenv("ITICAS_TOMTOM_CIRCUIT_SECONDS","3600"))
SOFT=int(os.getenv("ITICAS_TOMTOM_MONTHLY_SOFT_BUDGET","18000")); HARD=int(os.getenv("ITICAS_TOMTOM_MONTHLY_HARD_BUDGET","19800"))
def con():
 d=sqlite3.connect(DB,timeout=15); d.execute("CREATE TABLE IF NOT EXISTS cache(provider TEXT,key TEXT,payload TEXT,observed REAL,expires REAL,PRIMARY KEY(provider,key))"); d.execute("CREATE TABLE IF NOT EXISTS calls(id INTEGER PRIMARY KEY,provider TEXT,ts REAL,outcome TEXT,cache_hit INTEGER,key TEXT)"); d.execute("CREATE TABLE IF NOT EXISTS circuit(provider TEXT PRIMARY KEY,until_ts REAL,reason TEXT)"); d.commit(); return d
def key(lat,lon): return f"{round(float(lat),4):.4f},{round(float(lon),4):.4f}"
def month_start():
 n=datetime.now(timezone.utc); return datetime(n.year,n.month,1,tzinfo=timezone.utc).timestamp()
def record(provider,outcome,k=None,hit=0):
 d=con(); d.execute("INSERT INTO calls(provider,ts,outcome,cache_hit,key) VALUES(?,?,?,?,?)",(provider,time.time(),outcome,int(hit),k)); d.commit(); d.close()
def month_calls(provider="tomtom"):
 d=con(); n=d.execute("SELECT COUNT(*) FROM calls WHERE provider=? AND ts>=? AND cache_hit=0 AND outcome IN ('success','quota_exhausted','rate_or_quota_limited','provider_failure')",(provider,month_start())).fetchone()[0]; d.close(); return int(n)
def clear_circuit(provider):
 d=con(); d.execute("DELETE FROM circuit WHERE provider=?",(provider,)); d.commit(); d.close()
def open_circuit(provider,reason,seconds=CIRCUIT):
 d=con(); d.execute("INSERT OR REPLACE INTO circuit VALUES(?,?,?)",(provider,time.time()+int(seconds),str(reason))); d.commit(); d.close()
def cached(provider,k):
 d=con(); r=d.execute("SELECT payload,observed,expires FROM cache WHERE provider=? AND key=?",(provider,k)).fetchone(); d.close()
 if not r or r[2]<time.time(): return None
 try: p=json.loads(r[0])
 except Exception: return None
 return {"payload":p,"observed_at":r[1],"cache":True}
def before(provider,lat,lon):
 k=key(lat,lon); c=cached(provider,k)
 if c: record(provider,"cache_hit",k,1); return {"allow":False,"reason":"recent_cache_hit","cached":c}
 d=con(); r=d.execute("SELECT until_ts,reason FROM circuit WHERE provider=?",(provider,)).fetchone(); d.close()
 if r and r[0]>time.time(): record(provider,"circuit_block",k,1); return {"allow":False,"reason":"provider_circuit_open","warning":r[1]}
 if r: clear_circuit(provider)
 used=month_calls(provider)
 if provider=="tomtom" and used>=HARD: open_circuit(provider,"ITICAS hard request budget reached",86400); record(provider,"budget_block",k,1); return {"allow":False,"reason":"hard_budget_reached"}
 return {"allow":True,"reason":"soft_budget_warning" if provider=="tomtom" and used>=SOFT else "provider_call_allowed","monthly_calls":used}
def success(provider,lat,lon,payload):
 k=key(lat,lon); now=time.time(); record(provider,"success",k); d=con(); d.execute("INSERT OR REPLACE INTO cache VALUES(?,?,?,?,?)",(provider,k,json.dumps(payload),now,now+TTL)); d.commit(); d.close(); return payload
def failure(provider,lat,lon,status,body=""):
 t=(body or "").lower()
 q=any(w in t for w in ("insufficientfunds","insufficient funds","provider_credit_exhausted","quota_exhausted","credit exhausted"))
 kind="quota_exhausted" if q else "rate_or_quota_limited" if status==429 or "rate_limited" in t else "provider_failure"
 record(provider,kind,key(lat,lon))
 if kind in ("quota_exhausted","rate_or_quota_limited"): open_circuit(provider,kind)
 return kind
def status(provider="tomtom"):
 d=con(); ev={r[0]:int(r[1]) for r in d.execute("SELECT outcome,COUNT(*) FROM calls WHERE provider=? AND ts>=? GROUP BY outcome",(provider,month_start())).fetchall()}; c=d.execute("SELECT until_ts,reason FROM circuit WHERE provider=?",(provider,)).fetchone(); d.close()
 return {"provider":provider,"monthly_provider_calls_recorded":month_calls(provider),"soft_budget":SOFT,"hard_budget":HARD,"cache_ttl_seconds":TTL,"monthly_events":ev,"circuit":{"open_until":c[0],"reason":c[1]} if c and c[0]>time.time() else None}
