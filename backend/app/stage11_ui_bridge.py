from .traffic_intelligence_integration import db as route_db
import sqlite3
def latest(study_id='stage10_ibadan',limit=8):
    try:
        with sqlite3.connect(route_db()) as c:
            c.row_factory=sqlite3.Row
            rows=[dict(x) for x in c.execute('SELECT * FROM route_observations WHERE study_id=? ORDER BY id DESC LIMIT ?',(study_id,int(limit))).fetchall()]
    except Exception:
        rows=[]
    rows=list(reversed(rows))
    return {'study_id':study_id,'research_probes':75,'representative_sections':len(rows),'traffic_aware_observations':sum(x['status']=='available' for x in rows),'cached_observations':sum(bool(x['cache_hit']) for x in rows),'provider_failures':sum(x['status']!='available' for x in rows),'direct_flow_observations':0,'evidence_type':'traffic_aware_route','direct_point_speed':False,'sections':rows}
