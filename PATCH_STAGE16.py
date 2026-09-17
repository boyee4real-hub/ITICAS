from pathlib import Path

# 1. Add API policy endpoint.
p=Path('backend/app/main.py'); s=p.read_text(encoding='utf-8')
m='# ITICAS_STAGE16_PROVIDER_ENFORCEMENT'
a='\n# ITICAS_STAGE16_PROVIDER_ENFORCEMENT\nfrom .provider_enforcement import authorize as _s16auth, diagnostics_policy as _s16diag\n@app.get("/api/providers/enforcement/status")\ndef stage16_enforcement_status(): return {"policy":_s16diag(),"passive_map":_s16auth("map_open"),"explicit_live":_s16auth("explicit_live_acquisition",explicit_live=True)}\n'
if m not in s:
    p.write_text(s+a,encoding='utf-8'); print('[PASS] Stage16 enforcement API installed')
else: print('[PASS] Stage16 API already installed')

# 2. Make provider readiness diagnostics passive unless explicitly requested.
d=Path('backend/app/diagnostics.py')
if d.exists():
    t=d.read_text(encoding='utf-8')
    old='async def provider_readiness():\n    key=(settings.tomtom_api_key or "").strip()'
    new='async def provider_readiness(live_provider_probe: bool=False):\n    key=(settings.tomtom_api_key or "").strip()\n    if not live_provider_probe:\n        weather=await _weather_probe()\n        tomdns,metdns,osmdns=await asyncio.gather(_dns_async("api.tomtom.com"),_dns_async("api.open-meteo.com"),_dns_async("tile.openstreetmap.org"))\n        return {"scope":"Nigeria","checked_at":__import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),"tomtom_key":{"status":"present" if key else "missing","exposed":False},"tomtom_search":{"status":"not_probed","reason":"request_conservation"},"tomtom_traffic_flow":{"status":"not_probed","reason":"request_conservation"},"weather":weather,"dns":{"api.tomtom.com":tomdns,"open-meteo.com":metdns,"tile.openstreetmap.org":osmdns},"request_conservation":{"passive_diagnostics":True,"provider_credit_consumed":False}}\n    # Explicit live diagnostic requested below.'
    if old in t:
        t=t.replace(old,new)
        d.write_text(t,encoding='utf-8'); print('[PASS] passive diagnostics no longer call TomTom')
    elif 'live_provider_probe: bool=False' in t:
        print('[PASS] passive diagnostics guard already installed')
    else:
        print('[WARN] diagnostics signature differed; left unchanged for safety')

# 3. Route adapter: telemetry + cache-first is already native; record calls/hits.
r=Path('backend/app/tomtom_route_traffic.py')
if r.exists():
    t=r.read_text(encoding='utf-8')
    if '# ITICAS_STAGE16_ROUTE_GUARD' not in t:
        t=t.replace('import httpx','import httpx\nfrom .request_conservation import event as _conservation_event # ITICAS_STAGE16_ROUTE_GUARD')
        t=t.replace('d=json.loads(r[2]); d["cache_hit"]=True; d["original_acquired_at"]=r[0]; return Evidence(**d)',
                    'd=json.loads(r[2]); d["cache_hit"]=True; d["original_acquired_at"]=r[0]; _conservation_event("cache_hit",k,"traffic_aware_route"); return Evidence(**d)')
        t=t.replace('r=httpx.get(u,params=q,timeout=25)',
                    '_conservation_event("provider_call",k,"tomtom_traffic_aware_route")\n        r=httpx.get(u,params=q,timeout=25)')
        r.write_text(t,encoding='utf-8'); print('[PASS] route cache/provider telemetry enforced')
    else: print('[PASS] route guard already installed')

# 4. Direct Flow/Incident calls are explicit acquisition methods; add telemetry.
f=Path('backend/app/tomtom_traffic.py')
if f.exists():
    t=f.read_text(encoding='utf-8')
    if '# ITICAS_STAGE16_FLOW_GUARD' not in t:
        t=t.replace('from .config import settings','from .config import settings\nfrom .request_conservation import event as _conservation_event # ITICAS_STAGE16_FLOW_GUARD')
        t=t.replace('async def fetch_flow(self, latitude, longitude):\n        return await self._get(',
                    'async def fetch_flow(self, latitude, longitude):\n        _conservation_event("provider_call",f"flow|{float(latitude):.4f}|{float(longitude):.4f}","explicit_flow")\n        return await self._get(')
        t=t.replace('async def fetch_incidents(self, latitude, longitude, radius_m):\n        return await self._get(',
                    'async def fetch_incidents(self, latitude, longitude, radius_m):\n        _conservation_event("provider_call",f"incidents|{float(latitude):.4f}|{float(longitude):.4f}|{int(radius_m)}","explicit_incidents")\n        return await self._get(')
        f.write_text(t,encoding='utf-8'); print('[PASS] direct Flow/Incident calls made auditable')
    else: print('[PASS] Flow/Incident telemetry already installed')

print('[PASS] Stage16 patch complete')
