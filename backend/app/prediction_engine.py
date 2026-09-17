from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from math import sqrt
from statistics import mean, median
from typing import Any

from sqlalchemy import select

from .analytics import ANALYSIS_TZ, category
from .config import settings
from .prediction_advanced import fit_cyclic_ridge, predict_cyclic_ridge
from .prediction_calibration import latest_context_calibration
from .prediction_monitoring import prediction_verification
from .database import (
    SessionLocal,
    MonitoringLocation,
    PredictionRequest,
    TrafficObservation,
    TrafficPrediction,
)


def _aware_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _db_dt(dt: datetime) -> datetime:
    return _aware_utc(dt).replace(tzinfo=None)


def _clip(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _quantile(values: list[float], q: float) -> float | None:
    vals = sorted(float(v) for v in values if v is not None)
    if not vals:
        return None
    if len(vals) == 1:
        return vals[0]
    pos = (len(vals) - 1) * q
    lo = int(pos)
    hi = min(len(vals) - 1, lo + 1)
    frac = pos - lo
    return vals[lo] * (1 - frac) + vals[hi] * frac


def _linear_slope(points: list[tuple[float, float]]) -> float:
    if len(points) < 3:
        return 0.0
    mx = mean(x for x, _ in points)
    my = mean(y for _, y in points)
    den = sum((x - mx) ** 2 for x, _ in points)
    if den <= 0:
        return 0.0
    return sum((x - mx) * (y - my) for x, y in points) / den


def _load_rows(location_id: int, lookback_days: int) -> tuple[MonitoringLocation | None, list[TrafficObservation]]:
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=max(1, min(int(lookback_days), 3650)))
    with SessionLocal() as db:
        loc = db.get(MonitoringLocation, location_id)
        rows = list(
            db.scalars(
                select(TrafficObservation)
                .where(
                    TrafficObservation.location_id == location_id,
                    TrafficObservation.observed_at >= _db_dt(start),
                    TrafficObservation.observed_at <= _db_dt(now),
                    TrafficObservation.congestion_index.is_not(None),
                )
                .order_by(TrafficObservation.observed_at)
            ).all()
        )
    return loc, rows


def _profiles(rows: list[TrafficObservation]) -> dict[str, Any]:
    hourly_ci: dict[int, list[float]] = defaultdict(list)
    weekday_hour_ci: dict[tuple[int, int], list[float]] = defaultdict(list)
    hourly_free: dict[int, list[float]] = defaultdict(list)
    free_all: list[float] = []
    cis: list[float] = []

    for row in rows:
        ci = row.congestion_index
        if ci is None:
            continue
        dt = _aware_utc(row.observed_at).astimezone(ANALYSIS_TZ)
        cis.append(float(ci))
        hourly_ci[dt.hour].append(float(ci))
        weekday_hour_ci[(dt.weekday(), dt.hour)].append(float(ci))
        if row.free_flow_speed_kmh is not None and row.free_flow_speed_kmh > 0:
            free = float(row.free_flow_speed_kmh)
            hourly_free[dt.hour].append(free)
            free_all.append(free)

    recent = cis[-min(24, len(cis)):] if cis else []
    recent_mean = mean(recent) if recent else (mean(cis) if cis else 0.0)

    # Trend is expressed in CI change per hour using the most recent evidence.
    recent_rows = [r for r in rows[-min(72, len(rows)):] if r.congestion_index is not None]
    if recent_rows:
        t0 = _aware_utc(recent_rows[0].observed_at)
        trend_points = [
            ((_aware_utc(r.observed_at) - t0).total_seconds() / 3600.0, float(r.congestion_index))
            for r in recent_rows
        ]
        trend_per_hour = _linear_slope(trend_points)
    else:
        trend_per_hour = 0.0

    return {
        "hourly_ci": {k: mean(v) for k, v in hourly_ci.items()},
        "weekday_hour_ci": {k: mean(v) for k, v in weekday_hour_ci.items()},
        "hourly_counts": {k: len(v) for k, v in hourly_ci.items()},
        "weekday_hour_counts": {k: len(v) for k, v in weekday_hour_ci.items()},
        "hourly_free": {k: mean(v) for k, v in hourly_free.items()},
        "free_all": mean(free_all) if free_all else None,
        "global_ci": mean(cis) if cis else None,
        "recent_mean": recent_mean,
        "trend_per_hour": trend_per_hour,
        "cyclic_ridge": fit_cyclic_ridge(rows),
    }


