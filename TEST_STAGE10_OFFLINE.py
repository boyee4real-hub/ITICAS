import os,tempfile
os.environ['ITICAS_DATA_ROOT']=tempfile.mkdtemp()
from backend.app.traffic_intelligence_integration import derive,status
assert derive({'travel_time_s':1103,'no_traffic_time_s':965})==(138,0.143)
assert status()['direct_point_speed'] is False
print('EXCESS_TRAVEL_TIME_S=138')
print('EXCESS_RATIO=0.143')
print('[PASS] Stage10 scientific semantics')
