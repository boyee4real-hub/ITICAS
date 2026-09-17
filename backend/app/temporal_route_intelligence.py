import sqlite3,statistics,math
from .traffic_intelligence_integration import db as route_db
def analyse(study_id='stage10_ibadan'):
 try:
  with sqlite3.connect(route_db()) as c:
   c.row_factory=sqlite3.Row;rows=[dict(x) for x in c.execute("SELECT * FROM route_observations WHERE study_id=? AND status='available'",(study_id,))]
 except:rows=[]
 tt=[float(x['travel_time_s']) for x in rows if x.get('travel_time_s') and x.get('no_traffic_time_s')]
 base=[float(x['no_traffic_time_s']) for x in rows if x.get('travel_time_s') and x.get('no_traffic_time_s')]
 tti=[float(x['tti']) for x in rows if x.get('tti') is not None]
 def p95(a):
  if not a:return None
  a=sorted(a);k=(len(a)-1)*.95;f=math.floor(k);c=math.ceil(k);return a[f] if f==c else a[f]*(c-k)+a[c]*(k-f)
 p=p95(tt);m=statistics.mean(tt) if tt else None;b=statistics.mean(base) if base else None
 return {'study_id':study_id,'observations':len(rows),'mean_tti':round(statistics.mean(tti),4) if tti else None,'p95_travel_time_s':round(p,2) if p is not None else None,'planning_time_index':round(p/b,4) if p is not None and b else None,'buffer_index':round((p-m)/m,4) if p is not None and m else None,'limitations':['Reliability metrics strengthen as repeated observations accumulate.','Traffic-aware route evidence is route-level evidence, not direct point-speed ground truth.']}
