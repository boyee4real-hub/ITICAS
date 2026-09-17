from pathlib import Path
p=Path('backend/app/main.py');s=p.read_text(encoding='utf-8');m='# ITICAS_STAGE13_REQUEST_CONSERVATION'
a='\n# ITICAS_STAGE13_REQUEST_CONSERVATION\nfrom .request_conservation import status as _rcs\nfrom .temporal_route_intelligence import analyse as _tra\n@app.get("/api/providers/request-conservation/status")\ndef stage13_rc(days:int=1): return _rcs(days)\n@app.get("/api/traffic-intelligence/temporal")\ndef stage13_temporal(study_id:str="stage10_ibadan"): return _tra(study_id)\n'
if m not in s:p.write_text(s+a,encoding='utf-8');print('[PASS] Stage13 APIs installed')
else:print('[PASS] Stage13 already installed')
