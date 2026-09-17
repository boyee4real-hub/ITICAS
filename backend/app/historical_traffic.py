from __future__ import annotations
import asyncio, gzip, json, urllib.parse, urllib.request, urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select, and_
from .config import settings
from .database import SessionLocal, MonitoringLocation, TrafficObservation, HistoricalBackfillJob, HistoricalTrafficSample

WAT = timezone(timedelta(hours=1), name="Africa/Lagos")
BASE = "https://api.tomtom.com/traffic/trafficstats"

class HistoricalTrafficUnavailable(RuntimeError):
    def __init__(self, message, category="historical_provider_error", status_code=502):
        super().__init__(message)
        self.category=category
        self.status_code=status_code

def effective_key():
    return settings.traffic_stats_api_key or settings.tomtom_api_key

def configured():
    return bool(effective_key())

def _request_json(url, method="GET", body=None, timeout=None):
    data=None
    headers={"Accept":"application/json","User-Agent":"ITICAS/0.11"}
    if body is not None:
        data=json.dumps(body).encode("utf-8")
        headers["Content-Type"]="application/json"
    req=urllib.request.Request(url,data=data,headers=headers,method=method)
    try:
        with urllib.request.urlopen(req,timeout=timeout or settings.traffic_stats_timeout_seconds) as r:
            raw=r.read()
            return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as e:
        text=e.read(700).decode("utf-8","replace")
        category=("historical_authentication_failure" if e.code==401 else "historical_entitlement_forbidden" if e.code==403 else "historical_provider_http_error")
        msg=("Traffic Stats access is forbidden for this key (HTTP 403). The key is present, but the account/key is not entitled to Route Analysis. Obtain/activate a TomTom MOVE / Traffic Analytics trial or licensed Traffic Stats key; ITICAS cannot bypass provider entitlement." if e.code==403 else f"Traffic Stats HTTP {e.code}: {text}")
        raise HistoricalTrafficUnavailable(msg,category,e.code) from e
    except Exception as e:
        raise HistoricalTrafficUnavailable(f"Traffic Stats connection failed: {e}","historical_network_failure",502) from e

def _latest_segment_coords(location_id:int):
    with SessionLocal() as db:
        row=db.scalar(select(TrafficObservation).where(
            TrafficObservation.location_id==location_id,
            TrafficObservation.segment_geometry_json.is_not(None)
        ).order_by(TrafficObservation.observed_at.desc()))
    if not row or not row.segment_geometry_json:
        return None
    try:
        obj=json.loads(row.segment_geometry_json)
        pts=obj.get("coordinate") or obj.get("coordinates") or []
        coords=[]
        for p in pts:
            if isinstance(p,dict):
                lat=p.get("latitude"); lon=p.get("longitude")
            elif isinstance(p,(list,tuple)) and len(p)>=2:
                lon,lat=p[0],p[1]
            else:
                continue
            if lat is not None and lon is not None:
                coords.append({"latitude":float(lat),"longitude":float(lon)})
        return coords if len(coords)>=2 else None
    except Exception:
        return None

