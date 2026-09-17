
from __future__ import annotations

from datetime import datetime, timezone, timedelta
import hashlib
import json
import httpx
from sqlalchemy import select

from .config import settings
from .database import SessionLocal, MonitoringLocation, CorridorProbe, TrafficObservation, CorridorProbeObservation


def configured():
    return bool(settings.supabase_archive_enabled and settings.supabase_url and settings.supabase_secret_key)


def _headers(prefer=None):
    h={
        "apikey": settings.supabase_secret_key or "",
        "Content-Type":"application/json",
        "Accept":"application/json",
        "User-Agent":"ITICAS-Server/0.22",
    }
    if prefer:
        h["Prefer"]=prefer
    return h


def _base():
    return (settings.supabase_url or "").rstrip("/") + "/rest/v1"


def _target_key(kind:str, location_id:int, sequence_no:int|None, latitude:float, longitude:float):
    raw=f"{kind}|{location_id}|{sequence_no or 0}|{latitude:.7f}|{longitude:.7f}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40]


async def _request(method, path, *, params=None, payload=None, prefer=None):
    if not configured():
        raise RuntimeError("Supabase autonomous archive is not configured.")
    async with httpx.AsyncClient(timeout=settings.supabase_archive_timeout_seconds) as c:
        r=await c.request(method, _base()+path, params=params, json=payload, headers=_headers(prefer))
        if r.status_code >= 400:
            raise RuntimeError(f"Supabase archive HTTP {r.status_code}: {r.text[:500]}")
        if not r.content:
            return None
        try:return r.json()
        except Exception:return r.text


async def sync_location_to_cloud(location_id:int):
    if not configured():
        return {"configured":False,"synced":0}
    with SessionLocal() as db:
        loc=db.get(MonitoringLocation,location_id)
        if not loc or loc.latitude is None or loc.longitude is None:
            return {"configured":True,"synced":0}
        probes=list(db.scalars(select(CorridorProbe).where(CorridorProbe.location_id==location_id).order_by(CorridorProbe.sequence_no)).all())
        payload=[{
            "target_key":_target_key("location",loc.id,None,float(loc.latitude),float(loc.longitude)),
            "target_type":"location",
            "local_location_id":loc.id,
            "probe_sequence_no":None,
            "name":loc.name,
            "road_name":loc.road_name,
            "city":loc.city,
            "state":loc.state,
            "country":"Nigeria",
            "latitude":float(loc.latitude),
            "longitude":float(loc.longitude),
            "active":bool(loc.active),
            "sample_every_minutes":int(settings.supabase_default_location_interval_minutes),
            "source":"iticas_local_sync"
        }]
        for p in probes:
            payload.append({
                "target_key":_target_key("probe",loc.id,p.sequence_no,float(p.latitude),float(p.longitude)),
                "target_type":"probe",
                "local_location_id":loc.id,
                "probe_sequence_no":p.sequence_no,
                "name":f"{loc.name} probe {p.sequence_no}",
                "road_name":loc.road_name or loc.name,
                "city":loc.city,
                "state":loc.state,
                "country":"Nigeria",
                "latitude":float(p.latitude),
                "longitude":float(p.longitude),
                "active":bool(loc.active),
                "sample_every_minutes":int(settings.supabase_default_probe_interval_minutes),
                "source":"iticas_local_sync"
            })
    result=await _request(
        "POST","/archive_targets",
        params={"on_conflict":"target_key"},
        payload=payload,
        prefer="resolution=merge-duplicates,return=representation"
    )
    return {"configured":True,"synced":len(payload),"result":result}


async def sync_all_to_cloud():
    if not configured():
        return {"configured":False,"locations":0,"targets":0}
    with SessionLocal() as db:
        ids=list(db.scalars(select(MonitoringLocation.id).where(MonitoringLocation.latitude.is_not(None),MonitoringLocation.longitude.is_not(None))).all())
    total=0
    errors=[]
    for lid in ids:
        try:
            r=await sync_location_to_cloud(int(lid)); total+=int(r.get("synced",0))
        except Exception as exc:
            errors.append({"location_id":lid,"error":str(exc)[:300]})
    return {"configured":True,"locations":len(ids),"targets":total,"errors":errors}


async def cloud_status():
    if not configured():
        return {"configured":False,"message":"Supabase autonomous archive is not configured on this ITICAS installation."}
    targets=await _request("GET","/archive_targets",params={"select":"target_key","active":"eq.true"})
    runs=await _request("GET","/archive_run_log",params={"select":"*","order":"started_at.desc","limit":"1"})
    count_resp=await _request("GET","/archive_observations",params={"select":"id","limit":"1"})
    # REST count is obtained separately so response body stays tiny.
    async with httpx.AsyncClient(timeout=settings.supabase_archive_timeout_seconds) as c:
        r=await c.get(_base()+"/archive_observations",params={"select":"id","limit":"1"},
                      headers={**_headers(),"Prefer":"count=exact"})
        total=None
        cr=r.headers.get("content-range","")
        if "/" in cr:
            try: total=int(cr.rsplit("/",1)[1])
            except Exception: pass
    last=runs[0] if isinstance(runs,list) and runs else None
    return {
        "configured":True,
        "active_targets":len(targets) if isinstance(targets,list) else 0,
        "observation_count":total,
        "latest_run":last,
        "collection_mode":"Supabase Cron + Edge Function",
        "pc_required":False,
    }


