import os,tempfile
os.environ["ITICAS_DATA_ROOT"]=tempfile.mkdtemp()
from backend.app.tomtom_route_traffic import corridor_pairs,safe_status,_class
p=[(7.4+i/10000,3.9+i/10000) for i in range(75)]
q=corridor_pairs(p,8)
assert 1<=len(q)<=8
assert _class(1.3)=="heavy"
assert safe_status()["direct_point_speed"] is False
print("PROBES=75 REPRESENTATIVE_ROUTE_SECTIONS=",len(q))
print("[PASS] Stage09 offline scientific/provenance test")
