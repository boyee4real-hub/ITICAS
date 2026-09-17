from __future__ import annotations
from datetime import datetime, timezone
import asyncio
import math
import json
from functools import lru_cache
import httpx
from sqlalchemy import select

from .config import settings
from .database import SessionLocal, MonitoringLocation, TrafficObservation
from .tomtom_traffic import TomTomTrafficClient, ProviderNotConfigured, ProviderRequestError, classify_http_error
from .weather_service import current_weather, WeatherUnavailable
from .provider_broker import evaluate as broker_evaluate, configured as broker_configured, BrokerUnavailable

SEARCH_URL = "https://api.tomtom.com/search/2/search/{query}.json"
REVERSE_URL = "https://api.tomtom.com/search/2/reverseGeocode/{position}.json"
OSM_REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"
OSM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"

class SearchUnavailable(RuntimeError):
    def __init__(self, message: str, *, category: str = "search_unavailable", retryable: bool = False,
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

def _as_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _position_lat_lon(value):
    """Normalize provider position variants to ``(lat, lon)``.

    TomTom reverse-geocoding payloads are normally objects with ``lat`` and
    ``lon`` keys, but deployed responses can also expose a comma-separated
    string (and defensive handling of two-item sequences is cheap).  A malformed
    provider position must never turn a map click into an application HTTP 500.
    """
    if isinstance(value, dict):
        return _as_float(value.get("lat")), _as_float(value.get("lon"))
    if isinstance(value, str):
        parts=[part.strip() for part in value.split(",")]
        if len(parts) >= 2:
            return _as_float(parts[0]), _as_float(parts[1])
        return None, None
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        return _as_float(value[0]), _as_float(value[1])
    return None, None

def normalize_search_results(payload: dict) -> list[dict]:
    rows = []
    for result in payload.get("results") or []:
        address = result.get("address") or {}
        position = result.get("position")
        country_code = str(address.get("countryCode") or "").upper()
        if country_code and country_code not in {"NG", "NGA"}:
            continue
        lat, lon = _position_lat_lon(position)
        if lat is None or lon is None:
            continue
        poi = result.get("poi") or {}
        routes = address.get("routeNumbers")
        route = routes[0] if isinstance(routes, list) and routes else None
        name = poi.get("name") or address.get("streetName") or address.get("municipality") or address.get("freeformAddress") or "Selected location"
        road_name = address.get("streetName") or route
        city = address.get("municipality") or address.get("municipalitySubdivision") or address.get("countrySecondarySubdivision")
        state = address.get("countrySubdivision") or address.get("countrySubdivisionName")
        rows.append({
            "id": result.get("id"),
            "type": result.get("type"),
            "score": result.get("score"),
            "name": name,
            "road_name": road_name,
            "freeform_address": address.get("freeformAddress"),
            "city": city,
            "state": state,
            "country": address.get("country") or "Nigeria",
            "country_code": country_code or "NG",
            "latitude": lat,
            "longitude": lon,
            "viewport": result.get("viewport"),
            "poi_category": (poi.get("categories") or [None])[0] if isinstance(poi.get("categories"), list) else None,
            "provenance": {"provider": "TomTom Search API", "service": "Fuzzy Search v2", "country_filter": "NG"},
        })
    return rows



def _road_result_is_specific(row: dict | None) -> bool:
    if not row:
        return False
    road = str(row.get("road_name") or "").strip()
    name = str(row.get("name") or "").strip().lower()
    return bool(road) or (bool(name) and name not in {"nigeria", "selected road", "selected location"})

def _osm_line_geometry(geometry):
    """Return road geometry as [[lat, lon], ...] when Nominatim returns a line."""
    if not isinstance(geometry, dict):
        return None
    kind = geometry.get("type")
    coords = geometry.get("coordinates")
    if kind == "LineString" and isinstance(coords, list):
        rows=[]
        for pair in coords:
            if isinstance(pair, (list, tuple)) and len(pair) >= 2:
                try: rows.append([float(pair[1]), float(pair[0])])
                except (TypeError, ValueError): pass
        return rows if len(rows) > 1 else None
    if kind == "MultiLineString" and isinstance(coords, list):
        best=[]
        for line in coords:
            rows=[]
            for pair in line or []:
                if isinstance(pair, (list, tuple)) and len(pair) >= 2:
                    try: rows.append([float(pair[1]), float(pair[0])])
                    except (TypeError, ValueError): pass
            if len(rows) > len(best): best=rows
        return best if len(best) > 1 else None
    return None

@lru_cache(maxsize=512)
def _osm_reverse_cached(latitude_6: float, longitude_6: float) -> dict | None:
    """Low-volume OSM/Nominatim fallback used only when TomTom has no road name.

    Coordinates are rounded before this cached function is called so repeated clicks
    around the same point do not generate unnecessary public-service requests.
    """
    from urllib.parse import urlencode
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError, URLError
    params={
        "format":"jsonv2",
        "lat":f"{float(latitude_6):.6f}",
        "lon":f"{float(longitude_6):.6f}",
        "zoom":17,
        "addressdetails":1,
        "namedetails":1,
        "polygon_geojson":1,
        "layer":"address",
        "accept-language":"en",
    }
    req=Request(
        f"{OSM_REVERSE_URL}?{urlencode(params)}",
        headers={
            "Accept":"application/json",
            "User-Agent":"ITICAS/0.24.1 Nigeria Traffic Intelligence and Congestion Analysis System",
        },
        method="GET",
    )
    try:
        with urlopen(req, timeout=min(8.0, float(settings.tomtom_timeout_seconds or 8.0))) as response:
            payload=json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, OSError, ValueError, json.JSONDecodeError):
        return None
    address=payload.get("address") or {}
    country_code=str(address.get("country_code") or "").upper()
    if country_code and country_code not in {"NG", "NGA"}:
        return None
    road=address.get("road") or address.get("pedestrian") or address.get("footway") or address.get("path") or address.get("highway")
    if not road:
        return None
    city=address.get("city") or address.get("town") or address.get("village") or address.get("municipality") or address.get("county")
    state=address.get("state")
    return {
        "name":road,
        "road_name":road,
        "freeform_address":payload.get("display_name"),
        "city":city,
        "state":state,
        "country":address.get("country") or "Nigeria",
        "country_code":country_code or "NG",
        "latitude":float(latitude_6),
        "longitude":float(longitude_6),
        "road_geometry":_osm_line_geometry(payload.get("geojson")),
        "osm_type":payload.get("osm_type"),
        "osm_id":payload.get("osm_id"),
        "provenance":{"provider":"OpenStreetMap/Nominatim","service":"Reverse Geocoding fallback","country_scope":"Nigeria"},
    }


