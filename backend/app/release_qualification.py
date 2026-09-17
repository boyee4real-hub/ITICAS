from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import json, sqlite3, os
CREDIT="Developed by Dr. Oyeyode A.O. MNIS, MGEOSON, MNAG"
def _db():
    return Path(os.getenv("ITICAS_DATA_ROOT") or (Path.home()/".iticas"))/"data"/"traffic_intelligence"/"route_observations.sqlite3"
def report(study_id="stage10_ibadan"):
    rows=[]; p=_db()
    if p.exists():
        try:
            with sqlite3.connect(p) as c:
                c.row_factory=sqlite3.Row
                rows=[dict(x) for x in c.execute("SELECT * FROM route_observations WHERE study_id=? AND status='available' ORDER BY acquired_at",(study_id,))]
        except Exception: rows=[]
    t=[float(x["tti"]) for x in rows if x.get("tti") is not None]; cached=sum(bool(x.get("cache_hit")) for x in rows)
    return {"title":"ITICAS Traffic Intelligence Research Report","study_id":study_id,"generated_at":datetime.now(timezone.utc).isoformat(),"credit":CREDIT,
    "evidence":{"type":"traffic_aware_route","direct_point_speed":False,"observations":len(rows),"fresh_provider_observations":len(rows)-cached,"cached_observations":cached,
    "tti_min":round(min(t),4) if t else None,"tti_max":round(max(t),4) if t else None,"tti_mean":round(sum(t)/len(t),4) if t else None},
    "interpretation":{"provider_delay_note":"Provider incident delay is kept separate from excess travel time over the no-traffic baseline.","classification_note":"Congestion classes are ITICAS operational classifications, not universal standards.","provenance_note":"Cached and historical evidence must not be relabelled as fresh live traffic."},
    "limitations":["Traffic-aware routing is route-level evidence and is not direct point-speed measurement.","Reliability and persistence conclusions strengthen as repeated observations accumulate.","Descriptive hotspot screening is not an inferential Gi* significance test."],
    "reproducibility":{"software":"ITICAS v0.26.3","core_gate":"Stage17 11/11","timezone_policy":"Africa/Lagos via zoneinfo for operational timestamps","provider_conservation":"stored/cache first; fresh provider only when explicitly required"}}
def write_json(study_id="stage10_ibadan"):
    out=Path(os.getenv("ITICAS_DATA_ROOT") or (Path.home()/".iticas"))/"reports"/"release_qualification"; out.mkdir(parents=True,exist_ok=True)
    p=out/(study_id+"_research_report.json"); p.write_text(json.dumps(report(study_id),indent=2),encoding="utf-8"); return str(p)
