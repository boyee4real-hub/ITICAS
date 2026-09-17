from __future__ import annotations

from math import radians, sin, cos, sqrt, atan2, erf, exp
from statistics import mean, pstdev
from sqlalchemy import select

from .database import SessionLocal, MonitoringLocation
from .analytics import analyze_location

EARTH_KM = 6371.0088


def haversine_km(lat1, lon1, lat2, lon2):
    p1, p2 = radians(lat1), radians(lat2)
    dphi = radians(lat2-lat1); dl = radians(lon2-lon1)
    a = sin(dphi/2)**2 + cos(p1)*cos(p2)*sin(dl/2)**2
    return 2*EARTH_KM*atan2(sqrt(a), sqrt(max(0.0,1-a)))


def _p_two_sided(z):
    # Normal approximation; adequate for screening, not a substitute for permutation validation.
    return max(0.0, min(1.0, 1-erf(abs(z)/sqrt(2))))


def _gi_star(points, bandwidth_km=5.0):
    n=len(points)
    if n < 4:
        return {p['id']:{'z_score':None,'p_value':None,'class':'insufficient'} for p in points}
    xs=[p['mean_congestion_index'] for p in points]
    xbar=mean(xs); s=pstdev(xs)
    if s == 0:
        return {p['id']:{'z_score':0.0,'p_value':1.0,'class':'not_significant'} for p in points}
    out={}
    for i,p in enumerate(points):
        ws=[]
        for j,q in enumerate(points):
            if i==j:
                w=1.0
            else:
                d=haversine_km(p['lat'],p['lon'],q['lat'],q['lon'])
                w=max(0.0,1-d/bandwidth_km) if d <= bandwidth_km else 0.0
            ws.append(w)
        sw=sum(ws); sw2=sum(w*w for w in ws)
        den=s*sqrt(max(0.0,(n*sw2-sw*sw)/(n-1)))
        z=(sum(w*x for w,x in zip(ws,xs))-xbar*sw)/den if den else 0.0
        pv=_p_two_sided(z)
        if pv <= .01 and z>0: cls='hotspot_99'
        elif pv <= .05 and z>0: cls='hotspot_95'
        elif pv <= .10 and z>0: cls='hotspot_90'
        elif pv <= .01 and z<0: cls='coldspot_99'
        elif pv <= .05 and z<0: cls='coldspot_95'
        elif pv <= .10 and z<0: cls='coldspot_90'
        else: cls='not_significant'
        out[p['id']]={'z_score':round(z,4),'p_value':round(pv,5),'class':cls}
    return out


def spatial_summary(days=30, bandwidth_km=5.0):
    days=max(1,min(int(days),3650)); bandwidth_km=max(.5,min(float(bandwidth_km),100.0))
    with SessionLocal() as db:
        locs=list(db.scalars(select(MonitoringLocation).where(MonitoringLocation.active==1, MonitoringLocation.latitude.is_not(None), MonitoringLocation.longitude.is_not(None))).all())
    points=[]
    for loc in locs:
        a=analyze_location(loc.id,days)
        if not a: continue
        ci=a['summary'].get('mean_congestion_index')
        if ci is None: continue
        points.append({
            'id':loc.id,'name':loc.name,'road_name':loc.road_name,'city':loc.city,'state':loc.state,
            'lat':loc.latitude,'lon':loc.longitude,'mean_congestion_index':ci,
            'mean_speed_kmh':a['summary'].get('mean_speed_kmh'),'mean_delay_seconds':a['summary'].get('mean_delay_seconds'),
            'coverage_pct':a['coverage'].get('combined_hourly_coverage_pct'),
            'evidence_hours':a['coverage'].get('combined_hour_buckets_with_data'),
            'evidence_grade':a['summary'].get('evidence_grade'),
            'priority_score':a['summary'].get('iticas_decision_priority_score'),
            'priority_class':a['summary'].get('iticas_decision_priority_class'),
        })
    gi=_gi_star(points,bandwidth_km)
    for p in points:
        raw_gi=gi.get(p['id'])
        # Inferential gate: do not call a road a statistically significant hot/cold spot
        # when its temporal evidence is extremely sparse.
        qualified=(p.get('coverage_pct') or 0) >= 20.0 and (p.get('evidence_hours') or 0) >= 24
        if raw_gi and not qualified:
            p['gi_star']={
                'z_score':raw_gi.get('z_score'),'p_value':raw_gi.get('p_value'),
                'class':'insufficient_evidence','screening_class':raw_gi.get('class'),
                'reported_significance':False,
                'reason':'Requires at least 20% temporal coverage and 24 evidence-bearing hours before inferential hotspot significance is reported.'
            }
        else:
            p['gi_star']=dict(raw_gi or {})
            p['gi_star']['reported_significance']=bool(raw_gi and raw_gi.get('class') not in ('not_significant','insufficient'))
        if not qualified and p.get('priority_class'):
            p['priority_class']='Provisional · '+str(p['priority_class'])
        p['spatial_evidence_qualified']=qualified
        # Congestion-weighted kernel exposure at each monitoring point.
        kde=0.0
        for q in points:
            d=haversine_km(p['lat'],p['lon'],q['lat'],q['lon'])
            kde += q['mean_congestion_index']*exp(-0.5*(d/bandwidth_km)**2)
        p['weighted_kernel_exposure']=round(kde,4)
    points.sort(key=lambda x:(x.get('priority_score') or 0), reverse=True)
    return {
        'scope':'Nigeria','period_days':days,'bandwidth_km':bandwidth_km,'locations_analyzed':len(points),
        'network_basis':'configured_active_monitoring_locations_with_coordinates_and_traffic_evidence',
        'network_basis_note':'This ranking is not a list of every road in Nigeria. It ranks only configured ITICAS monitoring locations with usable traffic evidence. Use the Nationwide Road Explorer to query any mapped Nigerian road on demand.',
        'method':{
            'gi_star':'Getis-Ord Gi* normal-approximation screening over monitoring-location mean congestion index using distance-decay weights. ITICAS withholds inferential hot/cold-spot labels unless the individual route has at least 20% temporal coverage and 24 evidence-bearing hours; permutation validation is planned.',
            'kernel':'Congestion-weighted Gaussian kernel exposure, not raw GPS point density.',
            'priority':'Experimental ITICAS Decision Priority Score combines severity, persistence, delay, variability and coverage with transparent weights.'
        },
        'points':points,
        'validation_status':'provider_reference',
        'independent_traffic_benchmark':'not_configured',
    }
