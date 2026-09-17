from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from .analytics import ANALYSIS_TZ
from .database import SessionLocal, MonitoringLocation, TrafficIncident, CorridorProbe, CorridorProbeObservation
from .weather_service import hourly_weather_forecast, WeatherUnavailable
from .config import settings


def _aware_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _db_dt(dt: datetime) -> datetime:
    return _aware_utc(dt).replace(tzinfo=None)


def _day_type_summary(start: datetime, end: datetime) -> dict[str, Any]:
    start_local = _aware_utc(start).astimezone(ANALYSIS_TZ)
    end_local = _aware_utc(end).astimezone(ANALYSIS_TZ)
    cursor = start_local.replace(hour=0, minute=0, second=0, microsecond=0)
    days: list[dict[str, Any]] = []
    while cursor.date() <= end_local.date():
        days.append({
            "date": cursor.date().isoformat(),
            "weekday": cursor.strftime("%A"),
            "is_weekend": cursor.weekday() >= 5,
        })
        cursor += timedelta(days=1)
    return {
        "days": days,
        "weekday_days": sum(not x["is_weekend"] for x in days),
        "weekend_days": sum(x["is_weekend"] for x in days),
        "note": "Weekend/weekday context is deterministic. ITICAS does not label a date as a Nigerian public holiday unless an operator-supplied holiday/event scenario is provided.",
    }


def _incident_context(location_id: int) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)
    with SessionLocal() as db:
        rows = list(db.scalars(
            select(TrafficIncident).where(
                TrafficIncident.location_id == location_id,
                ((TrafficIncident.ended_at.is_(None)) | (TrafficIncident.ended_at >= _db_dt(cutoff))),
            ).order_by(TrafficIncident.source_timestamp.desc())
        ).all())
    active = []
    for r in rows:
        ended = _aware_utc(r.ended_at) if r.ended_at else None
        if ended is None or ended >= now:
            active.append(r)
    max_delay = max([float(r.delay_seconds or 0) for r in active] + [0.0])
    active_records=[{
        "incident_type":r.incident_type,"description":r.description,"severity":r.severity,
        "delay_seconds":r.delay_seconds,"road_from":r.road_from,"road_to":r.road_to,
        "started_at":_aware_utc(r.started_at).isoformat() if r.started_at else None,
        "ended_at":_aware_utc(r.ended_at).isoformat() if r.ended_at else None,
        "provider":r.provider,
    } for r in active]
    return {
        "active_count": len(active),
        "recent_24h_count": len(rows),
        "maximum_reported_delay_seconds": round(max_delay, 1),
        "types": sorted({str(r.incident_type) for r in active if r.incident_type}),
        "active_records":active_records,
        "provider": "TomTom Incident Details / stored ITICAS incident archive",
        "interpretation": "Incident context is a current operational warning. A cause is reported only when the provider supplies incident evidence; otherwise ITICAS states that the cause is not established.",
    }


def _probe_context(location_id: int) -> dict[str, Any]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=6)
    with SessionLocal() as db:
        probes = list(db.scalars(select(CorridorProbe).where(CorridorProbe.location_id == location_id)).all())
        ids = [p.id for p in probes]
        obs = list(db.scalars(
            select(CorridorProbeObservation).where(
                CorridorProbeObservation.location_id == location_id,
                CorridorProbeObservation.observed_at >= _db_dt(cutoff),
                CorridorProbeObservation.provider_status == "ok",
            ).order_by(CorridorProbeObservation.observed_at.desc())
        ).all()) if ids else []
    by_probe: dict[int, list[float]] = defaultdict(list)
    for r in obs:
        if r.congestion_index is not None:
            by_probe[int(r.probe_id)].append(float(r.congestion_index))
    probe_means = {pid: sum(vals)/len(vals) for pid, vals in by_probe.items() if vals}
    vals = list(probe_means.values())
    hotspot_share = (100.0 * sum(v >= 0.25 for v in vals) / len(vals)) if vals else None
    return {
        "configured_probes": len(probes),
        "probes_with_recent_data": len(probe_means),
        "recent_probe_observations": len(obs),
        "mean_recent_probe_ci": round(sum(vals)/len(vals), 4) if vals else None,
        "moderate_or_worse_probe_share_pct": round(hotspot_share, 2) if hotspot_share is not None else None,
        "interpretation": "Probe context describes current spatial heterogeneity along the monitored corridor. It does not fabricate future hotspot positions.",
    }


async def collect_prediction_context(location_id: int, forecast_start: datetime, forecast_end: datetime) -> dict[str, Any]:
    with SessionLocal() as db:
        loc = db.get(MonitoringLocation, location_id)
    if not loc:
        raise LookupError("Monitoring location not found.")

    weather: dict[str, Any]
    if loc.latitude is None or loc.longitude is None:
        weather = {"status": "unavailable", "reason": "Monitoring location has no coordinates.", "hourly": []}
    else:
        try:
            weather = await asyncio.wait_for(hourly_weather_forecast(float(loc.latitude), float(loc.longitude), forecast_start, forecast_end), timeout=max(5.0, float(settings.weather_timeout_seconds)))
        except WeatherUnavailable as exc:
            weather = {"status": "unavailable", "reason": str(exc), "diagnostic": exc.as_dict(), "hourly": []}
        except Exception as exc:
            weather = {"status": "unavailable", "reason": f"Weather context could not be retrieved: {exc}", "hourly": []}

    incident = _incident_context(location_id)
    probes = _probe_context(location_id)
    day_type = _day_type_summary(forecast_start, forecast_end)

    rain_hours = [r for r in weather.get("hourly", []) if float(r.get("precipitation_mm") or 0) > 0]
    heavy_rain_hours = [r for r in weather.get("hourly", []) if float(r.get("precipitation_mm") or 0) >= 5.0]
    max_rain = max([float(r.get("precipitation_mm") or 0) for r in weather.get("hourly", [])] + [0.0])
    return {
        "status": "available",
        "weather": weather,
        "weather_summary": {
            "forecast_hours": len(weather.get("hourly", [])),
            "rain_hours": len(rain_hours),
            "heavy_rain_hours": len(heavy_rain_hours),
            "maximum_hourly_precipitation_mm": round(max_rain, 2),
            "provider": weather.get("provider"),
            "calibration_status": "advisory_only",
            "note": "Weather is shown as forecast context. Until a road has enough paired historical traffic-weather observations, ITICAS does not alter the traffic forecast mean with an unvalidated rainfall coefficient.",
        },
        "incidents": incident,
        "corridor_probes": probes,
        "day_type": day_type,
        "scientific_rule": "External context is separated from the validated traffic-history forecast unless a context effect has been empirically calibrated and validated for the selected road.",
    }
