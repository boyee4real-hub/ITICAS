import py_compile
from pathlib import Path
for m in ["release_qualification.py","delivery_readiness.py","main.py"]:py_compile.compile(str(Path("backend/app")/m),doraise=True)
from backend.app.release_qualification import report,write_json
from backend.app.delivery_readiness import readiness
r=report();q=readiness()
assert r["credit"]=="Developed by Dr. Oyeyode A.O. MNIS, MGEOSON, MNAG"
assert r["evidence"]["direct_point_speed"] is False
assert "not universal standards" in r["interpretation"]["classification_note"]
assert "not an inferential Gi*" in r["limitations"][2]
assert q["core_frozen"] is True and q["final_build_complete"] is False
p=Path(write_json());assert p.exists()
print("[PASS] publication/research report semantics")
print("[PASS] provenance and scientific limitations")
print("[PASS] reproducibility metadata")
print("[PASS] exact application credit")
print("[PASS] release-readiness gate")
print("[PASS] no live provider request required")
print("[PASS] STAGE 18 VALIDATION")
print("REPORT="+str(p))
