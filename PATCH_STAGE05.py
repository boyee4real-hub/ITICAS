from pathlib import Path
R=Path(__file__).resolve().parent; tt=R/"backend"/"app"/"tomtom_traffic.py"; ci=R/"backend"/"app"/"corridor_intelligence.py"
s=tt.read_text(encoding="utf-8")
if "# ITICAS_STAGE05_GUARDED_FLOW" not in s:
 s += """
# ITICAS_STAGE05_GUARDED_FLOW
from .traffic_quota import before as _q_before, success as _q_success, failure as _q_failure, status as quota_status
_ITICAS_UNGUARDED_FETCH_FLOW=TomTomTrafficClient.fetch_flow
async def _iticas_guarded_fetch_flow(self,latitude,longitude):
 d=_q_before("tomtom",latitude,longitude)
 if d.get("reason")=="recent_cache_hit": return d["cached"]["payload"]
 if not d.get("allow"):
  raise ProviderRequestError("ITICAS quota protection: "+str(d.get("reason")),category=str(d.get("reason") or "provider_circuit_open"),retryable=False,attempts=0)
 try: p=await _ITICAS_UNGUARDED_FETCH_FLOW(self,latitude,longitude)
 except ProviderRequestError as e:
  _q_failure("tomtom",latitude,longitude,getattr(e,"status_code",None),f"{getattr(e,'category','')} {e}"); raise
 _q_success("tomtom",latitude,longitude,p); return p
TomTomTrafficClient.fetch_flow=_iticas_guarded_fetch_flow
def iticas_quota_status(): return quota_status("tomtom")
"""
 tt.write_text(s,encoding="utf-8"); print("[PASS] guarded flow installed")
else: print("[PASS] guarded flow already present")
c=ci.read_text(encoding="utf-8")
if "# ITICAS_STAGE05_CORRIDOR_METRICS" not in c:
 c=c.replace("successful=0; failed=0; rows=[]","successful=0; failed=0; rows=[]\n    # ITICAS_STAGE05_CORRIDOR_METRICS\n    from .traffic_quota import status as _qs\n    _e0=dict((_qs('tomtom').get('monthly_events') or {}))")
 old='return {"status":"ok" if successful else "failed","location_id":location_id,"probes":len(probes),"successful":successful,"failed":failed,"rows":rows}'
 new='_e1=dict((_qs("tomtom").get("monthly_events") or {})); _d=lambda n:int(_e1.get(n,0))-int(_e0.get(n,0))\n    return {"status":"ok" if successful else ("provider_unavailable" if _d("circuit_block")+_d("budget_block") else "failed"),"location_id":location_id,"probes":len(probes),"successful":successful,"failed":failed,"provider_calls_attempted":_d("success")+_d("quota_exhausted")+_d("rate_or_quota_limited")+_d("provider_failure"),"cache_hits":_d("cache_hit"),"provider_calls_prevented":_d("circuit_block")+_d("budget_block"),"rows":rows}'
 if old not in c: raise SystemExit("[FAIL] corridor signature changed; refusing unsafe patch")
 c=c.replace(old,new); ci.write_text(c,encoding="utf-8"); print("[PASS] corridor metrics installed")
else: print("[PASS] corridor metrics already present")
