import os,httpx
class MapboxTraffic:
 def __init__(self,token=None): self.token=token or os.getenv("MAPBOX_ACCESS_TOKEN")
 @property
 def configured(self): return bool(self.token)
 async def corridor(self,a,b,c,d):
  if not self.token:return {"provider":"mapbox","evidence_type":"traffic_aware_route","status":"not_configured"}
  u=f"https://api.mapbox.com/directions/v5/mapbox/driving-traffic/{b},{a};{d},{c}"
  try:
   async with httpx.AsyncClient(timeout=15) as x:r=await x.get(u,params={"access_token":self.token,"overview":"full","geometries":"geojson"})
   if r.status_code!=200:return {"provider":"mapbox","evidence_type":"traffic_aware_route","status":"provider_error","status_code":r.status_code,"body":r.text[:300]}
   q=r.json(); routes=q.get("routes") or []
   if not routes:return {"provider":"mapbox","evidence_type":"traffic_aware_route","status":"no_route"}
   y=routes[0]
   return {"provider":"mapbox","evidence_type":"traffic_aware_route","status":"ok","duration_s":y.get("duration"),"distance_m":y.get("distance"),"geometry":y.get("geometry"),"note":"Traffic-aware routing evidence; not direct measured point speed."}
  except Exception as e:return {"provider":"mapbox","evidence_type":"traffic_aware_route","status":"network_error","note":str(e)}
