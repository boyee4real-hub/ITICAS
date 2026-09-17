from pathlib import Path
p=Path('backend/app/main.py');s=p.read_text(encoding='utf-8');m='# ITICAS_STAGE15_COMPLETION_INTELLIGENCE'
a='\n# ITICAS_STAGE15_COMPLETION_INTELLIGENCE\nfrom .completion_intelligence import reliability as _s15rel, completion as _s15comp\nfrom .provider_call_audit import audit as _s15audit\n@app.get("/api/traffic-intelligence/reliability")\ndef stage15_reliability(study_id:str="stage10_ibadan"): return _s15rel(study_id)\n@app.get("/api/traffic-intelligence/completion")\ndef stage15_completion(study_id:str="stage10_ibadan"): return _s15comp(study_id)\n@app.get("/api/providers/provider-call-audit")\ndef stage15_provider_audit(): return _s15audit()\n'
if m not in s:p.write_text(s+a,encoding='utf-8');print('[PASS] Stage15 APIs installed')
else:print('[PASS] Stage15 already installed')
