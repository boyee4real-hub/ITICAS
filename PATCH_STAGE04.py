from pathlib import Path
p=Path(__file__).parent/"backend"/"app"/"tomtom_traffic.py"
s=p.read_text(encoding="utf-8")
m="# ITICAS_STAGE04_QUOTA_INTELLIGENCE"
if m not in s:
 s+="""\n\n# ITICAS_STAGE04_QUOTA_INTELLIGENCE
from .traffic_quota import before as quota_before, success as quota_success, failure as quota_failure, status as quota_status
def iticas_quota_guard(lat,lon): return quota_before("tomtom",lat,lon)
def iticas_quota_success(lat,lon,payload): return quota_success("tomtom",lat,lon,payload)
def iticas_quota_failure(lat,lon,status_code=None,body=""): return quota_failure("tomtom",lat,lon,status_code,body)
def iticas_quota_status(): return quota_status("tomtom")
"""
 p.write_text(s,encoding="utf-8")
 print("[PASS] quota hooks installed")
else: print("[PASS] quota hooks already present")
