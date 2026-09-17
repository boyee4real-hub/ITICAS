from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
import csv
import io
import math
from typing import Any

from sqlalchemy import select

from .config import settings
from .database import SessionLocal, MonitoringLocation
from .supabase_archive import configured, _request, _headers, _base, _paged_observations


def _iso(dt: datetime | None) -> str | None:
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None



async def _paged_get(path: str, params: dict[str, str] | None = None, page_size: int = 1000, hard_cap: int = 10000) -> list[dict[str, Any]]:
    params = dict(params or {})
    out: list[dict[str, Any]] = []
    offset = 0
    while offset < hard_cap:
        q = {**params, "limit": str(page_size), "offset": str(offset)}
        rows = await _request("GET", path, params=q)
        rows = rows if isinstance(rows, list) else []
        out.extend(rows)
        if len(rows) < page_size:
            break
        offset += page_size
    return out

async def _count(path: str, params: dict[str, str] | None = None) -> int | None:
    if not configured():
        return None
    params = dict(params or {})
    params.setdefault("select", "id")
    params.setdefault("limit", "1")
    import httpx
    async with httpx.AsyncClient(timeout=settings.supabase_archive_timeout_seconds) as client:
        r = await client.get(_base() + path, params=params, headers={**_headers(), "Prefer": "count=exact"})
        if r.status_code >= 400:
            raise RuntimeError(f"Supabase archive HTTP {r.status_code}: {r.text[:500]}")
        cr = r.headers.get("content-range", "")
        if "/" in cr:
            tail = cr.rsplit("/", 1)[1]
            if tail != "*":
                return int(tail)
    return None


async def _first_last_observation() -> tuple[str | None, str | None]:
    first = await _request("GET", "/archive_observations", params={"select": "observed_at", "order": "observed_at.asc", "limit": "1"})
    last = await _request("GET", "/archive_observations", params={"select": "observed_at", "order": "observed_at.desc", "limit": "1"})
    f = first[0]["observed_at"] if isinstance(first, list) and first else None
    l = last[0]["observed_at"] if isinstance(last, list) and last else None
    return f, l


async def archive_overview() -> dict[str, Any]:
    if not configured():
        return {"configured": False, "message": "Supabase autonomous archive is not configured."}

    targets = await _paged_get("/archive_targets", {
        "select": "target_key,target_type,local_location_id,name,road_name,city,state,active,sample_every_minutes,last_sampled_at,last_attempt_at,last_status,created_at",
        "order": "state.asc,city.asc,name.asc",
    }, hard_cap=20000)
    runs = await _request("GET", "/archive_run_log", params={
        "select": "*", "order": "started_at.desc", "limit": "50"
    })
    runs = runs if isinstance(runs, list) else []
    total_obs = await _count("/archive_observations")
    first_obs, last_obs = await _first_last_observation()

    active = [t for t in targets if t.get("active")]
    locations = [t for t in active if t.get("target_type") == "location"]
    probes = [t for t in active if t.get("target_type") == "probe"]
    failures = [t for t in active if str(t.get("last_status") or "").lower().startswith("failed")]
    stale_cutoff = datetime.now(timezone.utc) - timedelta(minutes=max(15, settings.supabase_default_location_interval_minutes * 3))
    stale_locations = []
    for t in locations:
        last = _dt(t.get("last_sampled_at"))
        if last is None or last < stale_cutoff:
            stale_locations.append(t)

    completed = [r for r in runs if str(r.get("status") or "").startswith("completed")]
    total_attempted = sum(int(r.get("attempted") or 0) for r in completed)
    total_success = sum(int(r.get("successful") or 0) for r in completed)
    success_rate = round((100.0 * total_success / total_attempted), 2) if total_attempted else None

    by_state = Counter((t.get("state") or "Unspecified") for t in locations)
    by_city = Counter((t.get("city") or "Unspecified") for t in locations)

    health = "healthy"
    if failures or stale_locations:
        health = "attention"
    if not runs or not last_obs:
        health = "not_collecting"

    return {
        "configured": True,
        "health": health,
        "collection_mode": "Supabase Cron + Edge Function",
        "pc_required": False,
        "total_targets": len(targets),
        "active_targets": len(active),
        "active_locations": len(locations),
        "active_probes": len(probes),
        "observation_count": total_obs,
        "archive_started": first_obs,
        "latest_observation": last_obs,
        "latest_run": runs[0] if runs else None,
        "recent_runs": runs[:10],
        "recent_success_rate_pct": success_rate,
        "failed_targets": len(failures),
        "stale_locations": len(stale_locations),
        "states_with_active_locations": len(by_state),
        "cities_with_active_locations": len(by_city),
        "top_states": [{"state": k, "locations": v} for k, v in by_state.most_common(20)],
        "top_cities": [{"city": k, "locations": v} for k, v in by_city.most_common(20)],
        "scientific_boundary": "Archive readiness applies only to periods accumulated after a target entered autonomous monitoring; ITICAS does not fabricate retrospective history.",
    }


