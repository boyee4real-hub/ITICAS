from .mapbox_traffic import MapboxTraffic
from .azure_traffic import AzureTraffic
class NigeriaTrafficBroker:
 def __init__(self): self.mapbox=MapboxTraffic(); self.azure=AzureTraffic()
 def status(self):
  try:
   from .tomtom_traffic import iticas_quota_status
   t=iticas_quota_status()
  except Exception as e:t={"provider":"tomtom","status":"unknown","error":str(e)}
  return {"priority":["tomtom_live_flow","azure_optional","mapbox_driving_traffic","cached_provider","iticas_historical"],"tomtom":t,"azure":self.azure.status(),"mapbox":{"configured":self.mapbox.configured,"evidence_type":"traffic_aware_route"},"waze":{"configured":False,"status":"partner_access_required"}}
 async def mapbox_corridor(self,*x):return await self.mapbox.corridor(*x)
nigeria_traffic_broker=NigeriaTrafficBroker()
