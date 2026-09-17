from __future__ import annotations
import os,json,sqlite3,hashlib
from dataclasses import dataclass,asdict
from datetime import datetime,timezone
from pathlib import Path
import httpx
from .request_conservation import event as _conservation_event # ITICAS_STAGE16_ROUTE_GUARD

@dataclass
class Evidence:
    provider:str; evidence_type:str; status:str; acquired_at:str
    origin:tuple; destination:tuple
    length_m:int|None=None; travel_time_s:int|None=None
    no_traffic_time_s:int|None=None; historic_time_s:int|None=None
    live_time_s:int|None=None; traffic_delay_s:int|None=None
    traffic_length_m:int|None=None; tti:float|None=None
    congestion_class:str|None=None; cache_hit:bool=False
    original_acquired_at:str|None=None; note:str|None=None

def _now(): return datetime.now(timezone.utc).isoformat()
def _root():
    p=Path(os.getenv("ITICAS_DATA_ROOT") or (Path.home()/".iticas")); p.mkdir(parents=True,exist_ok=True); return p
def _db():
    p=_root()/"data"/"provider_state"/"route_traffic.sqlite3"; p.parent.mkdir(parents=True,exist_ok=True); return p
def _init():
    with sqlite3.connect(_db()) as c:
        c.execute("CREATE TABLE IF NOT EXISTS cache(k TEXT PRIMARY KEY, acquired TEXT, expires INTEGER, payload TEXT)")
def _key(a,b): return hashlib.sha256(f"{a[0]:.4f},{a[1]:.4f}|{b[0]:.4f},{b[1]:.4f}".encode()).hexdigest()
def _class(tti):
    if tti is None:return "unknown"
    if tti<1.10:return "free_flow_or_low"
    if tti<1.25:return "moderate"
    if tti<1.50:return "heavy"
    return "severe"

class TomTomTrafficAwareRouting:
    def __init__(self,key=None,ttl=300):
        self.key=key or os.getenv("TOMTOM_API_KEY",""); self.ttl=ttl; _init()
    def acquire(self,a,b,use_cache=True):
        a=(float(a[0]),float(a[1])); b=(float(b[0]),float(b[1])); k=_key(a,b)
        now=int(datetime.now(timezone.utc).timestamp())
        if use_cache:
            with sqlite3.connect(_db()) as c:r=c.execute("SELECT acquired,expires,payload FROM cache WHERE k=?",(k,)).fetchone()
            if r and r[1]>=now:
                d=json.loads(r[2]); d["cache_hit"]=True; d["original_acquired_at"]=r[0]; _conservation_event("cache_hit",k,"traffic_aware_route"); return Evidence(**d)
        if not self.key:return Evidence("tomtom","traffic_aware_route","not_configured",_now(),a,b,note="No TomTom key configured")
        u=f"https://api.tomtom.com/routing/1/calculateRoute/{a[0]},{a[1]}:{b[0]},{b[1]}/json"
        q={"key":self.key,"traffic":"true","travelMode":"car","routeType":"fastest","computeTravelTimeFor":"all","routeRepresentation":"summaryOnly"}
        _conservation_event("provider_call",k,"tomtom_traffic_aware_route")
        r=httpx.get(u,params=q,timeout=25)
        if r.status_code!=200:
            t=(r.text or "")[:800]; low=t.lower(); st="provider_error"
            if r.status_code in (401,403):st="authentication_or_entitlement_error"
            if r.status_code==429 or "insufficientfunds" in low or "quota" in low:st="quota_exhausted"
            return Evidence("tomtom","traffic_aware_route",st,_now(),a,b,note=f"HTTP {r.status_code}: {t}")
        s=(r.json().get("routes") or [{}])[0].get("summary") or {}
        tt=s.get("travelTimeInSeconds"); nt=s.get("noTrafficTravelTimeInSeconds")
        tti=(float(tt)/float(nt)) if tt and nt and nt>0 else None
        e=Evidence("tomtom","traffic_aware_route","available",_now(),a,b,s.get("lengthInMeters"),tt,nt,
          s.get("historicTrafficTravelTimeInSeconds"),s.get("liveTrafficIncidentsTravelTimeInSeconds"),
          s.get("trafficDelayInSeconds"),s.get("trafficLengthInMeters"),round(tti,4) if tti else None,
          _class(tti),False,None,"Route-level traffic evidence; not direct point-speed.")
        with sqlite3.connect(_db()) as c:c.execute("INSERT OR REPLACE INTO cache VALUES(?,?,?,?)",(k,e.acquired_at,now+self.ttl,json.dumps(asdict(e))))
        return e

def corridor_pairs(points,target_sections=8):
    p=[(float(x[0]),float(x[1])) for x in points]
    if len(p)<2:return []
    n=max(1,min(int(target_sections),len(p)-1))
    ix=sorted(set(round(i*(len(p)-1)/n) for i in range(n+1)))
    return [(p[ix[i]],p[ix[i+1]]) for i in range(len(ix)-1)]

def safe_status():
    return {"provider":"tomtom","evidence_type":"traffic_aware_route","configured":bool(os.getenv("TOMTOM_API_KEY")),"direct_point_speed":False,"cache_db":str(_db())}