async def archive_failures(limit: int = 100) -> dict[str, Any]:
    if not configured():
        return {"configured": False, "targets": [], "runs": []}
    targets = await _paged_get("/archive_targets", {
        "select": "target_key,target_type,local_location_id,name,road_name,city,state,last_attempt_at,last_sampled_at,last_status,sample_every_minutes",
        "active": "eq.true", "order": "last_attempt_at.desc"
    }, hard_cap=max(1000, min(limit, 5000)))
    bad = [x for x in targets if str(x.get("last_status") or "").lower().startswith("failed")]
    runs = await _request("GET", "/archive_run_log", params={
        "select": "*", "failed": "gt.0", "order": "started_at.desc", "limit": "50"
    })
    return {"configured": True, "targets": bad, "runs": runs if isinstance(runs, list) else []}


async def location_research_readiness(location_id: int, days: int = 30) -> dict[str, Any]:
    days = max(1, min(int(days), 3660))
    if not configured():
        return {"configured": False, "location_id": location_id, "days": days}

    with SessionLocal() as db:
        loc = db.get(MonitoringLocation, int(location_id))
        if not loc:
            raise KeyError("Location not found")
        location = {"id": loc.id, "name": loc.name, "road_name": loc.road_name, "city": loc.city, "state": loc.state,
                    "latitude": loc.latitude, "longitude": loc.longitude, "active": bool(loc.active)}

    targets = await _paged_get("/archive_targets", {
        "select": "target_key,target_type,probe_sequence_no,name,sample_every_minutes,last_sampled_at,last_status,created_at",
        "local_location_id": f"eq.{int(location_id)}", "order": "target_type.asc,probe_sequence_no.asc"
    }, hard_cap=10000)
    if not targets:
        return {"configured": True, "location": location, "days": days, "readiness": "not_archived", "score": 0,
                "message": "No autonomous cloud archive target exists for this location."}

    since_dt = datetime.now(timezone.utc) - timedelta(days=days)
    since = since_dt.isoformat()
    keys = [t["target_key"] for t in targets]
    key_filter = "in.(" + ",".join(keys) + ")"
    total = await _count("/archive_observations", {"target_key": key_filter, "observed_at": f"gte.{since}"})
    rows = await _paged_observations(keys, since, page_size=1000)

    per_target = defaultdict(list)
    for r in rows:
        per_target[r.get("target_key")].append(r)

    target_metrics = []
    weighted_expected = 0.0
    weighted_actual = 0
    now = datetime.now(timezone.utc)
    for t in targets:
        created = _dt(t.get("created_at")) or since_dt
        effective_start = max(since_dt, created)
        minutes = max(0.0, (now - effective_start).total_seconds() / 60.0)
        interval = max(5, int(t.get("sample_every_minutes") or 15))
        expected = max(1, int(math.floor(minutes / interval)) + 1) if minutes > 0 else 1
        actual = len(per_target.get(t["target_key"], []))
        completeness = min(100.0, 100.0 * actual / expected) if expected else 0.0
        weighted_expected += expected
        weighted_actual += actual
        target_metrics.append({
            "target_key": t["target_key"], "target_type": t.get("target_type"), "name": t.get("name"),
            "probe_sequence_no": t.get("probe_sequence_no"), "sample_every_minutes": interval,
            "expected_samples": expected, "actual_samples": actual, "completeness_pct": round(completeness, 1),
            "last_sampled_at": t.get("last_sampled_at"), "last_status": t.get("last_status")
        })

    completeness = min(100.0, 100.0 * weighted_actual / weighted_expected) if weighted_expected else 0.0
    observed_times = [_dt(r.get("observed_at")) for r in rows]
    observed_times = [x for x in observed_times if x]
    first = min(observed_times).isoformat() if observed_times else None
    last = max(observed_times).isoformat() if observed_times else None

    main_target = next((t for t in targets if t.get("target_type") == "location"), None)
    main_rows = per_target.get(main_target["target_key"], []) if main_target else []
    valid_speed = sum(1 for r in main_rows if r.get("current_speed_kmh") is not None and r.get("free_flow_speed_kmh") is not None)
    data_quality_pct = round(100.0 * valid_speed / len(main_rows), 1) if main_rows else 0.0

    diagnostic_partial = total is not None and total > len(rows)
    if len(rows) == 0:
        readiness, score = "insufficient", 0
    else:
        score = int(round(0.7 * min(100.0, completeness) + 0.3 * data_quality_pct))
        if diagnostic_partial:
            score = min(score, 79)
            readiness = "usable_with_caution" if score >= 50 else "insufficient"
        elif score >= 80:
            readiness = "research_ready"
        elif score >= 50:
            readiness = "usable_with_caution"
        else:
            readiness = "insufficient"

    day_counts = Counter()
    for dtv in observed_times:
        day_counts[dtv.date().isoformat()] += 1
    calendar = [{"date": (since_dt.date() + timedelta(days=i)).isoformat(),
                 "observations": day_counts.get((since_dt.date() + timedelta(days=i)).isoformat(), 0)}
                for i in range(days + 1)]

    return {
        "configured": True,
        "location": location,
        "days": days,
        "target_count": len(targets),
        "observation_count": total if total is not None else len(rows),
        "loaded_rows_for_diagnostics": len(rows),
        "diagnostic_partial": diagnostic_partial,
        "first_observation": first,
        "last_observation": last,
        "completeness_pct": round(completeness, 1),
        "data_quality_pct": data_quality_pct,
        "readiness": readiness,
        "score": score,
        "target_metrics": target_metrics,
        "calendar": calendar,
        "limitations": [
            "Completeness is estimated from target creation time, requested period and configured sampling interval.",
            "Provider/network failures can create legitimate gaps; ITICAS reports rather than fabricates missing observations.",
            "Autonomous history begins when a target is registered and cannot reconstruct earlier traffic conditions by itself.",
            *( ["The requested period exceeds the in-app diagnostic row cap; readiness is conservatively limited and full export/import should be used for exhaustive analysis."] if diagnostic_partial else [] ),
        ],
    }