def _route_for_location(location_id:int):
    with SessionLocal() as db:
        loc=db.get(MonitoringLocation,location_id)
        if not loc:
            raise HistoricalTrafficUnavailable("Monitoring location not found.","location_not_found",404)
        if loc.latitude is None or loc.longitude is None:
            raise HistoricalTrafficUnavailable("Monitoring location has no coordinates.","missing_coordinates",422)
    coords=_latest_segment_coords(location_id)
    if not coords:
        # A short route around the point is a fallback only for job creation.
        # The UI warns that a live segment geometry should preferably be acquired first.
        lat=float(loc.latitude); lon=float(loc.longitude)
        d=0.004
        coords=[{"latitude":lat,"longitude":lon-d},{"latitude":lat,"longitude":lon+d}]
    # Keep a bounded set of via points so route map matching follows the actual live segment.
    if len(coords)>14:
        step=max(1,(len(coords)-2)//10)
        via=coords[1:-1:step][:10]
    else:
        via=coords[1:-1]
    return loc, coords[0], via, coords[-1]

def _time_sets():
    days=["MON","TUE","WED","THU","FRI","SAT","SUN"]
    out=[]
    for h in range(24):
        nxt=h+1
        start=f"{h:02d}:00"
        end="24:00" if nxt==24 else f"{nxt:02d}:00"
        out.append({"name":f"H{h:02d}","timeGroups":[{"days":days,"times":[f"{start}-{end}"]}]})
    return out

def _date_ranges(start_date, end_date):
    out=[]
    d=start_date
    while d<=end_date:
        s=d.isoformat()
        out.append({"name":s,"from":s,"to":s})
        d += timedelta(days=1)
    return out

def _chunks(start_date, end_date, size=24):
    d=start_date
    while d<=end_date:
        e=min(end_date,d+timedelta(days=size-1))
        yield d,e
        d=e+timedelta(days=1)

def submit_backfill(location_id:int, days:int=30):
    key=effective_key()
    if not key:
        raise HistoricalTrafficUnavailable(
            "TomTom Traffic Stats access is not configured. Configure a Traffic Stats key/trial before requesting historical backfill.",
            "historical_provider_not_configured",503)
    days=max(1,min(int(days),366))
    loc,start,via,end=_route_for_location(location_id)
    today=datetime.now(WAT).date()
    end_date=today-timedelta(days=1)  # completed historical days only
    start_date=end_date-timedelta(days=days-1)
    created=[]
    for chunk_start,chunk_end in _chunks(start_date,end_date):
        body={
            "jobName":f"ITICAS {loc.name} {chunk_start} to {chunk_end}",
            "distanceUnit":"KILOMETERS",
            "routes":[{
                "name":f"{loc.name} - {loc.road_name or loc.name}",
                "start":start,
                "via":via,
                "end":end,
                "fullTraversal":False,
                "zoneId":"Africa/Lagos",
                "probeSource":"ALL"
            }],
            "dateRanges":_date_ranges(chunk_start,chunk_end),
            "timeSets":_time_sets(),
            "acceptMode":"AUTO",
            "averageSampleSizeThreshold":0
        }
        url=f"{BASE}/routeanalysis/1?"+urllib.parse.urlencode({"key":key})
        result=_request_json(url,"POST",body)
        provider_job_id=str(result.get("jobId") or "")
        if not provider_job_id:
            raise HistoricalTrafficUnavailable(f"Traffic Stats did not return a jobId: {result}","historical_provider_response_error",502)
        with SessionLocal() as db:
            job=HistoricalBackfillJob(
                location_id=location_id,provider=settings.traffic_stats_provider_name,
                provider_job_id=provider_job_id,
                requested_from=datetime.combine(chunk_start,datetime.min.time()),
                requested_to=datetime.combine(chunk_end,datetime.max.time()),
                status="submitted",message="Historical hourly Route Analysis job submitted."
            )
            db.add(job); db.commit(); db.refresh(job)
            created.append(job.id)
    return {"status":"submitted","location_id":location_id,"days":days,"job_ids":created,"chunks":len(created)}

def _download_result(url:str):
    req=urllib.request.Request(url,headers={"User-Agent":"ITICAS/0.11","Accept":"application/json,*/*"})
    with urllib.request.urlopen(req,timeout=settings.traffic_stats_timeout_seconds) as r:
        raw=r.read()
        ctype=(r.headers.get("Content-Type") or "").lower()
    if url.lower().endswith(".gz") or raw[:2]==b"\\x1f\\x8b" or "gzip" in ctype:
        raw=gzip.decompress(raw)
    return json.loads(raw.decode("utf-8"))

def _p85(percentiles):
    # 5,10,...,95 => 17th item (index 16) is 85th percentile.
    try:
        return float(percentiles[16]) if percentiles and len(percentiles)>=17 else None
    except Exception:
        return None

def _ingest_result(local_job_id:int, provider_job_id:str, data:dict):
    pref=data.get("userPreference") or {}
    date_ranges={str(x.get("@id")):x for x in pref.get("dateRanges",[]) if x.get("@id") is not None}
    time_sets={str(x.get("@id")):x for x in pref.get("timeSets",[]) if x.get("@id") is not None}
    routes=data.get("routes") or []
    if not routes:
        return 0
    summaries=routes[0].get("summaries") or []
    inserted=0
    with SessionLocal() as db:
        job=db.get(HistoricalBackfillJob,local_job_id)
        location_id=job.location_id if job else None
        for s in summaries:
            dr=date_ranges.get(str(s.get("dateRange"))) or {}
            ts=time_sets.get(str(s.get("timeSet"))) or {}
            date_name=dr.get("from") or dr.get("name")
            ts_name=ts.get("name","")
            if not date_name or not ts_name.startswith("H"):
                continue
            try:
                hour=int(ts_name[1:3])
                local_dt=datetime.fromisoformat(date_name).replace(hour=hour,tzinfo=WAT)
                hour_utc=local_dt.astimezone(timezone.utc).replace(tzinfo=None)
            except Exception:
                continue
            avg=s.get("harmonicAverageSpeed")
            if avg is None: avg=s.get("averageSpeed")
            med=s.get("medianSpeed")
            ref=_p85(s.get("speedPercentiles"))
            ci=None
            if avg is not None and ref not in (None,0):
                ci=max(0.0,min(1.0,1-float(avg)/float(ref)))
            existing=db.scalar(select(HistoricalTrafficSample).where(
                HistoricalTrafficSample.location_id==location_id,
                HistoricalTrafficSample.hour_start==hour_utc,
                HistoricalTrafficSample.provider_job_id==provider_job_id
            ))
            if existing:
                continue
            db.add(HistoricalTrafficSample(
                location_id=location_id,hour_start=hour_utc,
                average_speed_kmh=float(avg) if avg is not None else None,
                harmonic_average_speed_kmh=float(s.get("harmonicAverageSpeed")) if s.get("harmonicAverageSpeed") is not None else None,
                median_speed_kmh=float(med) if med is not None else None,
                reference_speed_kmh=ref,
                congestion_index=ci,
                average_travel_time_seconds=float(s.get("averageTravelTime")) if s.get("averageTravelTime") is not None else None,
                sample_size=float(s.get("averageSampleSize")) if s.get("averageSampleSize") is not None else None,
                provider=settings.traffic_stats_provider_name,
                provider_job_id=provider_job_id,
                provenance_json=json.dumps({"route_summary":s,"date_range":dr,"time_set":ts},separators=(",",":"))
            ))
            inserted += 1
        if job:
            job.status="ingested"
            job.message=f"Ingested {inserted} historical hourly provider samples."
            job.updated_at=datetime.now(timezone.utc)
        db.commit()
    return inserted

def refresh_job(local_job_id:int):
    key=effective_key()
    if not key:
        raise HistoricalTrafficUnavailable("Traffic Stats access is not configured.","historical_provider_not_configured",503)
    with SessionLocal() as db:
        job=db.get(HistoricalBackfillJob,local_job_id)
        if not job:
            raise HistoricalTrafficUnavailable("Historical backfill job not found.","historical_job_not_found",404)
        provider_job_id=job.provider_job_id
    url=f"{BASE}/status/1/{urllib.parse.quote(str(provider_job_id))}?"+urllib.parse.urlencode({"key":key})
    result=_request_json(url)
    state=str(result.get("jobState") or "UNKNOWN")
    urls=result.get("urls") or []
    with SessionLocal() as db:
        job=db.get(HistoricalBackfillJob,local_job_id)
        job.status=state.lower()
        job.updated_at=datetime.now(timezone.utc)
        job.result_urls_json=json.dumps(urls) if urls else None
        job.message="Traffic Stats job state: "+state
        db.commit()
    ingested=0
    if state=="DONE":
        json_url=next((u for u in urls if "json" in u.lower() and "geojson" not in u.lower()),None)
        if json_url:
            data=_download_result(json_url)
            ingested=_ingest_result(local_job_id,str(provider_job_id),data)
    return {"job_id":local_job_id,"provider_job_id":provider_job_id,"state":state,"ingested_samples":ingested}

def list_jobs(limit=100):
    with SessionLocal() as db:
        rows=db.scalars(select(HistoricalBackfillJob).order_by(HistoricalBackfillJob.requested_at.desc()).limit(limit)).all()
        return [{
            "id":r.id,"location_id":r.location_id,"provider_job_id":r.provider_job_id,
            "from":r.requested_from.isoformat(),"to":r.requested_to.isoformat(),
            "status":r.status,"message":r.message,"requested_at":r.requested_at.isoformat()
        } for r in rows]

def coverage(location_id:int, days:int=30):
    end=datetime.now(timezone.utc).replace(tzinfo=None)
    start=end-timedelta(days=max(1,min(int(days),366)))
    with SessionLocal() as db:
        live=db.scalars(select(TrafficObservation).where(
            TrafficObservation.location_id==location_id,
            TrafficObservation.observed_at>=start,
            TrafficObservation.observed_at<=end
        )).all()
        hist=db.scalars(select(HistoricalTrafficSample).where(
            HistoricalTrafficSample.location_id==location_id,
            HistoricalTrafficSample.hour_start>=start,
            HistoricalTrafficSample.hour_start<=end
        )).all()
    live_hours={x.observed_at.replace(minute=0,second=0,microsecond=0) for x in live}
    hist_hours={x.hour_start.replace(minute=0,second=0,microsecond=0) for x in hist}
    expected=max(1,days*24)
    combined=live_hours|hist_hours
    return {
        "location_id":location_id,"days":days,
        "live_observations":len(live),"live_hours":len(live_hours),
        "historical_provider_samples":len(hist),"historical_hours":len(hist_hours),
        "combined_unique_hours":len(combined),
        "expected_hours":expected,
        "combined_hourly_coverage_percent":round(100*len(combined)/expected,2),
        "traffic_stats_configured":configured(),
        "historical_provider":settings.traffic_stats_provider_name,
        "data_origins":["observed_live","historical_provider"],
        "synthetic_records":0,"imputed_records":0
    }


def pending_jobs(limit=10):
    terminal={"done","error","rejected","cancelled","expired"}
    with SessionLocal() as db:
        rows=db.scalars(select(HistoricalBackfillJob).order_by(HistoricalBackfillJob.requested_at.asc()).limit(200)).all()
        return [r.id for r in rows if (r.status or '').lower() not in terminal][:limit]

def refresh_pending_jobs_once(limit=5):
    results=[]
    for job_id in pending_jobs(limit):
        try:
            results.append(refresh_job(job_id))
        except Exception as exc:
            results.append({"job_id":job_id,"state":"REFRESH_ERROR","message":str(exc)})
    return results

async def auto_refresh_loop(stop_event):
    while not stop_event.is_set():
        if configured():
            try:
                await asyncio.to_thread(refresh_pending_jobs_once,5)
            except Exception:
                pass
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=max(5,int(settings.historical_auto_refresh_seconds)))
        except asyncio.TimeoutError:
            pass
