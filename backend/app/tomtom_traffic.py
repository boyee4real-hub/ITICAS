from __future__ import annotations
from datetime import datetime, timezone
import asyncio
import json
import math
import socket
import httpx
from .config import settings
from .request_conservation import event as _conservation_event # ITICAS_STAGE16_FLOW_GUARD

FLOW_URL = "https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json"
INCIDENT_URL = "https://api.tomtom.com/traffic/services/5/incidentDetails"
INCIDENT_FIELDS = "{incidents{type,geometry{type,coordinates},properties{id,iconCategory,magnitudeOfDelay,events{description,code,iconCategory},startTime,endTime,from,to,length,delay,roadNumbers,timeValidity,probabilityOfOccurrence,numberOfReports,lastReportTime}}}"

class ProviderNotConfigured(RuntimeError):
    pass

class ProviderRequestError(RuntimeError):
    def __init__(self, message: str, *, category: str = "provider_error", retryable: bool = False,
                 status_code: int | None = None, attempts: int = 1):
        super().__init__(message)
        self.category = category
        self.retryable = retryable
        self.status_code = status_code
        self.attempts = attempts

    def as_dict(self) -> dict:
        return {
            "category": self.category,
            "message": str(self),
            "retryable": self.retryable,
            "http_status": self.status_code,
            "attempts": self.attempts,
        }

