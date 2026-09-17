from pathlib import Path
ROOT=Path(r"C:\ITICAS_BUILD\ITICAS_v0.26.3_WINDOWS_DISTRIBUTION_KIT\source\ITICAS_v0.26.3_DISTRIBUTION_SOURCE")
p=ROOT/"backend"/"app"/"main.py"
s=p.read_text(encoding="utf-8")
old='        "provider": "TomTom Search API",\n        "service": "Fuzzy Search v2",'
new='        "provider": ((rows[0].get("provenance") or {}).get("provider") if rows else "TomTom Search API / OpenStreetMap fallback"),\n        "service": ((rows[0].get("provenance") or {}).get("service") if rows else "Nigeria search"),'
if old in s:
    s=s.replace(old,new,1)
    p.write_text(s,encoding="utf-8")
    print("[PASS] Search provenance response patched.")
elif "OpenStreetMap fallback" in s:
    print("[PASS] Search provenance patch already present.")
else:
    raise SystemExit("[FAIL] Could not locate search provenance block in main.py.")
