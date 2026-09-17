from __future__ import annotations
import os
# ITICAS_STAGE14_DIAGNOSTIC_GUARD: diagnostics must not silently consume provider credit.
import asyncio, socket, time
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from .config import settings
from .weather_service import current_weather, WeatherUnavailable

async def _probe(url:str, params:dict|None=None):
    def run():
        full=url if not params else f"{url}?{urlencode(params)}"
        req=Request(full,headers={"Accept":"application/json","User-Agent":f"ITICAS/{settings.version}"})
        started=time.perf_counter()
        try:
            with urlopen(req,timeout=float(settings.diagnostics_timeout_seconds)) as r:
                return {"status":"online","http_status":r.status,"latency_ms":round((time.perf_counter()-started)*1000,1)}
        except HTTPError as e:
            return {"status":"unauthorized" if e.code in {401,403} else "degraded","http_status":e.code,"latency_ms":round((time.perf_counter()-started)*1000,1)}
        except Exception as e:
            return {"status":"offline","http_status":None,"error":type(e).__name__,"message":str(e)[:180]}
    return await asyncio.to_thread(run)

async def _dns_async(host):
    def run():
        try: socket.getaddrinfo(host,443); return "resolved"
        except OSError:return "failed"
    try:return await asyncio.wait_for(asyncio.to_thread(run),3.0)
    except asyncio.TimeoutError:return "timeout"

async def _weather_probe():
    try:
        weather=await asyncio.wait_for(current_weather(9.0765,7.3986),7.0)
        return {"status":"online","provider":weather["provider"]}
    except asyncio.TimeoutError:return {"status":"timeout","message":"Weather diagnostic timed out without blocking other checks."}
    except WeatherUnavailable as e:return {"status":"offline","category":e.category,"message":str(e)}

async def provider_readiness(live_provider_probe: bool=False):
    key=(settings.tomtom_api_key or "").strip()
    if not live_provider_probe:
        weather=await _weather_probe()
        tomdns,metdns,osmdns=await asyncio.gather(_dns_async("api.tomtom.com"),_dns_async("api.open-meteo.com"),_dns_async("tile.openstreetmap.org"))
        return {"scope":"Nigeria","checked_at":__import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),"tomtom_key":{"status":"present" if key else "missing","exposed":False},"tomtom_search":{"status":"not_probed","reason":"request_conservation"},"tomtom_traffic_flow":{"status":"not_probed","reason":"request_conservation"},"weather":weather,"dns":{"api.tomtom.com":tomdns,"open-meteo.com":metdns,"tile.openstreetmap.org":osmdns},"request_conservation":{"passive_diagnostics":True,"provider_credit_consumed":False}}
    # Explicit live diagnostic requested below.
    search_task=_probe("https://api.tomtom.com/search/2/search/Abuja.json",{"key":key,"countrySet":"NG","limit":1}) if key else asyncio.sleep(0,result={"status":"missing_credential"})
    flow_task=_probe("https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json",{"key":key,"point":"9.0765,7.3986","unit":"kmph"}) if key else asyncio.sleep(0,result={"status":"missing_credential"})
    search,flow,weather,tomdns,metdns,osmdns=await asyncio.gather(search_task,flow_task,_weather_probe(),_dns_async("api.tomtom.com"),_dns_async("api.open-meteo.com"),_dns_async("tile.openstreetmap.org"))
    return {"scope":"Nigeria","checked_at":__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),"tomtom_key":{"status":"present" if key else "missing","exposed":False},"tomtom_search":search,"tomtom_traffic_flow":flow,"weather":weather,"dns":{"api.tomtom.com":tomdns,"open-meteo.com":metdns,"tile.openstreetmap.org":osmdns},"independent_traffic_benchmark":{"status":"not_configured","message":"Provider-reference validation is explicit; an independent Nigeria-wide traffic ground-truth adapter is not yet configured."},"standardized_environment_reference":{"status":"available_on_demand","dataset":"ERA5-Land reanalysis","traffic_ground_truth":False}}