def parse_iso(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None

def congestion_index(current_speed, free_flow_speed):
    if current_speed is None or free_flow_speed in (None, 0):
        return None
    return round(max(0.0, min(1.0, 1.0 - float(current_speed) / float(free_flow_speed))), 6)

def bbox_for_radius(latitude, longitude, radius_m):
    lat = float(latitude)
    lon = float(longitude)
    radius = max(100.0, float(radius_m))
    dlat = radius / 111_320.0
    cos_lat = max(0.05, abs(math.cos(math.radians(lat))))
    dlon = radius / (111_320.0 * cos_lat)
    return f"{lon-dlon:.7f},{lat-dlat:.7f},{lon+dlon:.7f},{lat+dlat:.7f}"

def event_description(events):
    if not isinstance(events, list):
        return None
    parts=[]
    for event in events:
        if isinstance(event, dict) and event.get("description"):
            parts.append(str(event["description"]))
    return "; ".join(parts) or None

def _cause_chain_text(exc: BaseException) -> str:
    parts=[]
    seen=set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        parts.append(str(cur))
        cur = cur.__cause__ or cur.__context__
    return " | ".join(parts).lower()

def classify_http_error(exc: BaseException, status_code: int | None = None) -> tuple[str, bool, str]:
    if status_code in (401, 403):
        return "authentication_failure", False, "Traffic provider rejected the configured credential or access permission."
    if status_code == 429:
        return "rate_limited", True, "Traffic provider rate limit reached. ITICAS will retry with backoff."
    if status_code in (500, 502, 503, 504):
        return "provider_temporarily_unavailable", True, "Traffic provider is temporarily unavailable."
    if status_code == 400:
        return "invalid_provider_request", False, "Traffic provider rejected the request parameters."
    if status_code is not None:
        return "provider_http_error", False, f"Traffic provider returned HTTP {status_code}."

    chain = _cause_chain_text(exc)
    if "getaddrinfo" in chain or "name or service not known" in chain or isinstance(exc, socket.gaierror):
        return "network_dns_failure", True, "DNS lookup for the traffic provider failed. Check internet/DNS connectivity."
    if isinstance(exc, (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout)) or "timed out" in chain:
        return "network_timeout", True, "Traffic provider request timed out, possibly because of weak or unstable internet connectivity."
    if isinstance(exc, (httpx.ConnectError, httpx.NetworkError)):
        return "network_connectivity_failure", True, "Could not reach the traffic provider. Check internet connectivity."
    return "provider_response_error", True, "Traffic provider response could not be completed or decoded."

class TomTomTrafficClient:
    provider_name = "TomTom Traffic API"

    def __init__(self, api_key: str | None = None, timeout: float | None = None):
        self.api_key = (api_key if api_key is not None else settings.tomtom_api_key) or ""
        self.timeout = timeout if timeout is not None else settings.tomtom_timeout_seconds
        self.retry_attempts = max(1, int(settings.provider_retry_attempts))
        self.retry_backoff_seconds = max(0.1, float(settings.provider_retry_backoff_seconds))

    @property
    def configured(self):
        return bool(self.api_key.strip())

    def _require_key(self):
        if not self.configured:
            raise ProviderNotConfigured("TOMTOM_API_KEY is not configured.")

    async def _get(self, url, *, params):
        self._require_key()
        last_error: ProviderRequestError | None = None
        timeout = httpx.Timeout(self.timeout, connect=min(self.timeout, 10.0))
        for attempt in range(1, self.retry_attempts + 1):
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.get(url, params=params, headers={"Accept": "application/json"})
                if response.status_code >= 400:
                    body_text = response.text or ""
                    body_lower = body_text.lower()
                    if response.status_code == 403 and ("insufficientfunds" in body_lower or "enough credits" in body_lower or "insufficient funds" in body_lower):
                        category, retryable, friendly = (
                            "provider_credit_exhausted",
                            False,
                            "TomTom live traffic quota/credits are exhausted. ITICAS will use non-live fallbacks where scientifically valid.",
                        )
                    else:
                        category, retryable, friendly = classify_http_error(RuntimeError(), response.status_code)
                    err = ProviderRequestError(
                        f"{friendly} (HTTP {response.status_code})",
                        category=category,
                        retryable=retryable,
                        status_code=response.status_code,
                        attempts=attempt,
                    )
                    if retryable and attempt < self.retry_attempts:
                        last_error = err
                        await asyncio.sleep(self.retry_backoff_seconds * (2 ** (attempt - 1)))
                        continue
                    raise err
                try:
                    return response.json()
                except ValueError as exc:
                    category, retryable, friendly = classify_http_error(exc)
                    raise ProviderRequestError(
                        friendly,
                        category=category,
                        retryable=retryable,
                        attempts=attempt,
                    ) from exc
            except ProviderRequestError:
                raise
            except httpx.HTTPError as exc:
                category, retryable, friendly = classify_http_error(exc)
                err = ProviderRequestError(
                    friendly,
                    category=category,
                    retryable=retryable,
                    attempts=attempt,
                )
                last_error = err
                if retryable and attempt < self.retry_attempts:
                    await asyncio.sleep(self.retry_backoff_seconds * (2 ** (attempt - 1)))
                    continue
                raise err from exc
        if last_error:
            raise last_error
        raise ProviderRequestError("Traffic provider request failed.")

    async def fetch_flow(self, latitude, longitude):
        _conservation_event("provider_call",f"flow|{float(latitude):.4f}|{float(longitude):.4f}","explicit_flow")
        return await self._get(FLOW_URL, params={
            "key": self.api_key,
            "point": f"{float(latitude):.7f},{float(longitude):.7f}",
            "unit": "kmph",
            "openLr": "false",
        })

    async def fetch_incidents(self, latitude, longitude, radius_m):
        _conservation_event("provider_call",f"incidents|{float(latitude):.4f}|{float(longitude):.4f}|{int(radius_m)}","explicit_incidents")
        return await self._get(INCIDENT_URL, params={
            "key": self.api_key,
            "bbox": bbox_for_radius(latitude, longitude, radius_m),
            "fields": INCIDENT_FIELDS,
            "language": "en-GB",
            "timeValidityFilter": "present",
        })

    @staticmethod
    def normalize_flow(payload, observed_at=None):
        data = payload.get("flowSegmentData") or {}
        if not data:
            return None
        current_speed = data.get("currentSpeed")
        free_speed = data.get("freeFlowSpeed")
        current_tt = data.get("currentTravelTime")
        free_tt = data.get("freeFlowTravelTime")
        delay = None
        if current_tt is not None and free_tt is not None:
            delay = max(0.0, float(current_tt) - float(free_tt))
        road_closure = data.get("roadClosure")
        return {
            "current_speed_kmh": float(current_speed) if current_speed is not None else None,
            "free_flow_speed_kmh": float(free_speed) if free_speed is not None else None,
            "jam_factor": None,
            "congestion_index": congestion_index(current_speed, free_speed),
            "delay_seconds": delay,
            "current_travel_time_seconds": float(current_tt) if current_tt is not None else None,
            "free_flow_travel_time_seconds": float(free_tt) if free_tt is not None else None,
            "confidence": float(data["confidence"]) if data.get("confidence") is not None else None,
            "road_closed": 1 if road_closure is True else 0 if road_closure is False else None,
            "functional_road_class": data.get("frc"),
            "segment_geometry_json": json.dumps(data.get("coordinates"), separators=(",", ":")) if data.get("coordinates") is not None else None,
            "source_timestamp": observed_at or datetime.now(timezone.utc),
            "raw_reference": json.dumps(data, separators=(",", ":")),
        }

    @staticmethod
    def normalize_incidents(payload, observed_at=None):
        rows=[]
        source_time = observed_at or datetime.now(timezone.utc)
        for incident in payload.get("incidents") or []:
            props = incident.get("properties") or {}
            events = props.get("events") or []
            icon = props.get("iconCategory")
            incident_type = None
            if events and isinstance(events[0], dict):
                incident_type = events[0].get("description") or str(events[0].get("iconCategory") or "")
            if not incident_type:
                incident_type = f"category_{icon}" if icon is not None else "traffic_incident"
            rows.append({
                "provider_incident_id": str(props.get("id")) if props.get("id") is not None else None,
                "incident_type": str(incident_type)[:100],
                "description": event_description(events),
                "severity": str(props.get("magnitudeOfDelay")) if props.get("magnitudeOfDelay") is not None else None,
                "magnitude_of_delay": int(props["magnitudeOfDelay"]) if props.get("magnitudeOfDelay") is not None else None,
                "delay_seconds": float(props["delay"]) if props.get("delay") is not None else None,
                "road_from": props.get("from"),
                "road_to": props.get("to"),
                "started_at": parse_iso(props.get("startTime")),
                "ended_at": parse_iso(props.get("endTime")),
                "source_timestamp": source_time,
                "raw_json": json.dumps(incident, separators=(",", ":")),
            })
        return rows


# ITICAS_STAGE04_QUOTA_INTELLIGENCE
from .traffic_quota import before as quota_before, success as quota_success, failure as quota_failure, status as quota_status
def iticas_quota_guard(lat,lon): return quota_before("tomtom",lat,lon)
def iticas_quota_success(lat,lon,payload): return quota_success("tomtom",lat,lon,payload)
def iticas_quota_failure(lat,lon,status_code=None,body=""): return quota_failure("tomtom",lat,lon,status_code,body)
def iticas_quota_status(): return quota_status("tomtom")

# ITICAS_STAGE05_GUARDED_FLOW
from .traffic_quota import before as _q_before, success as _q_success, failure as _q_failure, status as quota_status
_ITICAS_UNGUARDED_FETCH_FLOW=TomTomTrafficClient.fetch_flow
async def _iticas_guarded_fetch_flow(self,latitude,longitude):
 d=_q_before("tomtom",latitude,longitude)
 if d.get("reason")=="recent_cache_hit": return d["cached"]["payload"]
 if not d.get("allow"):
  raise ProviderRequestError("ITICAS quota protection: "+str(d.get("reason")),category=str(d.get("reason") or "provider_circuit_open"),retryable=False,attempts=0)
 try: p=await _ITICAS_UNGUARDED_FETCH_FLOW(self,latitude,longitude)
 except ProviderRequestError as e:
  _q_failure("tomtom",latitude,longitude,getattr(e,"status_code",None),f"{getattr(e,'category','')} {e}"); raise
 _q_success("tomtom",latitude,longitude,p); return p
TomTomTrafficClient.fetch_flow=_iticas_guarded_fetch_flow
def iticas_quota_status(): return quota_status("tomtom")


# ITICAS_STAGE08_AUTHORIZED_KEYRING
from .tomtom_keyring import credentials as _tt_credentials, safe_status as tomtom_keyring_status
_ITICAS_STAGE08_PREVIOUS_FETCH_FLOW = TomTomTrafficClient.fetch_flow
async def _iticas_stage08_keyring_fetch_flow(self, latitude, longitude):
    creds=_tt_credentials()
    if not creds: return await _ITICAS_STAGE08_PREVIOUS_FETCH_FLOW(self, latitude, longitude)
    last_error=None
    for index,cred in enumerate(creds):
        candidate=TomTomTrafficClient(api_key=cred.key, timeout=self.timeout)
        try:
            return await _ITICAS_STAGE08_PREVIOUS_FETCH_FLOW(candidate, latitude, longitude)
        except ProviderRequestError as exc:
            last_error=exc
            if getattr(exc,"category","")=="authentication_failure" and index+1<len(creds):
                continue
            raise
    if last_error: raise last_error
    raise ProviderNotConfigured("No usable TomTom credential is configured.")
TomTomTrafficClient.fetch_flow=_iticas_stage08_keyring_fetch_flow