async def archive_research_csv(location_id: int, days: int = 30) -> tuple[str, bytes]:
    days = max(1, min(int(days), 3660))
    if not configured():
        raise RuntimeError("Supabase autonomous archive is not configured.")
    with SessionLocal() as db:
        loc = db.get(MonitoringLocation, int(location_id))
        if not loc:
            raise KeyError("Location not found")
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in loc.name)[:80] or f"location_{location_id}"
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    targets = await _paged_get("/archive_targets", {
        "select": "target_key,target_type,probe_sequence_no,name,road_name,city,state,latitude,longitude,sample_every_minutes",
        "local_location_id": f"eq.{int(location_id)}"
    }, hard_cap=10000)
    meta = {t["target_key"]: t for t in targets}
    if not meta:
        raise RuntimeError("No cloud archive targets exist for this location.")
    rows = await _paged_observations(list(meta), since, page_size=1000)
    out = io.StringIO(newline="")
    fields = ["observed_at","target_type","target_name","probe_sequence_no","road_name","city","state","latitude","longitude",
              "current_speed_kmh","free_flow_speed_kmh","congestion_index","current_travel_time_seconds","free_flow_travel_time_seconds",
              "delay_seconds","confidence","road_closed","functional_road_class","provider","provider_source_timestamp","collection_run_id"]
    w = csv.DictWriter(out, fieldnames=fields)
    w.writeheader()
    for r in rows:
        t = meta.get(r.get("target_key"), {})
        w.writerow({
            "observed_at": r.get("observed_at"), "target_type": t.get("target_type"), "target_name": t.get("name"),
            "probe_sequence_no": t.get("probe_sequence_no"), "road_name": t.get("road_name"), "city": t.get("city"), "state": t.get("state"),
            "latitude": t.get("latitude"), "longitude": t.get("longitude"),
            "current_speed_kmh": r.get("current_speed_kmh"), "free_flow_speed_kmh": r.get("free_flow_speed_kmh"),
            "congestion_index": r.get("congestion_index"), "current_travel_time_seconds": r.get("current_travel_time_seconds"),
            "free_flow_travel_time_seconds": r.get("free_flow_travel_time_seconds"), "delay_seconds": r.get("delay_seconds"),
            "confidence": r.get("confidence"), "road_closed": r.get("road_closed"), "functional_road_class": r.get("functional_road_class"),
            "provider": r.get("provider"), "provider_source_timestamp": r.get("provider_source_timestamp"), "collection_run_id": r.get("collection_run_id"),
        })
    return f"ITICAS_{safe}_cloud_archive_{days}d.csv", out.getvalue().encode("utf-8-sig")
