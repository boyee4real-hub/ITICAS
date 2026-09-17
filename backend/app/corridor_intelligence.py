
from __future__ import annotations
from datetime import datetime, timezone
from statistics import mean, median, pstdev
from sqlalchemy import select, func

from .database import SessionLocal, MonitoringLocation, CorridorProbe, CorridorProbeObservation
from .tomtom_traffic import TomTomTrafficClient, ProviderRequestError, ProviderNotConfigured


def _severity(ci):
    if ci is None: return "unknown"
    if ci < .10: return "free"
    if ci < .25: return "light"
    if ci < .45: return "moderate"
    if ci < .65: return "heavy"
    return "severe"


async def acquire_corridor_probe_evidence(location_id:int, provider_factory=TomTomTrafficClient):
    with SessionLocal() as db:
        loc=db.get(MonitoringLocation,location_id)
        if not loc: raise ValueError("Location not found.")
        probes=list(db.scalars(select(CorridorProbe).where(CorridorProbe.location_id==location_id).order_by(CorridorProbe.sequence_no)).all())
    if not probes:
        return {"status":"no_probes","location_id":location_id,"successful":0,"failed":0,"message":"Generate corridor probes first."}
    client=provider_factory()
    successful=0; failed=0; rows=[]
    # ITICAS_STAGE05_CORRIDOR_METRICS
    from .traffic_quota import status as _qs
    _e0=dict((_qs('tomtom').get('monthly_events') or {}))
    for p in probes:
        observed_at=datetime.now(timezone.utc)
        try:
            payload=await client.fetch_flow(p.latitude,p.longitude)
            f=client.normalize_flow(payload,observed_at)
            if not f:
                raise RuntimeError("Provider returned no flow segment data.")
            with SessionLocal() as db:
                db.add(CorridorProbeObservation(
                    probe_id=p.id, location_id=location_id, observed_at=observed_at,
                    current_speed_kmh=f.get("current_speed_kmh"),
                    free_flow_speed_kmh=f.get("free_flow_speed_kmh"),
                    congestion_index=f.get("congestion_index"),
                    delay_seconds=f.get("delay_seconds"),
                    current_travel_time_seconds=f.get("current_travel_time_seconds"),
                    free_flow_travel_time_seconds=f.get("free_flow_travel_time_seconds"),
                    confidence=f.get("confidence"), road_closed=f.get("road_closed"),
                    provider=client.provider_name, provider_status="ok",
                    raw_reference=f.get("raw_reference")
                ));db.commit()
            successful+=1
            rows.append({"probe_id":p.id,"sequence_no":p.sequence_no,"chainage_m":p.chainage_m,
                         "current_speed_kmh":f.get("current_speed_kmh"),"free_flow_speed_kmh":f.get("free_flow_speed_kmh"),
                         "congestion_index":f.get("congestion_index"),"delay_seconds":f.get("delay_seconds"),
                         "confidence":f.get("confidence"),"severity":_severity(f.get("congestion_index"))})
        except (ProviderRequestError,ProviderNotConfigured) as exc:
            failed+=1
            category=getattr(exc,"category","provider_not_configured")
            with SessionLocal() as db:
                db.add(CorridorProbeObservation(probe_id=p.id,location_id=location_id,observed_at=observed_at,
                    provider=client.provider_name,provider_status="failed",error_category=category))
                db.commit()
            rows.append({"probe_id":p.id,"sequence_no":p.sequence_no,"chainage_m":p.chainage_m,"status":"failed","error_category":category})
        except Exception as exc:
            failed+=1
            rows.append({"probe_id":p.id,"sequence_no":p.sequence_no,"chainage_m":p.chainage_m,"status":"failed","error_category":type(exc).__name__})
    _e1=dict((_qs("tomtom").get("monthly_events") or {})); _d=lambda n:int(_e1.get(n,0))-int(_e0.get(n,0))
    return {"status":"ok" if successful else ("provider_unavailable" if _d("circuit_block")+_d("budget_block") else "failed"),"location_id":location_id,"probes":len(probes),"successful":successful,"failed":failed,"provider_calls_attempted":_d("success")+_d("quota_exhausted")+_d("rate_or_quota_limited")+_d("provider_failure"),"cache_hits":_d("cache_hit"),"provider_calls_prevented":_d("circuit_block")+_d("budget_block"),"rows":rows}