def _base_model_values(when_utc: datetime, profiles: dict[str, Any], horizon_hours: float = 0.0) -> dict[str, float]:
    local = _aware_utc(when_utc).astimezone(ANALYSIS_TZ)
    global_ci = profiles.get("global_ci")
    if global_ci is None:
        return {"persistence": 0.0, "clock_hour": 0.0, "weekday_hour": 0.0, "adaptive_hybrid": 0.0, "cyclic_ridge": 0.0}
    recent = profiles.get("recent_mean", global_ci)
    hourly = profiles["hourly_ci"].get(local.hour, global_ci)
    weekly = profiles["weekday_hour_ci"].get((local.weekday(), local.hour), hourly)
    n_weekly = profiles["weekday_hour_counts"].get((local.weekday(), local.hour), 0)
    seasonal = weekly if n_weekly >= 2 else hourly
    seasonal_weight = 0.72 if n_weekly >= 2 else 0.62
    trend = profiles.get("trend_per_hour", 0.0)
    trend_adjustment = _clip(trend * min(max(0.0, horizon_hours), 6.0) * 0.25, -0.10, 0.10)
    adaptive = seasonal_weight * seasonal + (1.0 - seasonal_weight) * recent + trend_adjustment
    ridge_pred = predict_cyclic_ridge(profiles.get("cyclic_ridge"), when_utc)
    return {
        "persistence": _clip(float(recent), 0.0, 1.0),
        "clock_hour": _clip(float(hourly), 0.0, 1.0),
        "weekday_hour": _clip(float(weekly), 0.0, 1.0),
        "adaptive_hybrid": _clip(float(adaptive), 0.0, 1.0),
        "cyclic_ridge": _clip(float(ridge_pred if ridge_pred is not None else adaptive), 0.0, 1.0),
    }


def _model_ci(model: str, when_utc: datetime, profiles: dict[str, Any], horizon_hours: float = 0.0, ensemble_weights: dict[str, float] | None = None) -> float:
    vals = _base_model_values(when_utc, profiles, horizon_hours)
    if model == "validation_weighted_ensemble":
        weights = ensemble_weights or {k: 0.25 for k in vals}
        total = sum(max(0.0, float(weights.get(k, 0.0))) for k in vals) or 1.0
        pred = sum(vals[k] * max(0.0, float(weights.get(k, 0.0))) for k in vals) / total
        return _clip(float(pred), 0.0, 1.0)
    return vals.get(model, vals["adaptive_hybrid"])


def _score_models(train: list[TrafficObservation], test: list[TrafficObservation]) -> list[dict[str, Any]]:
    profiles = _profiles(train)
    models = ["persistence", "clock_hour", "weekday_hour", "adaptive_hybrid", "cyclic_ridge"]
    scores: list[dict[str, Any]] = []
    for model in models:
        ci_errors: list[float] = []
        speed_errors: list[float] = []
        signed_residuals: list[float] = []
        for row in test:
            if row.congestion_index is None:
                continue
            pred_ci = _model_ci(model, _aware_utc(row.observed_at), profiles)
            actual_ci = float(row.congestion_index)
            err = pred_ci - actual_ci
            ci_errors.append(abs(err)); signed_residuals.append(err)
            if row.current_speed_kmh is not None:
                local = _aware_utc(row.observed_at).astimezone(ANALYSIS_TZ)
                free = profiles["hourly_free"].get(local.hour) or profiles.get("free_all") or row.free_flow_speed_kmh
                if free:
                    pred_speed = max(0.0, float(free) * (1.0 - pred_ci))
                    speed_errors.append(abs(pred_speed - float(row.current_speed_kmh)))
        if ci_errors:
            scores.append({
                "model": model,
                "ci_mae": round(mean(ci_errors), 4),
                "ci_rmse": round(sqrt(mean(e * e for e in signed_residuals)), 4),
                "speed_mae_kmh": round(mean(speed_errors), 2) if speed_errors else None,
                "residual_q90": round(_quantile(ci_errors, 0.90) or 0.0, 4),
                "validation_points": len(ci_errors),
            })
    return scores