def _osm_search_sync(query: str, limit: int = 10) -> list[dict]:
    """Nigeria-scoped Nominatim fallback for place/road search.

    This fallback preserves location search when TomTom Search is unavailable.
    It does not provide live traffic.
    """
    from urllib.parse import urlencode
    from urllib.request import Request, urlopen

    params = {
        "q": query,
        "format": "jsonv2",
        "addressdetails": 1,
        "namedetails": 1,
        "countrycodes": "ng",
        "limit": max(1, min(10, int(limit))),
        "accept-language": "en",
    }
    req = Request(
        f"{OSM_SEARCH_URL}?{urlencode(params)}",
        headers={
            "Accept": "application/json",
            "User-Agent": "ITICAS/0.26.3 Nigeria Traffic Intelligence and Congestion Analysis System",
        },
        method="GET",
    )
    with urlopen(req, timeout=min(10.0, float(settings.tomtom_timeout_seconds or 10.0))) as response:
        payload = json.loads(response.read().decode("utf-8"))

    rows = []
    for item in payload if isinstance(payload, list) else []:
        try:
            lat = float(item.get("lat"))
            lon = float(item.get("lon"))
        except (TypeError, ValueError):
            continue
        address = item.get("address") or {}
        country_code = str(address.get("country_code") or "").upper()
        if country_code and country_code not in {"NG", "NGA"}:
            continue
        road = address.get("road") or address.get("pedestrian") or address.get("highway")
        city = address.get("city") or address.get("town") or address.get("village") or address.get("municipality") or address.get("county")
        state = address.get("state")
        name = (item.get("namedetails") or {}).get("name") or road or item.get("display_name") or query
        rows.append({
            "id": f"osm:{item.get('osm_type')}:{item.get('osm_id')}",
            "type": item.get("type"),
            "score": item.get("importance"),
            "name": name,
            "road_name": road,
            "freeform_address": item.get("display_name"),
            "city": city,
            "state": state,
            "country": address.get("country") or "Nigeria",
            "country_code": country_code or "NG",
            "latitude": lat,
            "longitude": lon,
            "viewport": None,
            "poi_category": item.get("category"),
            "provenance": {
                "provider": "OpenStreetMap/Nominatim",
                "service": "Nigeria search fallback",
                "country_filter": "NG",
            },
        })
    return rows

