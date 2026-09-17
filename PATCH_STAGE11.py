from pathlib import Path
p=Path('backend/app/main.py')
s=p.read_text(encoding='utf-8')
if '# ITICAS_STAGE11_UI_BRIDGE' not in s:
    s += '''\n# ITICAS_STAGE11_UI_BRIDGE
from .stage11_ui_bridge import latest as _s11latest
@app.get("/api/traffic-intelligence/ui-summary")
def stage11_ui_summary(study_id:str="stage10_ibadan"): return _s11latest(study_id)
'''
    p.write_text(s,encoding='utf-8')
    print('[PASS] Stage11 UI API bridge installed')
else:
    print('[PASS] Stage11 already installed')
