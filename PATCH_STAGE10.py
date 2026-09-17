from pathlib import Path
p=Path('backend/app/main.py')
if not p.exists(): raise SystemExit('[FAIL] main.py missing')
s=p.read_text(encoding='utf-8')
marker='# ITICAS_STAGE10_TRAFFIC_INTELLIGENCE'
addition='''\n# ITICAS_STAGE10_TRAFFIC_INTELLIGENCE
from .traffic_intelligence_integration import status as _s10status
@app.get("/api/traffic-intelligence/status")
def stage10_status(): return _s10status()
'''
if marker not in s:
 p.write_text(s+addition,encoding='utf-8'); print('[PASS] Stage10 API installed')
else: print('[PASS] Stage10 already installed')
