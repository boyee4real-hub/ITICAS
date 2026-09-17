from __future__ import annotations
import asyncio, json
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from .config import settings

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

class WeatherUnavailable(RuntimeError):
    def __init__(self, message:str, category:str="weather_unavailable", retryable:bool=False, status_code:int|None=None):
        super().__init__(message); self.category=category; self.retryable=retryable; self.status_code=status_code
    def as_dict(self):
        return {"category":self.category,"message":str(self),"retryable":self.retryable,"status_code":self.status_code}

def _request_json(url:str, params:dict, timeout:float):
    req=Request(f"{url}?{urlencode(params)}",headers={"Accept":"application/json","User-Agent":f"ITICAS/{settings.version}"})
    try:
        with urlopen(req,timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except HTTPError as exc:
        raise WeatherUnavailable(f"Weather provider HTTP {exc.code}.","weather_http_error",exc.code in {429,500,502,503,504},exc.code) from exc
    except (URLError,OSError) as exc:
        text=str(exc).lower()
        cat="weather_dns_failure" if "name or service" in text or "getaddrinfo" in text else "weather_network_failure"
        raise WeatherUnavailable("Weather provider could not be reached.",cat,True) from exc
    except Exception as exc:
        raise WeatherUnavailable("Weather provider returned an invalid response.","weather_response_error",False) from exc

async def current_weather(latitude:float, longitude:float):
    if not settings.weather_enabled:
        raise WeatherUnavailable("Weather integration is disabled.","weather_disabled",False)
    params={
        "latitude":round(float(latitude),6),"longitude":round(float(longitude),6),
        "current":"temperature_2m,relative_humidity_2m,precipitation,rain,weather_code,wind_speed_10m,wind_direction_10m",
        "timezone":"auto","temperature_unit":"celsius","wind_speed_unit":"kmh","precipitation_unit":"mm"
    }
    data=await asyncio.to_thread(_request_json,FORECAST_URL,params,float(settings.weather_timeout_seconds))
    cur=data.get("current") or {}
    return {
        "status":"ok","provider":"Open-Meteo Forecast API","source_type":"multi-model operational weather",
        "latitude":data.get("latitude",latitude),"longitude":data.get("longitude",longitude),"timezone":data.get("timezone"),
        "observed_at":cur.get("time"),"temperature_c":cur.get("temperature_2m"),"humidity_pct":cur.get("relative_humidity_2m"),
        "precipitation_mm":cur.get("precipitation"),"rain_mm":cur.get("rain"),"weather_code":cur.get("weather_code"),
        "wind_speed_kmh":cur.get("wind_speed_10m"),"wind_direction_deg":cur.get("wind_direction_10m"),
        "provenance":{"provider":"Open-Meteo","service":"Forecast API","purpose":"traffic-weather context","independent_of_traffic_provider":True}
    }

async def era5_land_reference(latitude:float, longitude:float, days_ago:int=7):
    # ERA5-Land is typically delayed several days; use a date safely behind real time.
    day=(datetime.now(timezone.utc)-timedelta(days=max(7,int(days_ago)))).date().isoformat()
    params={
        "latitude":round(float(latitude),6),"longitude":round(float(longitude),6),"start_date":day,"end_date":day,
        "hourly":"temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m","models":"era5_land","timezone":"auto"
    }
    data=await asyncio.to_thread(_request_json,ARCHIVE_URL,params,float(settings.weather_timeout_seconds))
    hourly=data.get("hourly") or {}
    def mean(name):
        vals=[float(v) for v in (hourly.get(name) or []) if v is not None]
        return round(sum(vals)/len(vals),3) if vals else None
    return {
        "status":"ok","reference_dataset":"ERA5-Land reanalysis","reference_date":day,
        "spatial_resolution":"0.1 degree (~9-11 km)","temporal_resolution":"hourly",
        "mean_temperature_c":mean("temperature_2m"),"mean_humidity_pct":mean("relative_humidity_2m"),
        "total_precipitation_mm":round(sum(float(v) for v in (hourly.get("precipitation") or []) if v is not None),3) if hourly.get("precipitation") else None,
        "mean_wind_speed_kmh":mean("wind_speed_10m"),
        "provenance":{"dataset":"ERA5-Land","access":"Open-Meteo Historical Weather API","purpose":"standardized environmental reference context","traffic_ground_truth":False}
    }


async def hourly_weather_forecast(latitude: float, longitude: float, start: datetime, end: datetime):
    """Retrieve hourly operational weather for a future traffic-forecast window.

    This is contextual evidence. It does not itself constitute traffic ground truth.
    """
    if not settings.weather_enabled:
        raise WeatherUnavailable("Weather integration is disabled.", "weather_disabled", False)
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    else:
        start = start.astimezone(timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    else:
        end = end.astimezone(timezone.utc)
    params = {
        "latitude": round(float(latitude), 6),
        "longitude": round(float(longitude), 6),
        "start_date": start.date().isoformat(),
        "end_date": end.date().isoformat(),
        "hourly": "temperature_2m,relative_humidity_2m,precipitation,rain,weather_code,wind_speed_10m",
        "timezone": "UTC",
        "temperature_unit": "celsius",
        "wind_speed_unit": "kmh",
        "precipitation_unit": "mm",
    }
    data = await asyncio.to_thread(_request_json, FORECAST_URL, params, float(settings.weather_timeout_seconds))
    h = data.get("hourly") or {}
    times = h.get("time") or []
    rows = []
    for i, stamp in enumerate(times):
        try:
            dt = datetime.fromisoformat(str(stamp)).replace(tzinfo=timezone.utc)
        except Exception:
            continue
        if dt < start - timedelta(hours=1) or dt > end + timedelta(hours=1):
            continue
        def at(name):
            vals = h.get(name) or []
            return vals[i] if i < len(vals) else None
        rows.append({
            "time_utc": dt.isoformat(),
            "temperature_c": at("temperature_2m"),
            "humidity_pct": at("relative_humidity_2m"),
            "precipitation_mm": at("precipitation"),
            "rain_mm": at("rain"),
            "weather_code": at("weather_code"),
            "condition": weather_code_label(at("weather_code")),
            "wind_speed_kmh": at("wind_speed_10m"),
        })
    return {
        "status": "ok",
        "provider": "Open-Meteo Forecast API",
        "source_type": "operational weather forecast",
        "latitude": data.get("latitude", latitude),
        "longitude": data.get("longitude", longitude),
        "timezone": "UTC",
        "hourly": rows,
        "provenance": {
            "provider": "Open-Meteo",
            "service": "Forecast API",
            "purpose": "future traffic-prediction context",
            "traffic_ground_truth": False,
        },
    }

async def hourly_weather_history(latitude: float, longitude: float, start: datetime, end: datetime):
    """Retrieve hourly historical weather for empirical traffic-context calibration."""
    if not settings.weather_enabled:
        raise WeatherUnavailable("Weather integration is disabled.", "weather_disabled", False)
    if start.tzinfo is None: start=start.replace(tzinfo=timezone.utc)
    else: start=start.astimezone(timezone.utc)
    if end.tzinfo is None: end=end.replace(tzinfo=timezone.utc)
    else: end=end.astimezone(timezone.utc)
    params={
        "latitude":round(float(latitude),6),"longitude":round(float(longitude),6),
        "start_date":start.date().isoformat(),"end_date":end.date().isoformat(),
        "hourly":"temperature_2m,relative_humidity_2m,precipitation,rain,wind_speed_10m",
        "timezone":"UTC","temperature_unit":"celsius","wind_speed_unit":"kmh","precipitation_unit":"mm",
    }
    data=await asyncio.to_thread(_request_json,ARCHIVE_URL,params,float(settings.weather_timeout_seconds))
    h=data.get("hourly") or {}; times=h.get("time") or []; rows=[]
    for i,stamp in enumerate(times):
        try: dt=datetime.fromisoformat(str(stamp)).replace(tzinfo=timezone.utc)
        except Exception: continue
        if dt < start-timedelta(hours=1) or dt > end+timedelta(hours=1): continue
        def at(name):
            vals=h.get(name) or []; return vals[i] if i<len(vals) else None
        rows.append({"time_utc":dt.isoformat(),"temperature_c":at("temperature_2m"),"humidity_pct":at("relative_humidity_2m"),"precipitation_mm":at("precipitation"),"rain_mm":at("rain"),"wind_speed_kmh":at("wind_speed_10m")})
    return {"status":"ok","provider":"Open-Meteo Historical Weather API","hourly":rows,"provenance":{"purpose":"road-specific traffic-weather calibration","traffic_ground_truth":False}}


WEATHER_CODE_LABELS = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Depositing rime fog", 51: "Light drizzle", 53: "Moderate drizzle",
    55: "Dense drizzle", 56: "Light freezing drizzle", 57: "Dense freezing drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain", 66: "Light freezing rain",
    67: "Heavy freezing rain", 71: "Slight snowfall", 73: "Moderate snowfall", 75: "Heavy snowfall",
    77: "Snow grains", 80: "Slight rain showers", 81: "Moderate rain showers", 82: "Violent rain showers",
    85: "Slight snow showers", 86: "Heavy snow showers", 95: "Thunderstorm",
    96: "Thunderstorm with slight hail", 99: "Thunderstorm with heavy hail",
}

def weather_code_label(code):
    try: return WEATHER_CODE_LABELS.get(int(code), f"WMO code {int(code)}")
    except Exception: return "Unknown"

def _at(block, name, i):
    vals=(block or {}).get(name) or []
    return vals[i] if i < len(vals) else None

def _weather_advisory(*, precipitation=None, precip_probability=None, visibility=None, gust=None, code=None):
    reasons=[]
    try:
        if precipitation is not None and float(precipitation) >= 7.5: reasons.append("heavy precipitation")
        elif precipitation is not None and float(precipitation) > 0: reasons.append("wet road conditions possible")
    except Exception: pass
    try:
        if precip_probability is not None and float(precip_probability) >= 70: reasons.append("high precipitation probability")
    except Exception: pass
    try:
        if visibility is not None and float(visibility) < 3000: reasons.append("reduced visibility")
    except Exception: pass
    try:
        if gust is not None and float(gust) >= 50: reasons.append("strong wind gusts")
    except Exception: pass
    try:
        if int(code) in {95,96,99}: reasons.append("thunderstorm")
    except Exception: pass
    level="elevated" if reasons else "normal"
    return {"level":level,"reasons":reasons,"traffic_effect":"advisory_only_unless_empirically_calibrated"}

async def weather_intelligence_forecast(latitude: float, longitude: float, days: int = 7):
    """Current + hourly + daily weather intelligence for a Nigerian traffic location.

    Weather is contextual evidence. It does not automatically modify traffic forecasts;
    Stage 26's road-specific empirical calibration gate remains authoritative.
    """
    if not settings.weather_enabled:
        raise WeatherUnavailable("Weather integration is disabled.", "weather_disabled", False)
    days=max(1,min(int(days),7))
    params={
        "latitude":round(float(latitude),6), "longitude":round(float(longitude),6),
        "current":"temperature_2m,relative_humidity_2m,apparent_temperature,is_day,precipitation,rain,showers,snowfall,weather_code,cloud_cover,pressure_msl,surface_pressure,wind_speed_10m,wind_direction_10m,wind_gusts_10m",
        "hourly":"temperature_2m,relative_humidity_2m,apparent_temperature,precipitation_probability,precipitation,rain,weather_code,cloud_cover,visibility,wind_speed_10m,wind_direction_10m,wind_gusts_10m",
        "daily":"weather_code,temperature_2m_max,temperature_2m_min,apparent_temperature_max,apparent_temperature_min,sunrise,sunset,precipitation_sum,rain_sum,precipitation_hours,precipitation_probability_max,wind_speed_10m_max,wind_gusts_10m_max,wind_direction_10m_dominant",
        "forecast_days":days, "timezone":"auto", "temperature_unit":"celsius", "wind_speed_unit":"kmh", "precipitation_unit":"mm",
    }
    data=await asyncio.to_thread(_request_json,FORECAST_URL,params,float(settings.weather_timeout_seconds))
    cur=data.get("current") or {}; h=data.get("hourly") or {}; d=data.get("daily") or {}
    current={
        "time":cur.get("time"), "temperature_c":cur.get("temperature_2m"), "apparent_temperature_c":cur.get("apparent_temperature"),
        "humidity_pct":cur.get("relative_humidity_2m"), "precipitation_mm":cur.get("precipitation"), "rain_mm":cur.get("rain"),
        "showers_mm":cur.get("showers"), "snowfall_cm":cur.get("snowfall"), "weather_code":cur.get("weather_code"),
        "condition":weather_code_label(cur.get("weather_code")), "cloud_cover_pct":cur.get("cloud_cover"), "pressure_msl_hpa":cur.get("pressure_msl"),
        "surface_pressure_hpa":cur.get("surface_pressure"), "wind_speed_kmh":cur.get("wind_speed_10m"),
        "wind_direction_deg":cur.get("wind_direction_10m"), "wind_gusts_kmh":cur.get("wind_gusts_10m"), "is_day":cur.get("is_day"),
    }
    current["advisory"]=_weather_advisory(precipitation=current["precipitation_mm"],gust=current["wind_gusts_kmh"],code=current["weather_code"])
    hourly=[]
    for i,t in enumerate(h.get("time") or []):
        row={
            "time":t, "temperature_c":_at(h,"temperature_2m",i), "apparent_temperature_c":_at(h,"apparent_temperature",i),
            "humidity_pct":_at(h,"relative_humidity_2m",i), "precipitation_probability_pct":_at(h,"precipitation_probability",i),
            "precipitation_mm":_at(h,"precipitation",i), "rain_mm":_at(h,"rain",i), "weather_code":_at(h,"weather_code",i),
            "cloud_cover_pct":_at(h,"cloud_cover",i), "visibility_m":_at(h,"visibility",i), "wind_speed_kmh":_at(h,"wind_speed_10m",i),
            "wind_direction_deg":_at(h,"wind_direction_10m",i), "wind_gusts_kmh":_at(h,"wind_gusts_10m",i),
        }
        row["condition"]=weather_code_label(row["weather_code"])
        row["advisory"]=_weather_advisory(precipitation=row["precipitation_mm"],precip_probability=row["precipitation_probability_pct"],visibility=row["visibility_m"],gust=row["wind_gusts_kmh"],code=row["weather_code"])
        hourly.append(row)
    daily=[]
    for i,t in enumerate(d.get("time") or []):
        row={
            "date":t, "weather_code":_at(d,"weather_code",i), "temp_max_c":_at(d,"temperature_2m_max",i), "temp_min_c":_at(d,"temperature_2m_min",i),
            "apparent_max_c":_at(d,"apparent_temperature_max",i), "apparent_min_c":_at(d,"apparent_temperature_min",i),
            "sunrise":_at(d,"sunrise",i), "sunset":_at(d,"sunset",i), "precipitation_sum_mm":_at(d,"precipitation_sum",i),
            "rain_sum_mm":_at(d,"rain_sum",i), "precipitation_hours":_at(d,"precipitation_hours",i),
            "precipitation_probability_max_pct":_at(d,"precipitation_probability_max",i), "wind_speed_max_kmh":_at(d,"wind_speed_10m_max",i),
            "wind_gusts_max_kmh":_at(d,"wind_gusts_10m_max",i), "wind_direction_dominant_deg":_at(d,"wind_direction_10m_dominant",i),
        }
        row["condition"]=weather_code_label(row["weather_code"])
        row["advisory"]=_weather_advisory(precipitation=row["precipitation_sum_mm"],precip_probability=row["precipitation_probability_max_pct"],gust=row["wind_gusts_max_kmh"],code=row["weather_code"])
        daily.append(row)
    return {
        "status":"ok", "provider":"Open-Meteo Forecast API", "source_type":"operational weather forecast",
        "requested_latitude":float(latitude), "requested_longitude":float(longitude), "latitude":data.get("latitude",latitude), "longitude":data.get("longitude",longitude),
        "elevation_m":data.get("elevation"), "timezone":data.get("timezone"), "timezone_abbreviation":data.get("timezone_abbreviation"),
        "forecast_days":days, "current":current, "hourly":hourly, "daily":daily,
        "scientific_boundary":"Weather hazards are shown as contextual/advisory evidence. Weather may alter ITICAS traffic forecasts only when a road-specific effect passes the empirical holdout-validation gate.",
        "provenance":{"provider":"Open-Meteo","service":"Forecast API","coordinates":"WGS84","purpose":"traffic-weather intelligence","traffic_ground_truth":False},
    }

async def weather_history_summary(latitude: float, longitude: float, days: int = 30):
    """Recent historical weather summary for traffic research context."""
    if not settings.weather_enabled:
        raise WeatherUnavailable("Weather integration is disabled.", "weather_disabled", False)
    days=max(1,min(int(days),90)); end=(datetime.now(timezone.utc)-timedelta(days=1)).date(); start=end-timedelta(days=days-1)
    params={
        "latitude":round(float(latitude),6),"longitude":round(float(longitude),6),"start_date":start.isoformat(),"end_date":end.isoformat(),
        "daily":"weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,rain_sum,precipitation_hours,wind_speed_10m_max,wind_gusts_10m_max",
        "timezone":"auto","temperature_unit":"celsius","wind_speed_unit":"kmh","precipitation_unit":"mm",
    }
    data=await asyncio.to_thread(_request_json,ARCHIVE_URL,params,float(settings.weather_timeout_seconds)); d=data.get("daily") or {}; rows=[]
    for i,t in enumerate(d.get("time") or []):
        rows.append({"date":t,"condition":weather_code_label(_at(d,"weather_code",i)),"weather_code":_at(d,"weather_code",i),"temp_max_c":_at(d,"temperature_2m_max",i),"temp_min_c":_at(d,"temperature_2m_min",i),"precipitation_sum_mm":_at(d,"precipitation_sum",i),"rain_sum_mm":_at(d,"rain_sum",i),"precipitation_hours":_at(d,"precipitation_hours",i),"wind_speed_max_kmh":_at(d,"wind_speed_10m_max",i),"wind_gusts_max_kmh":_at(d,"wind_gusts_10m_max",i)})
    rain_days=sum(1 for r in rows if float(r.get("rain_sum_mm") or 0)>0)
    wet=sum(float(r.get("precipitation_sum_mm") or 0) for r in rows)
    return {"status":"ok","provider":"Open-Meteo Historical Weather API","start_date":start.isoformat(),"end_date":end.isoformat(),"timezone":data.get("timezone"),"summary":{"days":len(rows),"rain_days":rain_days,"total_precipitation_mm":round(wet,2)},"daily":rows,"provenance":{"provider":"Open-Meteo","service":"Historical Weather API","purpose":"research weather context","traffic_ground_truth":False}}
