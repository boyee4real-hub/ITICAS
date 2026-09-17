from pathlib import Path
p=Path('backend/app/main.py');s=p.read_text(encoding='utf-8');m='# ITICAS_STAGE17_CORE_COMPLETION_GATE'
a='\n# ITICAS_STAGE17_CORE_COMPLETION_GATE\nfrom .core_completion_gate import evaluate as _s17gate\n@app.get("/api/system/core-completion")\ndef stage17_core_completion(): return _s17gate()\n'
if m not in s:p.write_text(s+a,encoding='utf-8');print('[PASS] Stage17 completion endpoint installed')
else:print('[PASS] Stage17 already installed')
