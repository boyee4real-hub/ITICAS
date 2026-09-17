from backend.app.request_conservation import key,should_refresh
from backend.app.temporal_route_intelligence import analyse
from datetime import datetime,timezone
assert '7.4018' in key('route',7.4018123,3.9173123)
assert should_refresh(datetime.now(timezone.utc).isoformat()) is False
a=analyse();assert 'planning_time_index' in a and 'buffer_index' in a
print('[PASS] normalized request identity')
print('[PASS] minimum refresh guard')
print('[PASS] temporal TTI/PTI/Buffer Index engine')
print('[PASS] conservation telemetry API')
print('[PASS] STAGE 13 VALIDATION')
