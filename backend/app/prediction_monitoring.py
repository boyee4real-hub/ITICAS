from __future__ import annotations

from bisect import bisect_left
from datetime import datetime, timedelta, timezone
from statistics import mean
from typing import Any

from sqlalchemy import select

from .database import SessionLocal, TrafficObservation, TrafficPrediction


def _aware(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def prediction_verification(location_id: int, limit: int = 1000, tolerance_minutes: int = 10) -> dict[str, Any]:
    limit = max(20, min(int(limit), 5000))
    with SessionLocal() as db:
        preds = list(db.scalars(
            select(TrafficPrediction).where(TrafficPrediction.location_id == location_id)
            .order_by(TrafficPrediction.predicted_for.desc()).limit(limit)
        ).all())
        if not preds:
            return {'status':'no_predictions','matched_points':0,'drift_status':'not_available','reason':'No stored prediction points are available yet.'}
        lo = min(_aware(p.predicted_for) for p in preds) - timedelta(minutes=tolerance_minutes)
        hi = max(_aware(p.predicted_for) for p in preds) + timedelta(minutes=tolerance_minutes)
        obs = list(db.scalars(
            select(TrafficObservation).where(
                TrafficObservation.location_id == location_id,
                TrafficObservation.observed_at >= lo.replace(tzinfo=None),
                TrafficObservation.observed_at <= hi.replace(tzinfo=None),
                TrafficObservation.congestion_index.is_not(None),
            ).order_by(TrafficObservation.observed_at)
        ).all())
    times = [_aware(o.observed_at) for o in obs]
    matched=[]
    tol = timedelta(minutes=tolerance_minutes)
    for p in sorted(preds, key=lambda x:_aware(x.predicted_for)):
        t=_aware(p.predicted_for); i=bisect_left(times,t); candidates=[]
        if i < len(obs): candidates.append(obs[i])
        if i > 0: candidates.append(obs[i-1])
        if not candidates: continue
        o=min(candidates,key=lambda x:abs(_aware(x.observed_at)-t))
        delta=abs(_aware(o.observed_at)-t)
        if delta > tol or p.predicted_congestion_index is None or o.congestion_index is None: continue
        matched.append({
            'predicted_for':t.isoformat(),'observed_at':_aware(o.observed_at).isoformat(),
            'predicted_ci':float(p.predicted_congestion_index),'observed_ci':float(o.congestion_index),
            'abs_error':abs(float(p.predicted_congestion_index)-float(o.congestion_index)),
            'predicted_speed_kmh':p.predicted_speed_kmh,'observed_speed_kmh':o.current_speed_kmh,
            'minutes_offset':round(delta.total_seconds()/60.0,2),
        })
    if not matched:
        return {'status':'awaiting_actuals','matched_points':0,'drift_status':'not_available','reason':'Predictions exist, but matching observed traffic has not accumulated yet.'}
    errors=[x['abs_error'] for x in matched]
    speed_errors=[abs(float(x['predicted_speed_kmh'])-float(x['observed_speed_kmh'])) for x in matched if x['predicted_speed_kmh'] is not None and x['observed_speed_kmh'] is not None]
    cut=max(5,len(errors)//2)
    recent=errors[-cut:]
    prior=errors[:-cut]
    recent_mae=mean(recent)
    prior_mae=mean(prior) if prior else None
    if prior_mae is None or len(errors)<20:
        drift='insufficient_history'
    elif recent_mae > max(prior_mae*1.5, prior_mae+0.03):
        drift='warning'
    else:
        drift='stable'
    return {
        'status':'available','matched_points':len(matched),'ci_mae':round(mean(errors),4),
        'speed_mae_kmh':round(mean(speed_errors),2) if speed_errors else None,
        'recent_ci_mae':round(recent_mae,4),'prior_ci_mae':round(prior_mae,4) if prior_mae is not None else None,
        'drift_status':drift,'tolerance_minutes':tolerance_minutes,'recent_matches':matched[-20:],
        'interpretation':'Realized forecast accuracy is calculated only where a stored prediction can be matched to a subsequently observed ITICAS traffic record. Drift is flagged when recent CI MAE materially deteriorates relative to earlier matched predictions.'
    }
