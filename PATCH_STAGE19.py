from pathlib import Path
p=Path("backend/app/main.py");s=p.read_text(encoding="utf-8");m="# ITICAS_STAGE19_CENTRAL_RELEASE_GATE"
a="""\n# ITICAS_STAGE19_CENTRAL_RELEASE_GATE
from .central_release_gate import status as _s19status
@app.get("/api/release/central-access-readiness")
def stage19_central_access_readiness(): return _s19status()
"""
if m not in s:p.write_text(s+a,encoding="utf-8");print("[PASS] Stage19 central release gate installed")
else:print("[PASS] Stage19 already installed")
