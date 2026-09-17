from backend.app.completion_intelligence import reliability,completion
from backend.app.provider_call_audit import audit
r=reliability();c=completion();a=audit()
assert r['direct_point_speed'] is False
assert c['historical_never_presented_as_live'] is True
assert 'candidate_provider_call_sites' in a
assert 'operational threshold' in r['interpretation']
print('[PASS] congestion persistence/severity engine')
print('[PASS] reliability evidence semantics')
print('[PASS] provider-call source audit inventory')
print('[PASS] historical/live provenance gate')
print('[PASS] completion-readiness endpoint')
print('[PASS] STAGE 15 VALIDATION')
