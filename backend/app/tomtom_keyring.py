from __future__ import annotations
import os
from dataclasses import dataclass

@dataclass(frozen=True)
class TomTomCredential:
    name: str
    key: str

def credentials() -> list[TomTomCredential]:
    raw = (os.getenv("TOMTOM_API_KEYS") or "").strip()
    items=[]
    if raw:
        for i, token in enumerate(raw.split(","), start=1):
            token=token.strip()
            if not token: continue
            if ":" in token: name,key=token.split(":",1)
            else: name,key=f"key{i}",token
            if key.strip(): items.append(TomTomCredential(name.strip() or f"key{i}",key.strip()))
    if not items:
        single=(os.getenv("TOMTOM_API_KEY") or "").strip()
        if single: items.append(TomTomCredential("primary",single))
    return items

def safe_status():
    c=credentials()
    return {"configured":bool(c),"credential_count":len(c),"credential_names":[x.name for x in c],"secrets_exposed":False}
