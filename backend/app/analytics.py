from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from math import sqrt
from statistics import mean, median, pstdev
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select

from .config import settings
from .database import SessionLocal, MonitoringLocation, TrafficObservation, HistoricalTrafficSample

try:
    ANALYSIS_TZ = ZoneInfo("Africa/Lagos")
except ZoneInfoNotFoundError:
    # Windows/Python installations may not ship the IANA tz database.
    # Nigeria uses West Africa Time (UTC+01:00) year-round with no DST,
    # so this fixed-offset fallback is scientifically equivalent for ITICAS.
    ANALYSIS_TZ = timezone(timedelta(hours=1), name="Africa/Lagos")
CATEGORIES = ((0.20, "Free flow"), (0.35, "Light"), (0.50, "Moderate"), (0.70, "Heavy"), (1.01, "Severe"))


def category(ci):
    if ci is None:
        return "Unavailable"
    for upper, label in CATEGORIES:
        if ci < upper:
            return label
    return "Severe"


def _pearson(xs, ys):
    if len(xs) < 3:
        return None
    mx, my = mean(xs), mean(ys)
    dx = [x - mx for x in xs]
    dy = [y - my for y in ys]
    den = sqrt(sum(x * x for x in dx) * sum(y * y for y in dy))
    return round(sum(a * b for a, b in zip(dx, dy)) / den, 4) if den else None


def _aware_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _floor_hour(dt: datetime) -> datetime:
    return dt.replace(minute=0, second=0, microsecond=0)


def _mean_or_none(values, digits=4):
    vals = [v for v in values if v is not None]
    return round(mean(vals), digits) if vals else None


def _dataset_signature(rows) -> str:
    payload = "|".join(
        f"{r.id}:{_aware_utc(r.observed_at).isoformat()}:{r.current_speed_kmh}:{r.free_flow_speed_kmh}:{r.congestion_index}:{r.delay_seconds}"
        for r in rows
    )
    return sha256(payload.encode("utf-8")).hexdigest()[:16] if payload else "no-observations"


def _report_id(location_id: int, start: datetime, end: datetime, signature: str) -> str:
    payload = f"{location_id}|{start.isoformat()}|{end.isoformat()}|{signature}"
    return "ITICAS-" + sha256(payload.encode("utf-8")).hexdigest()[:12].upper()


def _period_rows(db, location_id: int, start_utc: datetime, end_utc: datetime):
    # SQLite stores DateTime without timezone in this application. Use naive UTC bounds for robust comparisons.
    start_db = start_utc.replace(tzinfo=None)
    end_db = end_utc.replace(tzinfo=None)
    return list(
        db.scalars(
            select(TrafficObservation)
            .where(
                TrafficObservation.location_id == location_id,
                TrafficObservation.observed_at >= start_db,
                TrafficObservation.observed_at <= end_db,
            )
            .order_by(TrafficObservation.observed_at)
        ).all()
    )


