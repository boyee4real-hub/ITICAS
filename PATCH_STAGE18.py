from pathlib import Path
p=Path("backend/app/main.py");s=p.read_text(encoding="utf-8");m="# ITICAS_STAGE18_RELEASE_QUALIFICATION"
a="""\n# ITICAS_STAGE18_RELEASE_QUALIFICATION
from .release_qualification import report as _s18report, write_json as _s18write
from .delivery_readiness import readiness as _s18ready
@app.get("/api/release/research-report")
def stage18_report(study_id:str="stage10_ibadan"): return _s18report(study_id)
@app.post("/api/release/research-report/export")
def stage18_export(study_id:str="stage10_ibadan"): return {"path":_s18write(study_id)}
@app.get("/api/release/readiness")
def stage18_readiness(): return _s18ready()
"""
if m not in s:p.write_text(s+a,encoding="utf-8");print("[PASS] Stage18 release APIs installed")
else:print("[PASS] Stage18 already installed")
