from pathlib import Path

p = Path("backend/app/diagnostics.py")
s = p.read_text(encoding="utf-8")

# Stage14 accidentally inserted "import os" before __future__.
# Move all future imports back to the legal first-code position.
lines = s.splitlines()
future = [x for x in lines if x.strip().startswith("from __future__ import")]
body = [x for x in lines if not x.strip().startswith("from __future__ import")]

# Remove duplicate leading import os introduced by Stage14 if present.
seen_os = False
clean = []
for x in body:
    if x.strip() == "import os":
        if seen_os:
            continue
        seen_os = True
    clean.append(x)

new = []
if future:
    new.extend(future)
new.extend(clean)
p.write_text("\n".join(new) + "\n", encoding="utf-8")
print("[PASS] diagnostics future-import ordering repaired")