class TomTomSearchClient:
    provider_name = "TomTom Search API"

    def __init__(self, api_key: str | None = None, timeout: float | None = None):
        self.api_key = ((api_key if api_key is not None else settings.tomtom_api_key) or "").strip()
        self.timeout = timeout if timeout is not None else settings.tomtom_timeout_seconds
        self.retry_attempts = max(1, int(settings.provider_retry_attempts))
        self.retry_backoff_seconds = max(0.1, float(settings.provider_retry_backoff_seconds))

    @property
    def configured(self):
        return bool(self.api_key)

    def _search_sync(self, q: str, limit: int) -> list[dict]:
        """Use the Python standard-library HTTP stack for TomTom Search.

        This deliberately mirrors the direct diagnostic transport validated on the
        deployed Windows host. Keeping Search on urllib also avoids a transport-
        specific authorization discrepancy observed with httpx on that host.
        """
        from urllib.parse import quote, urlencode
        from urllib.request import Request, urlopen
        from urllib.error import HTTPError, URLError

        url = SEARCH_URL.format(query=quote(q, safe=""))
        params = {
            "key": self.api_key,
            "countrySet": "NG",
            "limit": max(1, min(20, int(limit))),
            "typeahead": "false",
            "language": "en-GB",
        }
        request = Request(
            f"{url}?{urlencode(params)}",
            headers={
                "Accept": "application/json",
                "User-Agent": "ITICAS/0.8.0 (Nigeria Traffic Intelligence and Congestion Analysis System)",
            },
            method="GET",
        )
        try:
            with urlopen(request, timeout=float(self.timeout)) as response:
                payload = json.loads(response.read().decode("utf-8"))
                return normalize_search_results(payload)
        except HTTPError as exc:
            category, retryable, friendly = classify_http_error(exc, exc.code)
            raise SearchUnavailable(
                f"{friendly} (HTTP {exc.code})",
                category=category, retryable=retryable, status_code=exc.code, attempts=1
            ) from exc
        except (URLError, OSError, ValueError, json.JSONDecodeError) as exc:
            category, retryable, friendly = classify_http_error(exc)
            raise SearchUnavailable(
                friendly, category=category, retryable=retryable, attempts=1
            ) from exc

    def _reverse_sync(self, latitude: float, longitude: float) -> dict | None:
        """Reverse geocode a clicked Nigerian coordinate to the nearest named road/address."""
        from urllib.parse import urlencode
        from urllib.request import Request, urlopen
        from urllib.error import HTTPError, URLError

        position = f"{float(latitude):.7f},{float(longitude):.7f}"
        params = {
            "key": self.api_key,
            "language": "en-GB",
            "radius": 80,
        }
        request = Request(
            f"{REVERSE_URL.format(position=position)}?{urlencode(params)}",
            headers={
                "Accept": "application/json",
                "User-Agent": "ITICAS/0.24.0 (Nigeria Traffic Intelligence and Congestion Analysis System)",
            },
            method="GET",
        )
        try:
            with urlopen(request, timeout=float(self.timeout)) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            category, retryable, friendly = classify_http_error(exc, exc.code)
            raise SearchUnavailable(
                f"{friendly} (HTTP {exc.code})", category=category, retryable=retryable,
                status_code=exc.code, attempts=1
            ) from exc
        except (URLError, OSError, ValueError, json.JSONDecodeError) as exc:
            category, retryable, friendly = classify_http_error(exc)
            raise SearchUnavailable(friendly, category=category, retryable=retryable, attempts=1) from exc

        addresses = payload.get("addresses") or []
        if not addresses:
            return None
        row = addresses[0] or {}
        address = row.get("address") or {}
        pos = row.get("position")
        country_code = str(address.get("countryCode") or "").upper()
        if country_code and country_code not in {"NG", "NGA"}:
            return None
        lat, lon = _position_lat_lon(pos)
        road = address.get("streetName")
        route_numbers = address.get("routeNumbers") or []
        route = route_numbers[0] if isinstance(route_numbers, list) and route_numbers else None
        city = address.get("municipality") or address.get("municipalitySubdivision") or address.get("countrySecondarySubdivision")
        state = address.get("countrySubdivision") or address.get("countrySubdivisionName")
        freeform = address.get("freeformAddress")
        name = road or route or freeform or city or "Selected road"
        return {
            "name": name,
            "road_name": road or route,
            "freeform_address": freeform,
            "city": city,
            "state": state,
            "country": address.get("country") or "Nigeria",
            "country_code": country_code or "NG",
            "latitude": lat if lat is not None else float(latitude),
            "longitude": lon if lon is not None else float(longitude),
            "provenance": {"provider": "TomTom Search API", "service": "Reverse Geocoding", "country_scope": "Nigeria"},
        }

    async def reverse_geocode_nigeria(self, latitude: float, longitude: float) -> dict | None:
        """Resolve a click to a Nigerian road, with OSM fallback for unnamed TomTom results.

        TomTom remains the primary search provider. Nominatim is used only when the
        primary reverse result is absent/generic, which keeps public OSM requests low.
        """
        primary=None
        last_error: SearchUnavailable | None = None
        if self.configured:
            for attempt in range(1, self.retry_attempts + 1):
                try:
                    primary = await asyncio.to_thread(self._reverse_sync, latitude, longitude)
                    break
                except SearchUnavailable as exc:
                    exc.attempts = attempt
                    last_error = exc
                    if exc.retryable and attempt < self.retry_attempts:
                        await asyncio.sleep(self.retry_backoff_seconds * (2 ** (attempt - 1)))
                        continue
                    break
        if _road_result_is_specific(primary):
            return primary
        fallback = await asyncio.to_thread(_osm_reverse_cached, round(float(latitude), 6), round(float(longitude), 6))
        if fallback:
            if primary:
                # Retain any useful primary administrative/address fields while
                # letting the road-specific OSM result replace generic labels.
                for key in ("city", "state", "country"):
                    if not fallback.get(key) and primary.get(key): fallback[key]=primary[key]
                fallback["provenance"]["primary_attempt"]="TomTom Search API"
            return fallback
        if primary:
            return primary
        if last_error and not self.configured:
            raise last_error
        return None

    async def search_nigeria(self, query: str, limit: int = 10) -> list[dict]:
        q = (query or "").strip()
        if len(q) < 2:
            return []

        last_error: SearchUnavailable | None = None
        if self.configured:
            for attempt in range(1, self.retry_attempts + 1):
                try:
                    rows = await asyncio.to_thread(self._search_sync, q, limit)
                    if rows:
                        return rows
                except SearchUnavailable as exc:
                    exc.attempts = attempt
                    last_error = exc
                    if exc.retryable and attempt < self.retry_attempts:
                        await asyncio.sleep(self.retry_backoff_seconds * (2 ** (attempt - 1)))
                        continue
                    break

        try:
            rows = await asyncio.to_thread(_osm_search_sync, q, limit)
            if rows:
                return rows
        except Exception:
            pass

        if last_error:
            raise last_error
        raise SearchUnavailable(
            "No Nigeria search provider is currently available.",
            category="search_unavailable", retryable=True, attempts=self.retry_attempts
        )

