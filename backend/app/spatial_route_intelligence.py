import sqlite3,statistics
from .traffic_intelligence_integration import db as route_db
def analyse(study_id='stage10_ibadan'):
 try:
  with sqlite3.connect(route_db()) as c:
   c.row_factory=sqlite3.Row
   rows=[dict(x) for x in c.execute("SELECT * FROM route_observations WHERE study_id=? AND status='available' ORDER BY section_no,id",(study_id,))]
 except Exception: rows=[]
 by={}
 for r in rows:
  if r.get('tti') is not None: by.setdefault(int(r.get('section_no') or 0),[]).append(float(r['tti']))
 sections=[]
 for n,v in sorted(by.items()):
  sections.append({'section_no':n,'observations':len(v),'mean_tti':round(statistics.mean(v),4),'max_tti':round(max(v),4),
   'evidence_scope':'representative_route_section','direct_point_speed':False})
 vals=[x['mean_tti'] for x in sections]
 threshold=statistics.quantiles(vals,n=4,method='inclusive')[2] if len(vals)>=4 else (max(vals) if vals else None)
 hotspots=[x for x in sections if threshold is not None and x['mean_tti']>=threshold]
 return {'study_id':study_id,'sections':sections,'descriptive_hotspots':hotspots,
 'hotspot_rule':'upper-quartile section mean TTI; descriptive screening, not inferential Gi* significance',
 'direct_point_speed':False,'limitations':['Representative route sections must not be interpreted as independent live speed measurements at every research probe.']}