def corridor_analysis(location_id:int, days:int=30):
    with SessionLocal() as db:
        probes=list(db.scalars(select(CorridorProbe).where(CorridorProbe.location_id==location_id).order_by(CorridorProbe.sequence_no)).all())
        if not probes:
            return {"location_id":location_id,"probe_count":0,"observation_count":0,"status":"no_probes","rows":[]}
        ids=[p.id for p in probes]
        cutoff=datetime.now(timezone.utc).replace(tzinfo=None)
        from datetime import timedelta
        cutoff=cutoff-timedelta(days=days)
        obs=list(db.scalars(select(CorridorProbeObservation).where(
            CorridorProbeObservation.probe_id.in_(ids),
            CorridorProbeObservation.observed_at>=cutoff,
            CorridorProbeObservation.provider_status=="ok"
        ).order_by(CorridorProbeObservation.observed_at)).all())
    by_probe={p.id:[] for p in probes}
    for o in obs: by_probe.setdefault(o.probe_id,[]).append(o)
    rows=[]
    for p in probes:
        rr=by_probe.get(p.id,[])
        cis=[o.congestion_index for o in rr if o.congestion_index is not None]
        speeds=[o.current_speed_kmh for o in rr if o.current_speed_kmh is not None]
        delays=[o.delay_seconds for o in rr if o.delay_seconds is not None]
        conf=[o.confidence for o in rr if o.confidence is not None]
        rows.append({
            "probe_id":p.id,"sequence_no":p.sequence_no,"chainage_m":p.chainage_m,
            "latitude":p.latitude,"longitude":p.longitude,"observations":len(rr),
            "mean_speed_kmh":round(mean(speeds),2) if speeds else None,
            "mean_congestion_index":round(mean(cis),4) if cis else None,
            "max_congestion_index":round(max(cis),4) if cis else None,
            "mean_delay_seconds":round(mean(delays),2) if delays else None,
            "mean_confidence":round(mean(conf),4) if conf else None,
            "severity":_severity(mean(cis)) if cis else "unknown"
        })
    ci_values=[r["mean_congestion_index"] for r in rows if r["mean_congestion_index"] is not None]
    mu=mean(ci_values) if ci_values else None
    sd=pstdev(ci_values) if len(ci_values)>1 else 0
    for r in rows:
        v=r["mean_congestion_index"]
        z=(v-mu)/sd if v is not None and mu is not None and sd>0 else None
        r["corridor_z_score"]=round(z,4) if z is not None else None
        # Screening flag only; true inferential hotspot analysis requires repeated, spatially adequate evidence.
        r["screening_hotspot"]=bool(z is not None and z>=1.645 and r["observations"]>=3)
    repeated=sum(1 for r in rows if r["observations"]>=3)
    inferential_ready=len(rows)>=8 and repeated>=8
    return {
        "location_id":location_id,"period_days":days,"probe_count":len(probes),"observation_count":len(obs),
        "probes_with_repeated_evidence":repeated,"inferential_hotspot_ready":inferential_ready,
        "scientific_note":"Corridor z-scores are screening indicators. Gi*/Local Moran inference remains withheld until spatial and repeated-evidence requirements are met.",
        "rows":rows
    }


def workflow_status(location_id:int, days:int=30):
    from .research_engine import objective_matrix, survey_summary
    from .reporting import _latest_segment_coords
    obj=objective_matrix(location_id,days)
    survey=survey_summary(location_id)
    with SessionLocal() as db:
        probe_count=db.scalar(select(func.count(CorridorProbe.id)).where(CorridorProbe.location_id==location_id)) or 0
        probe_obs=db.scalar(select(func.count(CorridorProbeObservation.id)).where(CorridorProbeObservation.location_id==location_id, CorridorProbeObservation.provider_status=="ok")) or 0
    geom=len(_latest_segment_coords(location_id) or [])
    steps=[
        {"step":1,"name":"Choose study road and period","complete":True,"action":"Select the study target above."},
        {"step":2,"name":"Prepare road / corridor","complete":geom>=2 and probe_count>=2,"action":"Generate corridor probes after traffic geometry is available."},
        {"step":3,"name":"Collect evidence","complete":probe_obs>=probe_count and probe_count>0,"action":"Run corridor traffic scan; field GNSS is required only when the research objective demands field GPS/GNSS evidence."},
        {"step":4,"name":"Run research analysis","complete":obj is not None and obj["complete_objectives"]>=2,"action":"Run research analysis to update objectives and corridor intelligence."},
        {"step":5,"name":"Review outputs","complete":True,"action":"Review readiness, objective matrix and available output catalogue."},
        {"step":6,"name":"Export study","complete":True,"action":"Download the complete research package."},
    ]
    next_step=next((x["step"] for x in steps if not x["complete"]),6)
    return {"steps":steps,"next_step":next_step,"probe_count":probe_count,"probe_observations":probe_obs,
            "gnss_points":survey["points"],"research_objectives_complete":obj["complete_objectives"] if obj else 0}
