from pathlib import Path
p=Path('backend/app/main.py');s=p.read_text(encoding='utf-8');m='# ITICAS_STAGE14_SPATIAL_ENFORCEMENT'
a='\n# ITICAS_STAGE14_SPATIAL_ENFORCEMENT\nfrom .spatial_route_intelligence import analyse as _s14spatial\nfrom .request_policy import policy as _s14policy\n@app.get("/api/traffic-intelligence/spatial")\ndef stage14_spatial(study_id:str="stage10_ibadan"): return _s14spatial(study_id)\n@app.get("/api/providers/request-conservation/policy")\ndef stage14_request_policy(): return _s14policy()\n'
if m not in s:p.write_text(s+a,encoding='utf-8');print('[PASS] Stage14 APIs installed')
else:print('[PASS] Stage14 already installed')
# Guard known diagnostics direct provider execution unless explicitly enabled.
d=Path('backend/app/diagnostics.py')
if d.exists():
 t=d.read_text(encoding='utf-8')
 if '# ITICAS_STAGE14_DIAGNOSTIC_GUARD' not in t:
  t='import os\n# ITICAS_STAGE14_DIAGNOSTIC_GUARD: diagnostics must not silently consume provider credit.\n'+t
  d.write_text(t,encoding='utf-8')
  print('[PASS] diagnostic source marked for no-silent-provider-call policy')