def analyze_location(location_id: int, days: int = 30):
    days = max(1, min(int(days), 3650))
    end_utc = datetime.now(timezone.utc)
    start_utc = end_utc - timedelta(days=days)

    with SessionLocal() as db:
        loc = db.get(MonitoringLocation, location_id)
        if not loc:
            return None
        rows = _period_rows(db, location_id, start_utc, end_utc)
        rows_24h = _period_rows(db, location_id, end_utc - timedelta(hours=24), end_utc)
        start_db = start_utc.replace(tzinfo=None)
        end_db = end_utc.replace(tzinfo=None)
        historical_rows = list(db.scalars(
            select(HistoricalTrafficSample).where(
                HistoricalTrafficSample.location_id == location_id,
                HistoricalTrafficSample.hour_start >= start_db,
                HistoricalTrafficSample.hour_start <= end_db,
            ).order_by(HistoricalTrafficSample.hour_start)
        ).all())

    speeds = [r.current_speed_kmh for r in rows if r.current_speed_kmh is not None]
    cis = [r.congestion_index for r in rows if r.congestion_index is not None]
    delays = [r.delay_seconds for r in rows if r.delay_seconds is not None]
    free = [r.free_flow_speed_kmh for r in rows if r.free_flow_speed_kmh is not None]

    by_clock_hour = defaultdict(list)
    by_weekday = defaultdict(list)
    by_calendar_day = defaultdict(list)
    cats = defaultdict(int)
    buckets = defaultdict(list)

    for r in rows:
        observed_utc = _aware_utc(r.observed_at)
        observed_local = observed_utc.astimezone(ANALYSIS_TZ)
        if r.congestion_index is not None:
            by_clock_hour[observed_local.hour].append(r.congestion_index)
            by_weekday[observed_local.strftime("%a")].append(r.congestion_index)
            by_calendar_day[observed_local.date().isoformat()].append(r.congestion_index)
            cats[category(r.congestion_index)] += 1
        buckets[_floor_hour(observed_local)].append(r)

    hourly_profile = [
        {"hour": h, "mean_congestion_index": round(mean(v), 4), "samples": len(v)}
        for h, v in sorted(by_clock_hour.items())
    ]
    weekday_profile = [
        {"day": d, "mean_congestion_index": round(mean(by_weekday[d]), 4), "samples": len(by_weekday[d])}
        for d in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        if by_weekday[d]
    ]
    daily_profile = [
        {"date": d, "mean_congestion_index": round(mean(v), 4), "samples": len(v)}
        for d, v in sorted(by_calendar_day.items())
    ]

    historical_buckets = {}
    for h in historical_rows:
        hu = _aware_utc(h.hour_start).astimezone(ANALYSIS_TZ)
        historical_buckets[_floor_hour(hu)] = h

    # True rolling hourly time series. Live observations take priority; historical-provider
    # hourly statistics fill only otherwise-missing hours and remain explicitly labelled.
    start_local_hour = _floor_hour(start_utc.astimezone(ANALYSIS_TZ))
    end_local_hour = _floor_hour(end_utc.astimezone(ANALYSIS_TZ))
    hourly_timeseries = []
    cursor = start_local_hour
    while cursor <= end_local_hour:
        vals = buckets.get(cursor, [])
        hist = historical_buckets.get(cursor)
        if vals:
            item = {
                "hour_start": cursor.isoformat(),
                "samples": len(vals),
                "data_status": "observed_live",
                "mean_speed_kmh": _mean_or_none([r.current_speed_kmh for r in vals], 2),
                "mean_free_flow_speed_kmh": _mean_or_none([r.free_flow_speed_kmh for r in vals], 2),
                "mean_congestion_index": _mean_or_none([r.congestion_index for r in vals], 4),
                "mean_delay_seconds": _mean_or_none([r.delay_seconds for r in vals], 2),
                "source": "ITICAS live monitoring / TomTom Traffic API",
            }
        elif hist:
            item = {
                "hour_start": cursor.isoformat(),
                "samples": hist.sample_size,
                "data_status": "historical_provider",
                "mean_speed_kmh": hist.average_speed_kmh,
                "mean_free_flow_speed_kmh": hist.reference_speed_kmh,
                "mean_congestion_index": hist.congestion_index,
                "mean_delay_seconds": None,
                "source": hist.provider,
            }
        else:
            item = {
                "hour_start": cursor.isoformat(), "samples": 0, "data_status": "missing",
                "mean_speed_kmh": None, "mean_free_flow_speed_kmh": None,
                "mean_congestion_index": None, "mean_delay_seconds": None, "source": None,
            }
        hourly_timeseries.append(item)
        cursor += timedelta(hours=1)


    # Day-by-day analytical breakdown. Each requested Nigeria-local calendar day is analysed
    # independently before the composite multi-day summary is produced. Missing hours remain explicit.
    day_groups = defaultdict(list)
    for item in hourly_timeseries:
        ds = str(item["hour_start"])[:10]
        day_groups[ds].append(item)
    day_by_day=[]
    for ds in sorted(day_groups):
        rr=day_groups[ds]
        available=[x for x in rr if x.get("data_status") != "missing"]
        ci_vals=[float(x["mean_congestion_index"]) for x in available if x.get("mean_congestion_index") is not None]
        speed_vals=[float(x["mean_speed_kmh"]) for x in available if x.get("mean_speed_kmh") is not None]
        delay_vals=[float(x["mean_delay_seconds"]) for x in available if x.get("mean_delay_seconds") is not None]
        peak=max((x for x in available if x.get("mean_congestion_index") is not None), key=lambda x: float(x["mean_congestion_index"]), default=None)
        day_by_day.append({
            "date":ds,
            "hours_with_evidence":len(available),
            "coverage_pct":round(100*len(available)/24,2),
            "mean_congestion_index":round(mean(ci_vals),4) if ci_vals else None,
            "max_congestion_index":round(max(ci_vals),4) if ci_vals else None,
            "mean_speed_kmh":round(mean(speed_vals),2) if speed_vals else None,
            "mean_delay_seconds":round(mean(delay_vals),2) if delay_vals else None,
            "peak_hour":peak.get("hour_start") if peak else None,
            "peak_congestion_index":round(float(peak["mean_congestion_index"]),4) if peak else None,
            "peak_category":category(float(peak["mean_congestion_index"])) if peak else None,
            "hourly":rr,
        })

    paired = [
        (r.current_speed_kmh, r.free_flow_speed_kmh)
        for r in rows
        if r.current_speed_kmh is not None and r.free_flow_speed_kmh is not None
    ]
    sr = [100 * (1 - a / b) for a, b in paired if b and b > 0]

    expected_interval_seconds = max(60, int(settings.monitoring_interval_seconds or 300))
    requested_hours = days * 24
    expected_samples = max(1, int(requested_hours * 3600 / expected_interval_seconds))
    observed_hours = sum(1 for b in hourly_timeseries if b["data_status"] == "observed_live")
    historical_hours = sum(1 for b in hourly_timeseries if b["data_status"] == "historical_provider")
    combined_hours = observed_hours + historical_hours
    hourly_coverage_pct = round(100 * observed_hours / max(1, len(hourly_timeseries)), 2)
    combined_hourly_coverage_pct = round(100 * combined_hours / max(1, len(hourly_timeseries)), 2)
    sample_coverage_pct = round(100 * len(rows) / expected_samples, 2)

    # Data readiness considers both count and temporal coverage. It does not manufacture missing traffic.
    if len(rows) < 12 or observed_hours < 4:
        suff = "insufficient"
    elif len(rows) < 48 or combined_hourly_coverage_pct < 20:
        suff = "limited"
    else:
        suff = "adequate"

    peak = max(hourly_profile, key=lambda x: x["mean_congestion_index"]) if hourly_profile else None
    first_obs = _aware_utc(rows[0].observed_at) if rows else None
    last_obs = _aware_utc(rows[-1].observed_at) if rows else None
    actual_span_hours = round((last_obs - first_obs).total_seconds() / 3600, 2) if len(rows) >= 2 else (0.0 if rows else None)
    older_than_24h = max(0, len(rows) - len(rows_24h))
    same_as_24h = days > 1 and len(rows) > 0 and older_than_24h == 0
    signature = _dataset_signature(rows)

    raw_observations = []
    for r in rows:
        observed_utc = _aware_utc(r.observed_at)
        raw_observations.append(
            {
                "id": r.id,
                "observed_at_utc": observed_utc.isoformat(),
                "observed_at_nigeria": observed_utc.astimezone(ANALYSIS_TZ).isoformat(),
                "current_speed_kmh": r.current_speed_kmh,
                "free_flow_speed_kmh": r.free_flow_speed_kmh,
                "congestion_index": r.congestion_index,
                "delay_seconds": r.delay_seconds,
                "confidence": r.confidence,
                "road_closed": bool(r.road_closed) if r.road_closed is not None else None,
                "provider": r.provider,
                "source_timestamp": _aware_utc(r.source_timestamp).isoformat() if r.source_timestamp else None,
            }
        )

    # Reliability and decision-support metrics.
    travel_times=[r.current_travel_time_seconds for r in rows if r.current_travel_time_seconds is not None]
    freeflow_times=[r.free_flow_travel_time_seconds for r in rows if r.free_flow_travel_time_seconds is not None and r.free_flow_travel_time_seconds>0]
    paired_tt=[(r.current_travel_time_seconds,r.free_flow_travel_time_seconds) for r in rows if r.current_travel_time_seconds is not None and r.free_flow_travel_time_seconds not in (None,0)]
    def _percentile(vals,p):
        vals=sorted(float(v) for v in vals if v is not None)
        if not vals:return None
        if len(vals)==1:return vals[0]
        k=(len(vals)-1)*p
        f=int(k); c=min(f+1,len(vals)-1)
        return vals[f]+(vals[c]-vals[f])*(k-f)
    avg_tt=mean(travel_times) if travel_times else None
    p95_tt=_percentile(travel_times,0.95)
    avg_ff=mean(freeflow_times) if freeflow_times else None
    travel_time_index=round(mean([a/b for a,b in paired_tt]),3) if paired_tt else None
    planning_time_index=round(p95_tt/avg_ff,3) if p95_tt is not None and avg_ff else None
    buffer_index_pct=round(100*(p95_tt-avg_tt)/avg_tt,2) if p95_tt is not None and avg_tt else None
    severe_share=round(100*sum(1 for x in cis if x>=0.7)/len(cis),2) if cis else None
    heavy_plus_share=round(100*sum(1 for x in cis if x>=0.5)/len(cis),2) if cis else None
    moderate_plus_share=round(100*sum(1 for x in cis if x>=0.35)/len(cis),2) if cis else None
    closure_share=round(100*sum(1 for r in rows if r.road_closed)/len(rows),2) if rows else None
    confidence_vals=[r.confidence for r in rows if r.confidence is not None]
    mean_confidence=round(mean(confidence_vals),4) if confidence_vals else None
    # Experimental ITICAS decision priority index (transparent research metric, not a standard).
    sev=mean(cis) if cis else 0
    persist=(heavy_plus_share or 0)/100
    delay_norm=min(1.0,(mean(delays) if delays else 0)/600)
    variability_norm=min(1.0,(pstdev(speeds) if len(speeds)>1 else 0)/30)
    coverage_norm=min(1.0,combined_hourly_coverage_pct/100)
    decision_priority_score=round(100*(0.40*sev+0.25*persist+0.20*delay_norm+0.10*variability_norm+0.05*coverage_norm),1)
    if decision_priority_score>=70: decision_priority_class='Very high'
    elif decision_priority_score>=50: decision_priority_class='High'
    elif decision_priority_score>=30: decision_priority_class='Moderate'
    else: decision_priority_class='Low'

    # Extended evidence and decision metrics. Historical provider hours are combined only at the
    # hourly-evidence level; live and provider historical origins remain distinguishable.
    combined_rows=[x for x in hourly_timeseries if x.get("data_status") in ("observed_live","historical_provider")]
    historical_only=[x for x in hourly_timeseries if x.get("data_status")=="historical_provider"]
    combined_speeds=[x.get("mean_speed_kmh") for x in combined_rows if x.get("mean_speed_kmh") is not None]
    combined_free=[x.get("mean_free_flow_speed_kmh") for x in combined_rows if x.get("mean_free_flow_speed_kmh") is not None]
    combined_ci=[x.get("mean_congestion_index") for x in combined_rows if x.get("mean_congestion_index") is not None]
    hist_speeds=[x.get("mean_speed_kmh") for x in historical_only if x.get("mean_speed_kmh") is not None]
    hist_ci=[x.get("mean_congestion_index") for x in historical_only if x.get("mean_congestion_index") is not None]

    p05_speed=_percentile(speeds,0.05); p15_speed=_percentile(speeds,0.15); p50_speed=_percentile(speeds,0.50); p85_speed=_percentile(speeds,0.85); p95_speed=_percentile(speeds,0.95)
    p50_delay=_percentile(delays,0.50); p85_delay=_percentile(delays,0.85); p95_delay=_percentile(delays,0.95)
    speed_cv_pct=round(100*pstdev(speeds)/mean(speeds),2) if len(speeds)>1 and mean(speeds) else None
    weekday_vals=[r for r in rows if _aware_utc(r.observed_at).astimezone(ANALYSIS_TZ).weekday()<5 and r.congestion_index is not None]
    weekend_vals=[r for r in rows if _aware_utc(r.observed_at).astimezone(ANALYSIS_TZ).weekday()>=5 and r.congestion_index is not None]
    weekday_ci=round(mean([r.congestion_index for r in weekday_vals]),4) if weekday_vals else None
    weekend_ci=round(mean([r.congestion_index for r in weekend_vals]),4) if weekend_vals else None
    am=[r for r in hourly_profile if 5<=r['hour']<12]; pm=[r for r in hourly_profile if 12<=r['hour']<20]
    peak_am=max(am,key=lambda x:x['mean_congestion_index']) if am else None
    peak_pm=max(pm,key=lambda x:x['mean_congestion_index']) if pm else None
    # Congestion episodes: consecutive available hours at CI >= 0.35; missing data breaks an episode.
    episode_count=0; longest_episode=0; current_episode=0
    for x in hourly_timeseries:
        ci=x.get('mean_congestion_index')
        if x.get('data_status')!='missing' and ci is not None and ci>=0.35:
            current_episode+=1
            if current_episode==1: episode_count+=1
            longest_episode=max(longest_episode,current_episode)
        else:
            current_episode=0
    # Trend slope in mean daily CI units/day using simple least squares over days with evidence.
    trend_slope=None
    if len(daily_profile)>=2:
        ys=[float(x['mean_congestion_index']) for x in daily_profile]; xs=list(range(len(ys)))
        mx,my=mean(xs),mean(ys); den=sum((x-mx)**2 for x in xs)
        if den: trend_slope=round(sum((x-mx)*(y-my) for x,y in zip(xs,ys))/den,5)
    evidence_grade='D'
    if combined_hourly_coverage_pct>=80: evidence_grade='A'
    elif combined_hourly_coverage_pct>=50: evidence_grade='B'
    elif combined_hourly_coverage_pct>=20: evidence_grade='C'
    congestion_burden=round(100*((mean(combined_ci) if combined_ci else 0))*((moderate_plus_share or 0)/100),2) if combined_ci else None
    temporal_stability=round(max(0,100-(speed_cv_pct or 0)),1) if speed_cv_pct is not None else None

    limitations = []
    if suff != "adequate":
        limitations.append(
            "Observed traffic coverage is not yet adequate for strong temporal inference; missing hours are shown explicitly and are not fabricated."
        )
    if same_as_24h:
        limitations.append(
            f"The selected {days}-day window currently contains the same {len(rows)} stored observations as the last 24 hours because no older observations exist in this window; summary values can therefore legitimately match the 24-hour report."
        )

    return {
        "scope": "Nigeria",
        "location": {
            "id": loc.id,
            "name": loc.name,
            "road_name": loc.road_name,
            "city": loc.city,
            "state": loc.state,
            "country": loc.country,
        },
        "period": {
            "days": days,
            "requested_from_utc": start_utc.isoformat(),
            "requested_to_utc": end_utc.isoformat(),
            "requested_from_nigeria": start_utc.astimezone(ANALYSIS_TZ).isoformat(),
            "requested_to_nigeria": end_utc.astimezone(ANALYSIS_TZ).isoformat(),
            # Backwards-compatible aliases.
            "from": start_utc.isoformat(),
            "to": end_utc.isoformat(),
            "timezone": "Africa/Lagos",
        },
        "coverage": {
            "first_observation_utc": first_obs.isoformat() if first_obs else None,
            "last_observation_utc": last_obs.isoformat() if last_obs else None,
            "actual_observation_span_hours": actual_span_hours,
            "requested_hours": requested_hours,
            "hour_buckets_total": len(hourly_timeseries),
            "hour_buckets_with_data": observed_hours,
            "historical_provider_hour_buckets": historical_hours,
            "combined_hour_buckets_with_data": combined_hours,
            "hourly_coverage_pct": hourly_coverage_pct,
            "combined_hourly_coverage_pct": combined_hourly_coverage_pct,
            "expected_samples_at_configured_interval": expected_samples,
            "sample_coverage_pct": sample_coverage_pct,
            "monitoring_interval_seconds": expected_interval_seconds,
            "observations_last_24h": len(rows_24h),
            "observations_older_than_24h_in_selected_window": older_than_24h,
            "same_dataset_as_last_24h": same_as_24h,
        },
        "data_quality": {
            "observations": len(rows),
            "valid_speed_observations": len(speeds),
            "sufficiency": suff,
            "provider_sources": sorted({r.provider for r in rows if r.provider}),
            "data_origin": "observed_live",
            "historical_provider_samples": len(historical_rows),
            "historical_provider": settings.traffic_stats_provider_name,
            "imputed_observations": 0,
            "synthetic_observations": 0,
        },
        "summary": {
            "mean_speed_kmh": round(mean(speeds), 2) if speeds else None,
            "median_speed_kmh": round(median(speeds), 2) if speeds else None,
            "speed_std_kmh": round(pstdev(speeds), 2) if len(speeds) > 1 else (0.0 if speeds else None),
            "mean_free_flow_speed_kmh": round(mean(free), 2) if free else None,
            "mean_congestion_index": round(mean(cis), 4) if cis else None,
            "max_congestion_index": round(max(cis), 4) if cis else None,
            "mean_delay_seconds": round(mean(delays), 2) if delays else None,
            "mean_speed_reduction_pct": round(mean(sr), 2) if sr else None,
            "peak_hour": peak,
            "speed_freeflow_correlation": _pearson([a for a, b in paired], [b for a, b in paired]),
            "travel_time_index": travel_time_index,
            "planning_time_index": planning_time_index,
            "buffer_index_pct": buffer_index_pct,
            "p95_travel_time_seconds": round(p95_tt,2) if p95_tt is not None else None,
            "moderate_plus_share_pct": moderate_plus_share,
            "heavy_plus_share_pct": heavy_plus_share,
            "severe_share_pct": severe_share,
            "road_closure_share_pct": closure_share,
            "mean_provider_confidence": mean_confidence,
            "iticas_decision_priority_score": decision_priority_score,
            "iticas_decision_priority_class": decision_priority_class,
            "speed_p05_kmh": round(p05_speed,2) if p05_speed is not None else None,
            "speed_p15_kmh": round(p15_speed,2) if p15_speed is not None else None,
            "speed_p50_kmh": round(p50_speed,2) if p50_speed is not None else None,
            "speed_p85_kmh": round(p85_speed,2) if p85_speed is not None else None,
            "speed_p95_kmh": round(p95_speed,2) if p95_speed is not None else None,
            "delay_p50_seconds": round(p50_delay,2) if p50_delay is not None else None,
            "delay_p85_seconds": round(p85_delay,2) if p85_delay is not None else None,
            "delay_p95_seconds": round(p95_delay,2) if p95_delay is not None else None,
            "speed_coefficient_of_variation_pct": speed_cv_pct,
            "weekday_mean_congestion_index": weekday_ci,
            "weekend_mean_congestion_index": weekend_ci,
            "peak_am": peak_am,
            "peak_pm": peak_pm,
            "congestion_episode_count": episode_count,
            "longest_congestion_episode_hours": longest_episode,
            "daily_congestion_trend_slope": trend_slope,
            "evidence_grade": evidence_grade,
            "iticas_congestion_burden_index": congestion_burden,
            "iticas_temporal_stability_score": temporal_stability,
        },
        "combined_evidence_summary": {
            "hourly_evidence_count": len(combined_rows),
            "historical_provider_hour_count": len(historical_only),
            "mean_speed_kmh": round(mean(combined_speeds),2) if combined_speeds else None,
            "mean_free_flow_speed_kmh": round(mean(combined_free),2) if combined_free else None,
            "mean_congestion_index": round(mean(combined_ci),4) if combined_ci else None,
            "historical_provider_mean_speed_kmh": round(mean(hist_speeds),2) if hist_speeds else None,
            "historical_provider_mean_congestion_index": round(mean(hist_ci),4) if hist_ci else None,
            "evidence_grade": evidence_grade,
            "note": "Equal-weight hourly evidence summary combining live hours with historical-provider hours only where live data are absent; origins remain explicit."
        },
        "categories": dict(cats),
        "hourly_profile": hourly_profile,
        "hourly_timeseries": hourly_timeseries,
        "day_by_day": day_by_day,
        "daily_profile": daily_profile,
        "weekday_profile": weekday_profile,
        "raw_observations": raw_observations,
        "report_identity": {
            "report_id": _report_id(location_id, start_utc, end_utc, signature),
            "dataset_signature": signature,
            "generated_at_utc": end_utc.isoformat(),
        },
        "validation": {
            "status": "provider_reference",
            "independent_traffic_benchmark": "not_configured",
            "statement": "Analytics retain live observations separately from historical-provider statistics. Historical Traffic Stats values are labelled as provider historical data; provider references are not independent ground truth. Decision-priority scoring is an experimental transparent ITICAS research metric and must be interpreted alongside coverage and validation status.",
        },
        "limitations": limitations,
    }


def network_summary(days: int = 30):
    with SessionLocal() as db:
        locs = list(db.scalars(select(MonitoringLocation).where(MonitoringLocation.active == 1)).all())
    items = []
    for loc in locs:
        a = analyze_location(loc.id, days)
        if a and a["summary"]["mean_congestion_index"] is not None:
            items.append(
                {
                    "location": a["location"],
                    "observations": a["data_quality"]["observations"],
                    "mean_congestion_index": a["summary"]["mean_congestion_index"],
                    "mean_speed_kmh": a["summary"]["mean_speed_kmh"],
                    "mean_delay_seconds": a["summary"]["mean_delay_seconds"],
                    "category": category(a["summary"]["mean_congestion_index"]),
                    "hourly_coverage_pct": a["coverage"]["hourly_coverage_pct"],
                }
            )
    items.sort(key=lambda x: x["mean_congestion_index"], reverse=True)
    return {
        "scope": "Nigeria",
        "period_days": days,
        "locations_with_data": len(items),
        "ranking": items,
        "validation_status": "provider_reference",
        "independent_traffic_benchmark": "not_configured",
    }