async def cloud_coverage_for_location(location_id:int,days:int=30):
    if not configured():
        return {"configured":False}
    since=(datetime.now(timezone.utc)-timedelta(days=max(1,int(days)))).isoformat()
    # Find cloud target keys belonging to this local location id.
    targets=await _request("GET","/archive_targets",params={
        "select":"target_key,target_type,probe_sequence_no,name",
        "local_location_id":f"eq.{int(location_id)}",
        "active":"eq.true"
    })
    keys=[x["target_key"] for x in targets] if isinstance(targets,list) else []
    if not keys:
        return {"configured":True,"targets":0,"observations":0,"first_observation":None,"last_observation":None}
    # PostgREST 'in' filter.
    key_filter="in.("+",".join(keys)+")"
    rows=await _request("GET","/archive_observations",params={
        "select":"observed_at,target_key",
        "target_key":key_filter,
        "observed_at":f"gte.{since}",
        "order":"observed_at.asc",
        "limit":"10000"
    })
    rows=rows if isinstance(rows,list) else []
    return {
        "configured":True,
        "targets":len(keys),
        "observations":len(rows),
        "first_observation":rows[0]["observed_at"] if rows else None,
        "last_observation":rows[-1]["observed_at"] if rows else None,
        "period_days":days
    }


async def _paged_observations(keys:list[str], since_iso:str, page_size:int=1000):
    if not keys:return []
    key_filter="in.("+",".join(keys)+")"
    out=[]; offset=0
    while True:
        rows=await _request("GET","/archive_observations",params={
            "select":"*","target_key":key_filter,"observed_at":f"gte.{since_iso}",
            "order":"observed_at.asc","limit":str(page_size),"offset":str(offset)
        })
        rows=rows if isinstance(rows,list) else []
        out.extend(rows)
        if len(rows)<page_size:break
        offset += page_size
        if offset>=500000:break
    return out


def _parse_remote_time(value):
    if not value:return None
    try:
        dt=datetime.fromisoformat(str(value).replace("Z","+00:00"))
        if dt.tzinfo is not None:dt=dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except Exception:return None


async def import_cloud_history(location_id:int,days:int=30):
    """Pull autonomous cloud observations into the local research database.

    This makes serverless history usable by the existing analytics/report engines
    without changing their validated calculations.
    """
    if not configured():return {"configured":False,"imported":0}
    days=max(1,min(int(days),3660))
    since=(datetime.now(timezone.utc)-timedelta(days=days)).isoformat()
    targets=await _request("GET","/archive_targets",params={
        "select":"target_key,target_type,probe_sequence_no,name",
        "local_location_id":f"eq.{int(location_id)}"
    })
    targets=targets if isinstance(targets,list) else []
    target_by_key={x["target_key"]:x for x in targets}
    rows=await _paged_observations(list(target_by_key),since)
    main_added=probe_added=skipped=0
    with SessionLocal() as db:
        probe_map={p.sequence_no:p for p in db.scalars(select(CorridorProbe).where(CorridorProbe.location_id==location_id)).all()}
        for r in rows:
            meta=target_by_key.get(r.get("target_key")) or {}
            dt=_parse_remote_time(r.get("observed_at"))
            if not dt:skipped+=1;continue
            if meta.get("target_type")=="location":
                existing=db.scalar(select(TrafficObservation.id).where(
                    TrafficObservation.location_id==location_id,
                    TrafficObservation.observed_at==dt,
                    TrafficObservation.provider=="TomTom Traffic API (Autonomous Cloud Archive)"
                ))
                if existing:skipped+=1;continue
                db.add(TrafficObservation(
                    location_id=location_id,observed_at=dt,
                    current_speed_kmh=r.get("current_speed_kmh"),free_flow_speed_kmh=r.get("free_flow_speed_kmh"),
                    congestion_index=r.get("congestion_index"),delay_seconds=r.get("delay_seconds"),
                    current_travel_time_seconds=r.get("current_travel_time_seconds"),
                    free_flow_travel_time_seconds=r.get("free_flow_travel_time_seconds"),confidence=r.get("confidence"),
                    road_closed=1 if r.get("road_closed") else 0,functional_road_class=r.get("functional_road_class"),
                    provider="TomTom Traffic API (Autonomous Cloud Archive)",source_timestamp=dt,
                    raw_reference=json.dumps({"remote_archive_id":r.get("id"),"target_key":r.get("target_key")})
                ));main_added+=1
            elif meta.get("target_type")=="probe":
                seq=meta.get("probe_sequence_no"); probe=probe_map.get(seq)
                if not probe:skipped+=1;continue
                existing=db.scalar(select(CorridorProbeObservation.id).where(
                    CorridorProbeObservation.probe_id==probe.id,
                    CorridorProbeObservation.observed_at==dt,
                    CorridorProbeObservation.provider=="TomTom Traffic API (Autonomous Cloud Archive)"
                ))
                if existing:skipped+=1;continue
                db.add(CorridorProbeObservation(
                    probe_id=probe.id,location_id=location_id,observed_at=dt,
                    current_speed_kmh=r.get("current_speed_kmh"),free_flow_speed_kmh=r.get("free_flow_speed_kmh"),
                    congestion_index=r.get("congestion_index"),delay_seconds=r.get("delay_seconds"),
                    current_travel_time_seconds=r.get("current_travel_time_seconds"),
                    free_flow_travel_time_seconds=r.get("free_flow_travel_time_seconds"),confidence=r.get("confidence"),
                    road_closed=1 if r.get("road_closed") else 0,provider="TomTom Traffic API (Autonomous Cloud Archive)",
                    provider_status="ok",raw_reference=json.dumps({"remote_archive_id":r.get("id"),"target_key":r.get("target_key")})
                ));probe_added+=1
        db.commit()
    return {"configured":True,"remote_rows":len(rows),"main_observations_imported":main_added,
            "probe_observations_imported":probe_added,"skipped_existing_or_unmatched":skipped,"period_days":days}