def _haversine_m(lat1, lon1, lat2, lon2):
    r = 6371008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2-lat1)
    dlambda = math.radians(lon2-lon1)
    a = math.sin(dphi/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dlambda/2)**2
    return 2*r*math.asin(math.sqrt(a))

def nearest_iticas_history(latitude: float, longitude: float, max_distance_m: float = 2500.0):
    with SessionLocal() as db:
        locations = db.scalars(select(MonitoringLocation).where(
            MonitoringLocation.latitude.is_not(None),
            MonitoringLocation.longitude.is_not(None),
        )).all()
        best = None
        for loc in locations:
            d = _haversine_m(latitude, longitude, float(loc.latitude), float(loc.longitude))
            if d <= max_distance_m and (best is None or d < best[0]):
                best = (d, loc)
        if best is None:
            return None
        distance, loc = best
        row = db.scalar(select(TrafficObservation).where(
            TrafficObservation.location_id == loc.id
        ).order_by(TrafficObservation.observed_at.desc(), TrafficObservation.id.desc()))
        return {
            "location_id": loc.id,
            "location": loc.name,
            "city": loc.city,
            "state": loc.state,
            "distance_m": round(distance, 1),
            "latest_observation": None if not row else {
                "observed_at": row.observed_at.isoformat() if row.observed_at else None,
                "current_speed_kmh": row.current_speed_kmh,
                "free_flow_speed_kmh": row.free_flow_speed_kmh,
                "congestion_index": row.congestion_index,
                "delay_seconds": row.delay_seconds,
                "confidence": row.confidence,
                "provider": row.provider,
            },
        }

