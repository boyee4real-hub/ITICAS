from backend.app.request_policy import requires_live,policy
from backend.app.spatial_route_intelligence import analyse
for x in ['page_open','browser_refresh','report_export','historical_analysis','map_open','research_workbench_open']:
 assert requires_live(x) is False
assert requires_live('explicit_live_acquisition') is True
a=analyse();assert a['direct_point_speed'] is False and 'hotspot_rule' in a
assert policy()['historical_never_relabelled_live'] is True
print('[PASS] passive UI/report/history actions classified non-live')
print('[PASS] explicit live acquisition remains available')
print('[PASS] descriptive section-hotspot engine')
print('[PASS] route evidence not relabelled point speed')
print('[PASS] STAGE 14 VALIDATION')
