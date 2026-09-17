from __future__ import annotations
import os, math, httpx
from dataclasses import dataclass, asdict
from typing import Any

GOOGLE_ROUTES_URL="https://routes.googleapis.com/directions/v2:computeRoutes"

@dataclass
class TrafficEvidence:
    provider: str
    evidence_type: str
    status: str
    current_speed_kmh: float|None=None
    free_flow_speed_kmh: float|None=None
    traffic_duration_s: float|None=None
    baseline_duration_s: float|None=None
    delay_s: float|None=None
    travel_time_index: float|None=None
    confidence: float|None=None
    raw: dict[str,Any]|None=None
    note: str|None=None
    def dict(self): return asdict(self)

def _seconds(v):
    if not v: return None
    try: return float(str(v).rstrip("s"))
    except Exception: return None

class GoogleTrafficAwareRoutes:
    """Traffic-aware route evidence. It MUST NOT be labelled as direct measured speed."""
    def __init__(self,key=None,timeout=15):
        self.key=key or os.getenv("GOOGLE_MAPS_API_KEY") or os.getenv("ITICAS_GOOGLE_ROUTES_API_KEY")
        self.timeout=timeout
    @property
    def configured(self): return bool(self.key)
    async def corridor(self, origin_lat,origin_lon,dest_lat,dest_lon):
        if not self.key:
            return TrafficEvidence("google_routes","traffic_aware_route","not_configured",note="Google Routes key not configured").dict()
        body={"origin":{"location":{"latLng":{"latitude":float(origin_lat),"longitude":float(origin_lon)}}},
              "destination":{"location":{"latLng":{"latitude":float(dest_lat),"longitude":float(dest_lon)}}},
              "travelMode":"DRIVE","routingPreference":"TRAFFIC_AWARE"}
        headers={"X-Goog-Api-Key":self.key,
                 "X-Goog-FieldMask":"routes.duration,routes.staticDuration,routes.distanceMeters,routes.polyline.encodedPolyline",
                 "Content-Type":"application/json"}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as c:
                r=await c.post(GOOGLE_ROUTES_URL,json=body,headers=headers)
            if r.status_code!=200:
                return TrafficEvidence("google_routes","traffic_aware_route","provider_error",raw={"status_code":r.status_code,"body":r.text[:500]}).dict()
            data=r.json(); routes=data.get("routes") or []
            if not routes: return TrafficEvidence("google_routes","traffic_aware_route","no_route",raw=data).dict()
            x=routes[0]; td=_seconds(x.get("duration")); bd=_seconds(x.get("staticDuration"))
            delay=max(0.0,td-bd) if td is not None and bd is not None else None
            tti=(td/bd) if td is not None and bd and bd>0 else None
            return TrafficEvidence("google_routes","traffic_aware_route","ok",traffic_duration_s=td,
                baseline_duration_s=bd,delay_s=delay,travel_time_index=tti,raw=x,
                note="Traffic-aware route estimate; not a direct TomTom-style point speed measurement.").dict()
        except Exception as e:
            return TrafficEvidence("google_routes","traffic_aware_route","network_error",note=str(e)).dict()
