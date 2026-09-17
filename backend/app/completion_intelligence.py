import sqlite3,statistics,math
from collections import defaultdict
from .traffic_intelligence_integration import db as route_db

def _rows(study_id):
 try:
  with sqlite3.connect(route_db()) as c:
   c.row_factory=sqlite3.Row
   return [dict(x) for x in c.execute("SELECT * FROM route_observations WHERE study_id=? AND status='available' ORDER BY acquired_at",(study_id,))]
 except Exception:return []

def reliability(study_id='stage10_ibadan'):
 rows=_rows(study_id); by=defaultdict(list)
 for r in rows:
  if r.get('tti') is not None: by[int(r.get('section_no') or 0)].append(float(r['tti']))
 out=[]
 for sec,v in sorted(by.items()):
  v=sorted(v); n=len(v); p95=v[min(n-1,max(0,math.ceil(.95*n)-1))]
  mean=statistics.mean(v)
  out.append({'section_no':sec,'observations':n,'mean_tti':round(mean,4),'p95_tti':round(p95,4),
   'persistence_ratio_tti_gt_1_2':round(sum(x>1.2 for x in v)/n,4),
   'severity_excess_tti':round(statistics.mean(max(0,x-1) for x in v),4)})
 return {'study_id':study_id,'sections':out,'interpretation':'Persistence is the observed share with TTI > 1.2; this is an ITICAS operational threshold, not a universal standard.',
 'evidence_type':'traffic_aware_route','direct_point_speed':False}

def completion(study_id='stage10_ibadan'):
 r=reliability(study_id); n=sum(x['observations'] for x in r['sections'])
 return {'study_id':study_id,'stored_route_observations':n,'reliability_ready':n>=20,
 'publication_caution':None if n>=20 else 'Repeated observations are still limited; reliability/persistence results should be treated as preliminary.',
 'provider_request_rule':'stored/cache first; fresh provider only for explicit live acquisition',
 'historical_never_presented_as_live':True}