def _ensemble_weights(train: list[TrafficObservation]) -> dict[str, float]:
    base_models = ["persistence", "clock_hour", "weekday_hour", "adaptive_hybrid", "cyclic_ridge"]
    if len(train) < 36:
        return {m: 1.0/len(base_models) for m in base_models}
    split = max(24, int(len(train) * 0.75))
    if split >= len(train):
        return {m: 1.0/len(base_models) for m in base_models}
    scores = _score_models(train[:split], train[split:])
    by = {x["model"]: max(float(x.get("ci_mae") or 0.0), 0.005) for x in scores}
    raw = {m: 1.0 / by.get(m, 0.10) for m in base_models}
    total = sum(raw.values()) or 1.0
    return {m: raw[m] / total for m in base_models}

def _backtest(rows: list[TrafficObservation]) -> dict[str, Any]:
    if len(rows) < 24:
        return {
            "validation_points": 0, "models": [], "selected_model": None,
            "ci_mae": None, "ci_rmse": None, "speed_mae_kmh": None,
            "residual_q90": None, "ensemble_weights": {},
        }
    split = max(12, int(len(rows) * 0.8))
    if split >= len(rows): split = len(rows) - 1
    train, test = rows[:split], rows[split:]
    profiles = _profiles(train)
    scores = _score_models(train, test)
    weights = _ensemble_weights(train)

    ci_errors: list[float] = []; speed_errors: list[float] = []; signed: list[float] = []
    for row in test:
        if row.congestion_index is None: continue
        pred_ci = _model_ci("validation_weighted_ensemble", _aware_utc(row.observed_at), profiles, ensemble_weights=weights)
        actual_ci = float(row.congestion_index); err = pred_ci - actual_ci
        ci_errors.append(abs(err)); signed.append(err)
        if row.current_speed_kmh is not None:
            local = _aware_utc(row.observed_at).astimezone(ANALYSIS_TZ)
            free = profiles["hourly_free"].get(local.hour) or profiles.get("free_all") or row.free_flow_speed_kmh
            if free: speed_errors.append(abs(max(0.0, float(free)*(1.0-pred_ci)) - float(row.current_speed_kmh)))
    if ci_errors:
        scores.append({
            "model": "validation_weighted_ensemble",
            "ci_mae": round(mean(ci_errors), 4),
            "ci_rmse": round(sqrt(mean(e*e for e in signed)), 4),
            "speed_mae_kmh": round(mean(speed_errors), 2) if speed_errors else None,
            "residual_q90": round(_quantile(ci_errors, 0.90) or 0.0, 4),
            "validation_points": len(ci_errors),
        })
    scores.sort(key=lambda x: (x["ci_mae"], x["ci_rmse"]))
    best = scores[0] if scores else None
    return {
        "validation_points": best["validation_points"] if best else 0,
        "models": scores,
        "selected_model": best["model"] if best else None,
        "ci_mae": best["ci_mae"] if best else None,
        "ci_rmse": best["ci_rmse"] if best else None,
        "speed_mae_kmh": best["speed_mae_kmh"] if best else None,
        "residual_q90": best["residual_q90"] if best else None,
        "ensemble_weights": {k: round(v, 4) for k,v in weights.items()},
        "selection_rule": "lowest holdout congestion-index MAE; ensemble weights are learned on an inner validation split to avoid using final holdout errors as weights",
    }

def _readiness(rows: list[TrafficObservation], validation: dict[str, Any]) -> dict[str, Any]:
    if not rows:
        return {"status": "insufficient", "grade": "D", "reason": "No stored observations are available."}
    span_hours = (_aware_utc(rows[-1].observed_at) - _aware_utc(rows[0].observed_at)).total_seconds() / 3600 if len(rows) > 1 else 0.0
    n = len(rows)
    val_n = validation.get("validation_points", 0)
    if n >= 288 and span_hours >= 48 and val_n >= 24:
        return {"status": "research_ready", "grade": "A", "reason": "Strong sample count, multi-day span and holdout validation are available."}
    if n >= 96 and span_hours >= 18 and val_n >= 12:
        return {"status": "operational", "grade": "B", "reason": "Enough history for operational forecasting, but longer seasonal coverage will improve robustness."}
    if n >= 36 and span_hours >= 6:
        return {"status": "limited", "grade": "C", "reason": "Forecasting is available with elevated uncertainty because historical coverage is still limited."}
    return {"status": "insufficient", "grade": "D", "reason": "More autonomous archive history is required before a defensible forecast can be issued."}



