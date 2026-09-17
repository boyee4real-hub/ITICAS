from __future__ import annotations
import os, json, sqlite3
from dataclasses import asdict
from pathlib import Path
from .tomtom_route_traffic import TomTomTrafficAwareRouting, corridor_pairs
def db():
 p=Path(os.getenv('ITICAS_DATA_ROOT') or Path.home()/'.iticas')/'data'/'traffic_intelligence'/'route_observations.sqlite3'; p.parent.mkdir(parents=True,exist_ok=True); return p
def init():
 with sqlite3.connect(db()) as c: c.execute('CREATE TABLE IF NOT EXISTS route_observations(id INTEGER PRIMARY KEY,study_id TEXT,section_no INTEGER,acquired_at TEXT,status TEXT,cache_hit INTEGER,tti REAL,travel_time_s INTEGER,no_traffic_time_s INTEGER,excess_s INTEGER,excess_ratio REAL,provider_delay_s INTEGER,congestion_class TEXT,payload_json TEXT)')
def derive(d):
 tt=d.get('travel_time_s'); nt=d.get('no_traffic_time_s'); ex=tt-nt if tt is not None and nt is not None else None
 return ex, round(ex/nt,4) if ex is not None and nt else None
class TrafficIntelligenceIntegrator:
 def __init__(self,target_sections=8): self.target_sections=int(target_sections); init()
 def acquire_corridor(self,study_id,probes,use_cache=True):
  probes=list(probes); pairs=corridor_pairs(probes,self.target_sections); client=TomTomTrafficAwareRouting(); rows=[]; counts={'available':0,'cached':0,'provider_failed':0,'prevented':0}
  for i,(a,b) in enumerate(pairs,1):
   d=asdict(client.acquire(a,b,use_cache)); ex,ratio=derive(d); d.update(section_no=i,excess_s=ex,excess_ratio=ratio,provider_delay_s=d.get('traffic_delay_s'))
   if d['status']=='available': counts['available']+=1; counts['cached']+=int(bool(d.get('cache_hit')))
   else: counts['provider_failed']+=1
   with sqlite3.connect(db()) as c: c.execute('INSERT INTO route_observations(study_id,section_no,acquired_at,status,cache_hit,tti,travel_time_s,no_traffic_time_s,excess_s,excess_ratio,provider_delay_s,congestion_class,payload_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(study_id,i,d['acquired_at'],d['status'],int(bool(d.get('cache_hit'))),d.get('tti'),d.get('travel_time_s'),d.get('no_traffic_time_s'),ex,ratio,d.get('provider_delay_s'),d.get('congestion_class'),json.dumps(d)))
   rows.append(d)
   if d['status'] in ('quota_exhausted','authentication_or_entitlement_error'): counts['prevented']+=max(0,len(pairs)-i); break
  return {'study_id':study_id,'probe_count':len(probes),'representative_section_count':len(pairs),'attempted_section_count':len(rows),'counts':counts,'evidence_type':'traffic_aware_route','direct_point_speed':False,'sections':rows}
def status(): init(); return {'stage':'10','database':str(db()),'target_sections_default':8,'evidence_type':'traffic_aware_route','direct_point_speed':False}
