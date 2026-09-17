import os,sqlite3
from datetime import datetime,timezone,timedelta
from pathlib import Path
TTL=max(300,int(os.getenv('ITICAS_TRAFFIC_CACHE_TTL_SECONDS','300')))
def db():
 p=Path(os.getenv('ITICAS_DATA_ROOT') or (Path(os.getenv('LOCALAPPDATA','.'))/'ITICAS'))/'data/provider_state/request_conservation.sqlite3';p.parent.mkdir(parents=True,exist_ok=True)
 with sqlite3.connect(p) as c:c.execute('CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,ts TEXT,kind TEXT,key TEXT,detail TEXT)')
 return p
def event(kind,key='',detail=''):
 with sqlite3.connect(db()) as c:c.execute('INSERT INTO events(ts,kind,key,detail) VALUES(?,?,?,?)',(datetime.now(timezone.utc).isoformat(),kind,key,detail))
def key(kind,*parts):
 return '|'.join([kind]+[f'{x:.4f}' if isinstance(x,(float,int)) else str(x).lower().strip() for x in parts])
def should_refresh(acquired_at):
 if not acquired_at:return True
 try:
  d=datetime.fromisoformat(str(acquired_at).replace('Z','+00:00'));d=d if d.tzinfo else d.replace(tzinfo=timezone.utc)
  return datetime.now(timezone.utc)-d>=timedelta(seconds=TTL)
 except:return True
def status(days=1):
 since=(datetime.now(timezone.utc)-timedelta(days=days)).isoformat()
 with sqlite3.connect(db()) as c:r=dict(c.execute('SELECT kind,count(*) FROM events WHERE ts>=? GROUP BY kind',(since,)).fetchall())
 return {'period_days':days,'fresh_provider_acquisitions':r.get('provider_call',0),'cache_hits':r.get('cache_hit',0),'database_reuse':r.get('database_reuse',0),'duplicate_requests_prevented':r.get('duplicate_prevented',0),'grouped_requests_saved':r.get('grouped_saved',0),'circuit_blocked':r.get('circuit_blocked',0),'all_events':r}