def _base_result(latitude: float, longitude: float, radius_m: int, label: str | None, observed_at: datetime, provider_name: str) -> dict:
    return {
        "scope": "Nigeria",
        "query_point": {"label": label, "latitude": float(latitude), "longitude": float(longitude), "radius_m": int(radius_m)},
        "evaluated_at": observed_at.isoformat(),
        "live_provider": provider_name,
        "iticas_history": nearest_iticas_history(float(latitude), float(longitude)),
        "provenance": {
            "live_traffic_provider": provider_name,
            "traffic_flow_service": "Flow Segment Data v4",
            "traffic_incident_service": "Incident Details v5",
            "stored_history_source": "ITICAS persistent monitoring database",
            "result_type": "on_demand_location_evaluation",
        },
    }

async def evaluate_traffic_point(latitude: float, longitude: float, radius_m: int = 1500, label: str | None = None,
                                 provider_factory=TomTomTrafficClient) -> dict:
    observed_at = datetime.now(timezone.utc)
    history = nearest_iticas_history(float(latitude), float(longitude))

    weather_context = None
    weather_diagnostic = None
    try:
        weather_context = await current_weather(latitude, longitude)
    except WeatherUnavailable as exc:
        weather_diagnostic = exc.as_dict()

    provider_attempts = []

    if broker_configured():
        try:
            broker = await broker_evaluate(latitude, longitude, radius_m)
            if broker.get("live_observation"):
                broker.setdefault("iticas_history", history)
                broker.setdefault("weather_context", weather_context)
                broker.setdefault("provider_diagnostics", {})
                broker["provider_diagnostics"].setdefault("weather", weather_diagnostic)
                return broker
            provider_attempts.extend((broker.get("provider_diagnostics") or {}).get("attempts") or [])
            if not provider_attempts:
                provider_attempts.append({
                    "provider": broker.get("provider") or "Central ITICAS Provider Broker",
                    "category": broker.get("status") or "broker_no_live_data",
                    "message": broker.get("message") or "Central broker returned no live traffic value.",
                })
        except BrokerUnavailable as exc:
            provider_attempts.append({"provider": "Central ITICAS Provider Broker", **exc.as_dict()})

    provider = provider_factory()
    if provider.configured:
        base = _base_result(latitude, longitude, radius_m, label, observed_at, provider.provider_name)
        try:
            flow_payload = await provider.fetch_flow(latitude, longitude)
            flow = provider.normalize_flow(flow_payload, observed_at=observed_at)
        except ProviderNotConfigured:
            flow = None
        except ProviderRequestError as exc:
            provider_attempts.append({"provider": provider.provider_name, **exc.as_dict()})
            flow = None

        if flow:
            incident_diagnostic = None
            try:
                incident_payload = await provider.fetch_incidents(latitude, longitude, radius_m)
                incidents = provider.normalize_incidents(incident_payload, observed_at=observed_at)
            except ProviderRequestError as exc:
                incidents = []
                incident_diagnostic = exc.as_dict()

            validation = {
                "validation_status": "insufficient_reference_data",
                "benchmark_source": "TomTom Traffic API free-flow reference",
                "benchmark_type": "established_provider_reference",
                "independence_level": "provider_reference",
                "independent_benchmark_configured": False,
                "reference_type": "free_flow_speed",
                "standard_alignment": "OGC SensorThings API / OGC Observations, Measurements and Samples metadata alignment",
                "limitations": "This on-demand evaluation compares live speed with the same provider's free-flow reference. It is not independent ground truth.",
            }
            if flow.get("current_speed_kmh") is not None and flow.get("free_flow_speed_kmh") not in (None, 0):
                observed = float(flow["current_speed_kmh"])
                reference = float(flow["free_flow_speed_kmh"])
                deviation = observed - reference
                validation.update({
                    "validation_status": "provider_reference_validated",
                    "observed_value": observed,
                    "reference_value": reference,
                    "deviation_value": round(deviation, 3),
                    "deviation_percent": round((deviation/reference)*100.0, 3),
                    "agreement_score": round(max(0.0, min(1.0, observed/reference)), 6),
                    "source_confidence": flow.get("confidence"),
                })
            return {
                **base,
                "status": "ok",
                "live_observation": flow,
                "fallback_observation": None,
                "incidents": incidents,
                "incident_count": len(incidents),
                "validation": validation,
                "provider_diagnostics": {
                    "attempts": provider_attempts,
                    "incidents": incident_diagnostic,
                    "weather": weather_diagnostic,
                },
                "weather_context": weather_context,
            }

    latest = (history or {}).get("latest_observation") if history else None
    categories = [str(x.get("category") or "") for x in provider_attempts]
    if "provider_credit_exhausted" in categories:
        status = "live_provider_credit_exhausted"
        reason = "Live traffic is unavailable because the configured provider quota/credits are exhausted."
    elif any("network" in c for c in categories):
        status = "live_provider_network_unavailable"
        reason = "Live traffic providers could not be reached because of network/DNS connectivity."
    elif provider_attempts:
        status = "live_provider_unavailable"
        reason = "No configured live traffic provider returned a usable live observation."
    else:
        status = "live_provider_not_configured"
        reason = "No live traffic provider is configured for this client."

    return {
        "scope": "Nigeria",
        "query_point": {"label": label, "latitude": float(latitude), "longitude": float(longitude), "radius_m": int(radius_m)},
        "evaluated_at": observed_at.isoformat(),
        "status": status,
        "live_provider": None,
        "live_observation": None,
        "fallback_observation": latest,
        "fallback_type": "stored_iticas_history" if latest else None,
        "incidents": [],
        "incident_count": 0,
        "iticas_history": history,
        "validation": {
            "validation_status": "not_validated_live_provider_unavailable",
            "benchmark_source": None,
            "benchmark_type": None,
            "independence_level": "historical_reference_only" if latest else "unavailable",
            "independent_benchmark_configured": False,
            "reference_type": "stored historical observation" if latest else None,
            "standard_alignment": "OGC SensorThings API / OGC Observations, Measurements and Samples metadata alignment",
            "limitations": reason + (" Stored ITICAS history is shown separately and is not substituted for live traffic." if latest else ""),
        },
        "provider_diagnostics": {"attempts": provider_attempts, "weather": weather_diagnostic},
        "weather_context": weather_context,
        "provenance": {
            "live_traffic_provider": None,
            "stored_history_source": "ITICAS persistent monitoring database" if latest else None,
            "result_type": "on_demand_location_evaluation",
            "live_vs_historical_separation": True,
        },
        "message": reason,
    }

