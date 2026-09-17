from pathlib import Path
p=Path('backend/app/main.py')
s=p.read_text(encoding='utf-8')
marker='# ITICAS_STAGE12_RESEARCH_MAP'
addition='\n# ITICAS_STAGE12_RESEARCH_MAP\nfrom .stage12_research_map import dashboard as _s12dash\n@app.get("/api/research/traffic-intelligence")\ndef stage12_research_traffic(study_id:str="stage10_ibadan"): return _s12dash(study_id)\n'
if marker not in s:
    p.write_text(s+addition,encoding='utf-8')
    print('[PASS] Stage12 research/map endpoint installed')
else:
    print('[PASS] Stage12 already installed')
