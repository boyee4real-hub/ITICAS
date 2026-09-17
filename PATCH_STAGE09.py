from pathlib import Path
p=Path("backend/app/main.py")
if not p.exists(): raise SystemExit("[FAIL] backend/app/main.py not found")
s=p.read_text(encoding="utf-8")
if "# ITICAS_STAGE09_TRAFFIC_AWARE_ROUTING" not in s:
 s += """
# ITICAS_STAGE09_TRAFFIC_AWARE_ROUTING
from dataclasses import asdict as _stage09_asdict
from .tomtom_route_traffic import TomTomTrafficAwareRouting, safe_status as _stage09_status
@app.get("/api/providers/tomtom-route-traffic/status")
def stage09_status(): return _stage09_status()
@app.get("/api/providers/tomtom-route-traffic/evaluate")
def stage09_eval(origin_lat:float,origin_lon:float,destination_lat:float,destination_lon:float):
 return _stage09_asdict(TomTomTrafficAwareRouting().acquire((origin_lat,origin_lon),(destination_lat,destination_lon)))
"""
 p.write_text(s,encoding="utf-8")
 print("[PASS] Stage09 API installed")
else: print("[PASS] Stage09 already installed")
