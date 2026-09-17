import py_compile
from pathlib import Path

p=Path("backend/app/diagnostics.py")
lines=p.read_text(encoding="utf-8").splitlines()
first_code=next((x.strip() for x in lines if x.strip() and not x.lstrip().startswith("#")), "")
assert first_code.startswith("from __future__ import"), first_code
py_compile.compile(str(p), doraise=True)
py_compile.compile("backend/app/tomtom_route_traffic.py", doraise=True)
py_compile.compile("backend/app/tomtom_traffic.py", doraise=True)
py_compile.compile("backend/app/provider_enforcement.py", doraise=True)
py_compile.compile("backend/app/main.py", doraise=True)

from backend.app.provider_enforcement import authorize
assert authorize("map_open")["provider_call_allowed"] is False
assert authorize("report_export")["provider_call_allowed"] is False
assert authorize("explicit_live_acquisition", explicit_live=True)["provider_call_allowed"] is True

d=p.read_text(encoding="utf-8")
assert "live_provider_probe: bool=False" in d
assert "request_conservation" in d

print("[PASS] diagnostics import ordering")
print("[PASS] Stage16 modules compile")
print("[PASS] passive diagnostics conservation guard retained")
print("[PASS] passive provider policy retained")
print("[PASS] explicit live acquisition retained")
print("[PASS] STAGE 16 FIX1 VALIDATION")
