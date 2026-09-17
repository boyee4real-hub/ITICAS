from pathlib import Path
from backend.app.stage12_research_map import dashboard
d=dashboard()
assert d['evidence_type']=='traffic_aware_route'
assert d['direct_point_speed'] is False
assert 'provenance_note' in d['source_status']
print('[PASS] research traffic dashboard semantics')
print('[PASS] live/cache/provenance presentation contract')
print('[PASS] STAGE 12 VALIDATION')