def _forecast_explainability(selected: str, when_utc: datetime, profiles: dict[str, Any], horizon_hours: float, weights: dict[str, float]) -> dict[str, Any]:
    vals = _base_model_values(when_utc, profiles, horizon_hours)
    local = _aware_utc(when_utc).astimezone(ANALYSIS_TZ)
    global_ci = float(profiles.get("global_ci") or 0.0)
    recent = float(profiles.get("recent_mean") or global_ci)
    hourly = float(profiles["hourly_ci"].get(local.hour, global_ci))
    weekly = float(profiles["weekday_hour_ci"].get((local.weekday(), local.hour), hourly))
    trend = float(profiles.get("trend_per_hour") or 0.0)
    out = {
        "selected_model": selected,
        "recent_state_ci": round(recent, 4),
        "clock_hour_ci": round(hourly, 4),
        "weekday_hour_ci": round(weekly, 4),
        "trend_ci_per_hour": round(trend, 6),
        "base_model_predictions": {k: round(v, 4) for k,v in vals.items()},
    }
    ridge = profiles.get("cyclic_ridge") or {}
    if ridge.get("coefficients"):
        out["cyclic_ridge_coefficients"] = {k: round(float(v), 6) for k,v in ridge["coefficients"].items()}
    if selected == "validation_weighted_ensemble":
        out["ensemble_weights"] = {k: round(float(weights.get(k, 0.0)), 4) for k in vals}
        out["interpretation"] = "The ensemble combines transparent temporal candidates using inner-validation inverse-error weights. Final selection is still judged on an untouched holdout segment."
    elif selected == "cyclic_ridge":
        out["interpretation"] = "The cyclic ridge model is a regularized linear machine-learning candidate using interpretable clock-hour and weekday cycles. It is selected only if it beats the transparent baselines on held-out observations."
    elif selected == "adaptive_hybrid":
        out["interpretation"] = "The adaptive hybrid blends supported weekday/hour or clock-hour recurrence with the recent state and a capped short-horizon trend."
    else:
        out["interpretation"] = "The selected transparent temporal baseline performed best on the held-out road observations."
    return out


def _decision_intelligence(points: list[dict[str, Any]], validation: dict[str, Any], readiness: dict[str, Any]) -> dict[str, Any]:
    if not points:
        return {"status": "unavailable", "signals": []}
    cis = [float(p.get("predicted_congestion_index") or 0.0) for p in points]
    speeds = [float(p["predicted_speed_kmh"]) for p in points if p.get("predicted_speed_kmh") is not None]
    peak = max(points, key=lambda p: float(p.get("predicted_congestion_index") or 0.0))
    mean_ci = mean(cis)
    moderate_share = 100.0 * sum(v >= 0.25 for v in cis) / len(cis)
    heavy_share = 100.0 * sum(v >= 0.45 for v in cis) / len(cis)
    severe_share = 100.0 * sum(v >= 0.65 for v in cis) / len(cis)
    widths = [max(0.0, float(p.get("ci_upper_90") or 0.0) - float(p.get("ci_lower_90") or 0.0)) for p in points]
    signals: list[str] = []
    peak_ci = float(peak.get("predicted_congestion_index") or 0.0)
    if peak_ci >= 0.65:
        signals.append("Severe congestion is forecast in the peak window; prioritize active traffic control, incident readiness and traveller information.")
    elif peak_ci >= 0.45:
        signals.append("Heavy congestion is forecast in the peak window; prioritize junction control, enforcement and route management.")
    elif peak_ci >= 0.25:
        signals.append("Moderate congestion is forecast; maintain targeted surveillance and prepare operational measures around the peak window.")
    else:
        signals.append("Forecast conditions are predominantly free/light; maintain monitoring and use the period as a baseline for deterioration detection.")
    if moderate_share >= 25:
        signals.append("A material share of the forecast is moderate-or-worse, so peak-window management is more appropriate than all-day averages alone.")
    if validation.get("ci_mae") is not None:
        signals.append(f"Use the forecast alongside holdout CI MAE {float(validation['ci_mae']):.4f} and the 90% uncertainty envelope.")
    signals.append("Re-run the forecast when incidents, road works, major events or weather conditions materially change.")
    top = sorted(points, key=lambda p: float(p.get("predicted_congestion_index") or 0.0), reverse=True)[:5]
    return {
        "status": "available",
        "mean_predicted_ci": round(mean_ci, 4),
        "peak_predicted_ci": round(peak_ci, 4),
        "peak_time_wat": peak.get("predicted_for_wat"),
        "minimum_predicted_speed_kmh": round(min(speeds), 2) if speeds else None,
        "moderate_or_worse_share_pct": round(moderate_share, 2),
        "heavy_or_worse_share_pct": round(heavy_share, 2),
        "severe_share_pct": round(severe_share, 2),
        "mean_uncertainty_width_ci": round(mean(widths), 4) if widths else None,
        "evidence_grade": readiness.get("grade"),
        "top_peak_windows": top,
        "signals": signals,
    }

