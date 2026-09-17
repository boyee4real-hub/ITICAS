from __future__ import annotations
import os, time
from .google_traffic import GoogleTrafficAwareRoutes

class MultiProviderTrafficBroker:
    """Provider failover without falsifying provenance."""
    def __init__(self):
        self.google=GoogleTrafficAwareRoutes()
    async def google_corridor(self,a_lat,a_lon,b_lat,b_lon):
        return await self.google.corridor(a_lat,a_lon,b_lat,b_lon)
    def status(self):
        try:
            from .tomtom_traffic import iticas_quota_status
            tom=iticas_quota_status()
        except Exception as e:
            tom={"provider":"tomtom","status":"unknown","error":str(e)}
        return {
          "tomtom":tom,
          "google_routes":{"configured":self.google.configured,
             "evidence_type":"traffic_aware_route",
             "scientific_rule":"Never present Google route evidence as a direct measured point speed."},
          "fallback_policy":["tomtom_live_flow","google_traffic_aware_route","iticas_historical"],
          "historical_rule":"Stored observations remain HISTORICAL unless their original acquisition timestamp qualifies them as cached provider evidence."
        }

traffic_broker=MultiProviderTrafficBroker()
