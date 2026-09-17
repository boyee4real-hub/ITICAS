from pathlib import Path
R=Path(__file__).parent; A=R/"backend"/"app"
for n in ("mapbox_traffic.py","azure_traffic.py","nigeria_traffic_broker.py"):(A/n).write_text((R/n).read_text(),encoding="utf-8")
m=A/"main.py";s=m.read_text(encoding="utf-8");mark="# ITICAS_STAGE07_NIGERIA_TRAFFIC"
if mark not in s:
 s+='''
# ITICAS_STAGE07_NIGERIA_TRAFFIC
from .nigeria_traffic_broker import nigeria_traffic_broker
@app.get("/api/providers/nigeria-traffic/status")
def nigeria_traffic_status(): return nigeria_traffic_broker.status()
@app.get("/api/providers/nigeria-traffic/mapbox-corridor")
async def nigeria_mapbox_corridor(origin_lat:float,origin_lon:float,dest_lat:float,dest_lon:float):
 return await nigeria_traffic_broker.mapbox_corridor(origin_lat,origin_lon,dest_lat,dest_lon)
'''
 m.write_text(s,encoding="utf-8");print("[PASS] Stage07 API installed")
else:print("[PASS] Stage07 already installed")
