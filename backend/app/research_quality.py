from __future__ import annotations
from math import atan2, cos, radians, sin, sqrt
from sqlalchemy import select
from .database import SessionLocal, MonitoringLocation, CorridorProbe

# Conservative Nigeria bounding envelope used only as a research-integrity guard.
# It prevents a browser/device position on another continent from being accepted as
# Nigerian field evidence. It is not used for geodetic computation.
NIGERIA_BOUNDS = {"lat_min": 4.0, "lat_max": 14.5, "lon_min": 2.0, "lon_max": 15.0}

def haversine_m(lat1, lon1, lat2, lon2):
    r=6371000.0
    p1,p2=radians(lat1),radians(lat2)
    dp=radians(lat2-lat1); dl=radians(lon2-lon1)
    a=sin(dp/2)**2+cos(p1)*cos(p2)*sin(dl/2)**2
    return 2*r*atan2(sqrt(a),sqrt(max(0.0,1-a)))

def _in_nigeria(lat, lon):
    return NIGERIA_BOUNDS["lat_min"] <= float(lat) <= NIGERIA_BOUNDS["lat_max"] and NIGERIA_BOUNDS["lon_min"] <= float(lon) <= NIGERIA_BOUNDS["lon_max"]

def point_study_distance(location_id:int, latitude:float, longitude:float):
    with SessionLocal() as db:
        loc=db.get(MonitoringLocation, location_id)
        probes=list(db.scalars(select(CorridorProbe).where(CorridorProbe.location_id==location_id)).all())
    if not loc:
        return None, None
    # The monitoring-location coordinate is the authoritative anchor. Probe coordinates
    # are accepted as corroborating corridor geometry only when they are themselves close
    # to that anchor. This prevents a previously corrupted/off-country probe set from
    # legitimising an unrelated device position.
    anchor=None
    if loc.latitude is not None and loc.longitude is not None:
        anchor=(float(loc.latitude),float(loc.longitude))
    candidates=[]
    if anchor:
        candidates.append(anchor)
        anchor_guard=max(5000.0, float(loc.radius_m or 1000)*5.0)
        for p in probes:
            if p.latitude is None or p.longitude is None: continue
            if haversine_m(anchor[0],anchor[1],float(p.latitude),float(p.longitude)) <= anchor_guard:
                candidates.append((float(p.latitude),float(p.longitude)))
    else:
        candidates=[(float(p.latitude),float(p.longitude)) for p in probes if p.latitude is not None and p.longitude is not None and _in_nigeria(p.latitude,p.longitude)]
    if not candidates:
        return None, loc
    return min(haversine_m(latitude,longitude,la,lo) for la,lo in candidates), loc

def gnss_quality(location_id:int, latitude:float, longitude:float, accuracy_m:float|None=None):
    if not _in_nigeria(latitude, longitude):
        return {
            "valid":False,
            "reason":(f"Device GNSS reports {float(latitude):.6f}, {float(longitude):.6f}, which is outside Nigeria. "
                      "Browser GNSS reports the physical device location; it does not move to the selected study road. "
                      "Use a phone/GNSS receiver physically on the Nigerian study corridor or import field coordinates."),
            "distance_m":None,"tolerance_m":None,"outside_nigeria":True,
        }
    distance,loc=point_study_distance(location_id,latitude,longitude)
    if not loc:
        return {"valid":False,"reason":"Study location not found.","distance_m":None,"tolerance_m":None}
    tolerance=max(750.0, float(loc.radius_m or 1000), min(2500.0, 2.0*float(accuracy_m or 0.0)))
    if distance is None:
        return {"valid":False,"reason":"The selected study road has no trustworthy Nigerian reference coordinate/geometry for GNSS validation.","distance_m":None,"tolerance_m":tolerance}
    valid=distance <= tolerance
    return {
        "valid":valid,"distance_m":round(distance,1),"tolerance_m":round(tolerance,1),
        "reason":("Coordinate is spatially consistent with the selected study corridor." if valid else
                  f"Device coordinate is {distance/1000:.1f} km from the selected study corridor and is excluded from study evidence."),
        "study_location":loc.name,"outside_nigeria":False,
    }
