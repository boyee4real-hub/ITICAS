import py_compile
from pathlib import Path
mods=['main.py','request_conservation.py','temporal_route_intelligence.py','spatial_route_intelligence.py','completion_intelligence.py','provider_enforcement.py','stage12_research_map.py','tomtom_route_traffic.py','tomtom_traffic.py','diagnostics.py']
for m in mods:py_compile.compile(str(Path('backend/app')/m),doraise=True)
from backend.app.core_completion_gate import evaluate
r=evaluate()
for k,v in r['checks'].items():print(('[PASS] ' if v else '[FAIL] ')+k)
print('CORE_CHECKS=%d/%d'%(r['passed'],r['total']))
assert r['core_development_complete'],r
print('[PASS] CORE DEVELOPMENT COMPLETE')
print('[PASS] STAGE 17 VALIDATION')
