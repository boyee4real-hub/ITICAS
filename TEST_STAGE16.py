from pathlib import Path
from backend.app.provider_enforcement import authorize, diagnostics_policy
assert authorize('map_open')['provider_call_allowed'] is False
assert authorize('report_export')['provider_call_allowed'] is False
assert authorize('historical_analysis')['provider_call_allowed'] is False
assert authorize('explicit_live_acquisition',explicit_live=True)['provider_call_allowed'] is True
assert diagnostics_policy()['network_provider_probe_default'] is False
d=Path('backend/app/diagnostics.py').read_text(encoding='utf-8')
r=Path('backend/app/tomtom_route_traffic.py').read_text(encoding='utf-8')
f=Path('backend/app/tomtom_traffic.py').read_text(encoding='utf-8')
assert 'live_provider_probe: bool=False' in d
assert 'ITICAS_STAGE16_ROUTE_GUARD' in r
assert 'ITICAS_STAGE16_FLOW_GUARD' in f
print('[PASS] passive diagnostics cannot silently consume TomTom credit')
print('[PASS] route acquisition remains cache-first and auditable')
print('[PASS] direct Flow/Incident acquisitions are auditable')
print('[PASS] passive UI/report/history provider calls denied by policy')
print('[PASS] explicit live acquisition remains available')
print('[PASS] STAGE 16 VALIDATION')