def forecast_location(
    location_id: int,
    forecast_start: datetime,
    forecast_end: datetime,
    step_minutes: int = 15,
    lookback_days: int = 30,
    external_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    start = _aware_utc(forecast_start)
    end = _aware_utc(forecast_end)
    if end <= start:
        raise ValueError("Forecast end must be later than forecast start.")
    horizon_minutes = int((end - start).total_seconds() / 60)
    if horizon_minutes < settings.prediction_min_horizon_minutes:
        raise ValueError(f"Forecast horizon must be at least {settings.prediction_min_horizon_minutes} minutes.")
    if horizon_minutes > settings.prediction_max_horizon_minutes:
        raise ValueError(f"Forecast horizon cannot exceed {settings.prediction_max_horizon_minutes} minutes.")
    step_minutes = int(step_minutes)
    if step_minutes not in {5, 10, 15, 30, 60}:
        raise ValueError("Forecast resolution must be 5, 10, 15, 30 or 60 minutes.")

    loc, rows = _load_rows(location_id, lookback_days)
    if not loc:
        raise LookupError("Monitoring location not found.")

    validation = _backtest(rows)
    readiness = _readiness(rows, validation)
    if readiness["status"] == "insufficient":
        return {
            "status": "insufficient_history",
            "location": {"id": loc.id, "name": loc.name, "road_name": loc.road_name, "city": loc.city, "state": loc.state},
            "readiness": readiness,
            "training": {"observations": len(rows)},
            "validation": validation,
            "forecast": [],
            "limitations": [readiness["reason"], "ITICAS does not fabricate future values when historical evidence is inadequate."],
        }

    profiles = _profiles(rows)
    selected = validation.get("selected_model") or "adaptive_hybrid"
    ensemble_weights = validation.get("ensemble_weights") or _ensemble_weights(rows)
    residual_q90 = validation.get("residual_q90")
    # A minimum interval width prevents false precision when residual history is unusually uniform.
    interval_half = max(0.04, float(residual_q90 or 0.08))

    calibration = latest_context_calibration(location_id)
    rain_cal = calibration.get("rain") or {}
    incident_cal = calibration.get("incident") or {}
    points: list[dict[str, Any]] = []
    cursor = start
    while cursor <= end:
        horizon_h = (cursor - start).total_seconds() / 3600.0
        pred_ci = _model_ci(selected, cursor, profiles, horizon_h, ensemble_weights=ensemble_weights)
        local = cursor.astimezone(ANALYSIS_TZ)
        free = profiles["hourly_free"].get(local.hour) or profiles.get("free_all")
        speed = max(0.0, float(free) * (1.0 - pred_ci)) if free else None
        lo = _clip(pred_ci - interval_half, 0.0, 1.0)
        hi = _clip(pred_ci + interval_half, 0.0, 1.0)
        points.append({
            "predicted_for": cursor.isoformat(),
            "predicted_for_wat": local.isoformat(),
            "predicted_speed_kmh": round(speed, 2) if speed is not None else None,
            "predicted_free_flow_speed_kmh": round(float(free), 2) if free is not None else None,
            "baseline_predicted_congestion_index": round(pred_ci, 4),
            "context_adjustment_ci": 0.0,
            "predicted_congestion_index": round(pred_ci, 4),
            "predicted_category": category(pred_ci),
            "context_flags": [],
            "ci_lower_90": round(lo, 4),
            "ci_upper_90": round(hi, 4),
        })
        cursor += timedelta(minutes=step_minutes)

    context = external_context or {"status": "not_requested"}
    weather_rows = ((context.get("weather") or {}).get("hourly") or []) if isinstance(context, dict) else []
    weather_by_hour = {}
    for wr in weather_rows:
        try:
            wdt = datetime.fromisoformat(str(wr.get("time_utc")).replace("Z", "+00:00")).astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
            weather_by_hour[wdt] = wr
        except Exception:
            continue
    incident_count = int(((context.get("incidents") or {}).get("active_count") or 0)) if isinstance(context, dict) else 0
    probe_share = ((context.get("corridor_probes") or {}).get("moderate_or_worse_probe_share_pct")) if isinstance(context, dict) else None
    for p in points:
        flags=[]
        try:
            pdt=datetime.fromisoformat(p["predicted_for"]).astimezone(timezone.utc); wh=pdt.replace(minute=0,second=0,microsecond=0); wr=weather_by_hour.get(wh)
        except Exception:
            wr=None
        if wr:
            p["weather_context"] = {"precipitation_mm": wr.get("precipitation_mm"), "temperature_c": wr.get("temperature_c"), "weather_code": wr.get("weather_code"), "condition": wr.get("condition"), "wind_speed_kmh": wr.get("wind_speed_kmh")}
            if float(wr.get("precipitation_mm") or 0) >= 5.0: flags.append("heavy_rain_forecast")
            elif float(wr.get("precipitation_mm") or 0) > 0: flags.append("rain_forecast")
        incident_active = incident_count > 0 and (datetime.fromisoformat(p["predicted_for"]) - start).total_seconds() <= 2*3600
        if incident_active: flags.append("current_incident_context")
        if probe_share is not None and float(probe_share) >= 25: flags.append("corridor_probe_congestion_context")
        local=datetime.fromisoformat(p["predicted_for"]).astimezone(ANALYSIS_TZ)
        if local.weekday() >= 5: flags.append("weekend")
        adjustment = 0.0
        if wr and float(wr.get("precipitation_mm") or 0) > 0 and rain_cal.get("validated"):
            adjustment += float(rain_cal.get("ci_adjustment") or 0.0); flags.append("validated_rain_effect_applied")
        if incident_active and incident_cal.get("validated"):
            adjustment += float(incident_cal.get("ci_adjustment") or 0.0); flags.append("validated_incident_effect_applied")
        adjustment = _clip(adjustment, -0.20, 0.20)
        if adjustment:
            base=float(p["baseline_predicted_congestion_index"]); calibrated=_clip(base+adjustment,0.0,1.0)
            p["context_adjustment_ci"] = round(adjustment,4); p["predicted_congestion_index"] = round(calibrated,4)
            free=p.get("predicted_free_flow_speed_kmh")
            p["predicted_speed_kmh"] = round(max(0.0,float(free)*(1.0-calibrated)),2) if free is not None else p.get("predicted_speed_kmh")
            half=max(calibrated-float(p["ci_lower_90"]), float(p["ci_upper_90"])-calibrated, interval_half)
            p["ci_lower_90"] = round(_clip(calibrated-half,0.0,1.0),4); p["ci_upper_90"] = round(_clip(calibrated+half,0.0,1.0),4)
            p["predicted_category"] = category(calibrated)
        p["context_flags"] = flags
        active_records=((context.get("incidents") or {}).get("active_records") or []) if isinstance(context,dict) else []
        if incident_active and active_records:
            rec=active_records[0]; desc=(rec.get("description") or "").strip(); typ=rec.get("incident_type") or "traffic incident"
            p["cause_assessment"]={"status":"provider_evidence","cause":f"{typ}: {desc}" if desc else str(typ),"confidence":"reported","source":rec.get("provider") or "TomTom incident archive"}
        elif wr and float(wr.get("precipitation_mm") or 0)>0 and rain_cal.get("validated"):
            p["cause_assessment"]={"status":"validated_weather_effect","cause":"Rainfall has a road-specific validated association with congestion for this monitored road.","confidence":"empirically_validated","source":"ITICAS paired historical traffic-weather calibration"}
        elif float(p.get("predicted_congestion_index") or 0)>=0.35:
            p["cause_assessment"]={"status":"not_established","cause":"Congestion is forecast from the road's historical temporal pattern, but no specific breakdown/crash/roadwork cause is established by current evidence.","confidence":"unknown","source":"ITICAS traffic history"}
        else:
            p["cause_assessment"]={"status":"none_identified","cause":"No specific congestion-causing event is identified for this forecast interval.","confidence":"unknown","source":"ITICAS context checks"}

    # Forecast is first summarized per Nigeria-local calendar day, then as a composite horizon.
    daily_groups=defaultdict(list)
    for p in points:
        local=datetime.fromisoformat(p["predicted_for"]).astimezone(ANALYSIS_TZ)
        daily_groups[local.date().isoformat()].append(p)
    daily_forecast=[]
    for ds,rr in sorted(daily_groups.items()):
        cis=[float(x.get("predicted_congestion_index") or 0.0) for x in rr]
        speeds=[float(x["predicted_speed_kmh"]) for x in rr if x.get("predicted_speed_kmh") is not None]
        peak=max(rr,key=lambda x:float(x.get("predicted_congestion_index") or 0.0)) if rr else None
        rainy=[x for x in rr if float(((x.get("weather_context") or {}).get("precipitation_mm") or 0.0))>0]
        weather_conditions=[]
        for x in rr:
            c=(x.get("weather_context") or {}).get("condition")
            if c and c not in weather_conditions: weather_conditions.append(c)
        causes=[]
        for x in rr:
            c=(x.get("cause_assessment") or {}).get("cause")
            if c and c not in causes: causes.append(c)
        daily_forecast.append({
            "date":ds,"interval_minutes":step_minutes,"forecast_points":len(rr),
            "mean_congestion_index":round(mean(cis),4) if cis else None,
            "max_congestion_index":round(max(cis),4) if cis else None,
            "mean_speed_kmh":round(mean(speeds),2) if speeds else None,
            "peak_time":peak.get("predicted_for") if peak else None,
            "peak_category":peak.get("predicted_category") if peak else None,
            "rain_forecast_intervals":len(rainy),
            "weather_conditions":weather_conditions,
            "weather_traffic_interpretation":("Rain is forecast and its validated road-specific traffic effect is applied where the calibration gate passed." if rainy and rain_cal.get("validated") else ("Rain is forecast, but its traffic effect remains advisory because road-specific validation has not passed." if rainy else "No rain is forecast in the available weather intervals for this day.")),
            "cause_assessments":causes[:5],
            "intervals":rr,
        })

    explainability = _forecast_explainability(selected, start, profiles, 0.0, ensemble_weights)
    explainability["context_calibration"] = {"rain": rain_cal, "incident": incident_cal}

    with SessionLocal() as db:
        req = PredictionRequest(
            location_id=location_id,
            requested_at=datetime.now(timezone.utc),
            forecast_start_at=_db_dt(start),
            forecast_end_at=_db_dt(end),
            horizon_minutes=horizon_minutes,
            status="completed",
            model_name=selected,
            validation_status=f"{readiness['grade']}:{readiness['status']}",
            limitations=" | ".join([
                "Forecast is evidence-based and uncertainty-bounded; it is not a guarantee of future traffic.",
                "External weather, incident and corridor context is preserved separately from the validated traffic-history forecast unless a road-specific context effect is empirically calibrated.",
            ]),
        )
        db.add(req)
        db.flush()
        for p in points:
            db.add(TrafficPrediction(
                prediction_request_id=req.id,
                location_id=location_id,
                predicted_for=_db_dt(datetime.fromisoformat(p["predicted_for"])),
                predicted_speed_kmh=p["predicted_speed_kmh"],
                predicted_congestion_index=p["predicted_congestion_index"],
                predicted_category=p["predicted_category"],
                lower_bound=p["ci_lower_90"],
                upper_bound=p["ci_upper_90"],
            ))
        db.commit()
        request_id = req.id

    first_obs = _aware_utc(rows[0].observed_at) if rows else None
    last_obs = _aware_utc(rows[-1].observed_at) if rows else None
    peak = max(points, key=lambda p: p["predicted_congestion_index"]) if points else None
    decision = _decision_intelligence(points, validation, readiness)
    return {
        "status": "completed",
        "request_id": request_id,
        "location": {"id": loc.id, "name": loc.name, "road_name": loc.road_name, "city": loc.city, "state": loc.state},
        "period": {
            "forecast_start_utc": start.isoformat(),
            "forecast_end_utc": end.isoformat(),
            "horizon_minutes": horizon_minutes,
            "step_minutes": step_minutes,
            "lookback_days": lookback_days,
        },
        "training": {
            "observations": len(rows),
            "first_observation": first_obs.isoformat() if first_obs else None,
            "last_observation": last_obs.isoformat() if last_obs else None,
        },
        "readiness": readiness,
        "model": {
            "selected": selected,
            "method": "automatic holdout-selected temporal/ML forecast with evidence-gated context calibration",
            "candidates": ["persistence", "clock_hour", "weekday_hour", "adaptive_hybrid", "cyclic_ridge", "validation_weighted_ensemble"],
            "ensemble_weights": {k: round(float(v), 4) for k, v in ensemble_weights.items()},
            "explanation": "ITICAS compares transparent temporal models, an interpretable cyclic-ridge ML candidate and a validation-weighted ensemble on held-out stored observations. Validated road-specific rain/incident effects may adjust the final forecast; unvalidated context remains advisory.",
            "explainability": explainability,
        },
        "validation": validation,
        "uncertainty": {
            "interval": "approximately 90% empirical residual envelope",
            "ci_half_width": round(interval_half, 4),
        },
        "peak_forecast": peak,
        "decision_intelligence": decision,
        "external_context": context,
        "context_calibration": calibration,
        "post_forecast_monitoring": prediction_verification(location_id),
        "scenario_comparison": {
            "baseline_mean_ci": round(mean(float(p.get("baseline_predicted_congestion_index") or 0.0) for p in points),4) if points else None,
            "context_calibrated_mean_ci": round(mean(float(p.get("predicted_congestion_index") or 0.0) for p in points),4) if points else None,
            "validated_rain_effect_ci": rain_cal.get("ci_adjustment") if rain_cal.get("validated") else None,
            "validated_incident_effect_ci": incident_cal.get("ci_adjustment") if incident_cal.get("validated") else None,
            "rule": "Scenario/context deltas are applied only when the selected road passes the empirical holdout calibration gate."
        },
        "daily_forecast": daily_forecast,
        "forecast": points,
        "limitations": [
            "Forecasts are based on the traffic history currently stored for this monitored road.",
            "Weather and incident effects alter the forecast only when road-specific paired historical evidence passes the holdout calibration gate; otherwise they remain advisory context.",
            "The cyclic-ridge machine-learning candidate is used only if its held-out error beats the simpler baselines.",
            "Prediction uncertainty should be considered alongside archive coverage and backtest error.",
        ],
    }


def prediction_history(limit: int = 30) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 200))
    with SessionLocal() as db:
        rows = list(db.scalars(select(PredictionRequest).order_by(PredictionRequest.id.desc()).limit(limit)).all())
        loc_ids = {r.location_id for r in rows}
        locs = {x.id: x for x in db.scalars(select(MonitoringLocation).where(MonitoringLocation.id.in_(loc_ids))).all()} if loc_ids else {}
    out = []
    for r in rows:
        loc = locs.get(r.location_id)
        out.append({
            "id": r.id,
            "location_id": r.location_id,
            "location_name": loc.name if loc else f"Location {r.location_id}",
            "requested_at": _aware_utc(r.requested_at).isoformat(),
            "forecast_start_at": _aware_utc(r.forecast_start_at).isoformat(),
            "forecast_end_at": _aware_utc(r.forecast_end_at).isoformat(),
            "horizon_minutes": r.horizon_minutes,
            "status": r.status,
            "model_name": r.model_name,
            "validation_status": r.validation_status,
        })
    return out
