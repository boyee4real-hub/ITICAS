from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from statistics import mean
from typing import Any

from sqlalchemy import select

from .analytics import ANALYSIS_TZ
from .database import SessionLocal, MonitoringLocation, TrafficObservation, TrafficIncident, PredictionContextCalibration
from .weather_service import hourly_weather_history, WeatherUnavailable


def _aware(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _db(dt: datetime) -> datetime:
    return _aware(dt).replace(tzinfo=None)


def _mae(values: list[float]) -> float | None:
    return mean(values) if values else None


def _hourly_traffic(rows: list[TrafficObservation]) -> list[dict[str, Any]]:
    grouped=defaultdict(list)
    for r in rows:
        if r.congestion_index is None: continue
        h=_aware(r.observed_at).replace(minute=0,second=0,microsecond=0)
        grouped[h].append(float(r.congestion_index))
    return [{'time_utc':k,'ci':mean(v)} for k,v in sorted(grouped.items())]


def _clock_baseline(train: list[dict[str,Any]]) -> tuple[dict[int,float],float]:
    by=defaultdict(list); vals=[]
    for r in train:
        local=r['time_utc'].astimezone(ANALYSIS_TZ); by[local.hour].append(float(r['ci'])); vals.append(float(r['ci']))
    g=mean(vals) if vals else 0.0
    return {h:mean(v) for h,v in by.items()},g


def _predict_base(row:dict[str,Any], profile:dict[int,float], global_ci:float)->float:
    return float(profile.get(row['time_utc'].astimezone(ANALYSIS_TZ).hour,global_ci))


def _incident_active(incidents:list[TrafficIncident], t:datetime)->bool:
    for x in incidents:
        if not x.started_at: continue
        s=_aware(x.started_at); e=_aware(x.ended_at) if x.ended_at else s+timedelta(hours=6)
        if s <= t <= e: return True
    return False


def _effect_result(name:str, train_rows:list[dict[str,Any]], test_rows:list[dict[str,Any]], profile:dict[int,float], global_ci:float, flag_key:str, min_exposed_train:int, min_exposed_test:int)->dict[str,Any]:
    exposed=[r for r in train_rows if r.get(flag_key)]; unexposed=[r for r in train_rows if not r.get(flag_key)]
    if len(train_rows)<48 or len(exposed)<min_exposed_train or len(unexposed)<16 or len(test_rows)<12:
        return {'effect':name,'status':'insufficient','validated':False,'training_pairs':len(train_rows),'exposed_training':len(exposed),'validation_pairs':len(test_rows),'reason':'Not enough paired exposed/unexposed evidence for a defensible road-specific effect.'}
    exp_res=[r['ci']-_predict_base(r,profile,global_ci) for r in exposed]
    unexp_res=[r['ci']-_predict_base(r,profile,global_ci) for r in unexposed]
    effect=max(-0.20,min(0.20,mean(exp_res)-mean(unexp_res)))
    baseline_errors=[]; adjusted_errors=[]; exposed_test=0
    for r in test_rows:
        b=_predict_base(r,profile,global_ci); baseline_errors.append(abs(b-r['ci']))
        if r.get(flag_key): exposed_test+=1; a=max(0,min(1,b+effect))
        else: a=b
        adjusted_errors.append(abs(a-r['ci']))
    bmae=_mae(baseline_errors) or 0.0; amae=_mae(adjusted_errors) or 0.0
    improvement=(bmae-amae)/bmae if bmae>0 else 0.0
    validated=exposed_test>=min_exposed_test and abs(effect)>=0.005 and improvement>=0.02
    return {'effect':name,'status':'validated' if validated else 'not_validated','validated':validated,'ci_adjustment':round(effect,4),'training_pairs':len(train_rows),'exposed_training':len(exposed),'validation_pairs':len(test_rows),'exposed_validation':exposed_test,'baseline_validation_mae':round(bmae,4),'adjusted_validation_mae':round(amae,4),'relative_mae_improvement_pct':round(improvement*100,2),'reason':'Effect is applied only when holdout validation improves by at least 2%.' if validated else 'Observed effect did not meet the holdout evidence/improvement gate; ITICAS will keep it advisory only.'}


async def calibrate_context_effects(location_id:int, lookback_days:int=90)->dict[str,Any]:
    lookback_days=max(7,min(int(lookback_days),365))
    end=datetime.now(timezone.utc); start=end-timedelta(days=lookback_days)
    with SessionLocal() as db:
        loc=db.get(MonitoringLocation,location_id)
        if not loc: raise LookupError('Monitoring location not found.')
        rows=list(db.scalars(select(TrafficObservation).where(TrafficObservation.location_id==location_id,TrafficObservation.observed_at>=_db(start),TrafficObservation.congestion_index.is_not(None)).order_by(TrafficObservation.observed_at)).all())
        incidents=list(db.scalars(select(TrafficIncident).where(TrafficIncident.location_id==location_id,TrafficIncident.started_at.is_not(None),TrafficIncident.started_at>=_db(start-timedelta(days=1))).order_by(TrafficIncident.started_at)).all())
    hourly=_hourly_traffic(rows)
    weather={'hourly':[],'status':'unavailable'}
    if loc.latitude is not None and loc.longitude is not None and hourly:
        try: weather=await hourly_weather_history(float(loc.latitude),float(loc.longitude),hourly[0]['time_utc'],hourly[-1]['time_utc'])
        except WeatherUnavailable as exc: weather={'hourly':[],'status':'unavailable','reason':str(exc)}
        except Exception as exc: weather={'hourly':[],'status':'unavailable','reason':str(exc)}
    wb={}
    for w in weather.get('hourly') or []:
        try: wb[datetime.fromisoformat(str(w['time_utc']).replace('Z','+00:00')).astimezone(timezone.utc).replace(minute=0,second=0,microsecond=0)]=w
        except Exception: pass
    paired=[]
    for r in hourly:
        w=wb.get(r['time_utc']); rain=float((w or {}).get('precipitation_mm') or 0.0)
        paired.append({**r,'rain':rain>0.0,'rain_mm':rain,'incident':_incident_active(incidents,r['time_utc'])})
    split=max(24,int(len(paired)*0.75)) if paired else 0
    if split>=len(paired): split=max(0,len(paired)-1)
    train,test=paired[:split],paired[split:]
    profile,g=_clock_baseline(train)
    rain=_effect_result('rain',train,test,profile,g,'rain',8,2)
    incident=_effect_result('incident',train,test,profile,g,'incident',6,2)
    result={'status':'completed','location_id':location_id,'location_name':loc.name,'calibrated_at':datetime.now(timezone.utc).isoformat(),'lookback_days':lookback_days,'traffic_observations':len(rows),'paired_hourly_samples':len(paired),'weather_status':weather.get('status'),'rain':rain,'incident':incident,'scientific_rule':'An exogenous effect is allowed to alter forecasts only after road-specific holdout validation demonstrates improvement. Otherwise it remains advisory.'}
    with SessionLocal() as db:
        db.add(PredictionContextCalibration(location_id=location_id,calibrated_at=datetime.now(timezone.utc),lookback_days=lookback_days,status='completed',rain_validated=1 if rain.get('validated') else 0,rain_adjustment_ci=rain.get('ci_adjustment'),incident_validated=1 if incident.get('validated') else 0,incident_adjustment_ci=incident.get('ci_adjustment'),paired_samples=len(paired),details_json=json.dumps(result,default=str)))
        db.commit()
    return result


def latest_context_calibration(location_id:int)->dict[str,Any]:
    with SessionLocal() as db:
        row=db.scalars(select(PredictionContextCalibration).where(PredictionContextCalibration.location_id==location_id).order_by(PredictionContextCalibration.id.desc()).limit(1)).first()
    if not row: return {'status':'not_calibrated','location_id':location_id,'scientific_rule':'Run road-specific context calibration before exogenous effects may alter the forecast mean.'}
    try: d=json.loads(row.details_json or '{}')
    except Exception: d={}
    d.setdefault('status',row.status); d['calibration_id']=row.id
    return d
