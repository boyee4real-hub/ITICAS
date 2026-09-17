from pathlib import Path
R=Path(__file__).resolve().parent
APP=R/"backend"/"app"
for name in ("google_traffic.py","multi_provider_traffic.py"):
    src=R/name
    if not src.exists(): raise SystemExit(f"[FAIL] missing {name}")
    (APP/name).write_text(src.read_text(encoding="utf-8"),encoding="utf-8")
main=APP/"main.py"
s=main.read_text(encoding="utf-8")
MARK="# ITICAS_STAGE06_MULTI_PROVIDER"
if MARK not in s:
    addition=r"""
# ITICAS_STAGE06_MULTI_PROVIDER
from .multi_provider_traffic import traffic_broker
try:
    from fastapi import Depends
    @app.get("/api/providers/traffic/status")
    def iticas_traffic_provider_status():
        return traffic_broker.status()

    @app.get("/api/providers/traffic/google-corridor")
    async def iticas_google_corridor(origin_lat:float,origin_lon:float,dest_lat:float,dest_lon:float):
        return await traffic_broker.google_corridor(origin_lat,origin_lon,dest_lat,dest_lon)
except Exception:
    pass
"""
    s += "\n"+addition
    main.write_text(s,encoding="utf-8")
    print("[PASS] provider status/fallback API installed")
else: print("[PASS] Stage06 API already present")
