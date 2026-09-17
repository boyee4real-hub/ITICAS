from contextlib import asynccontextmanager
import asyncio
from datetime import datetime, timezone, timedelta
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func, and_

from .config import settings
from .paths import ASSET_ROOT
from .database import (
    init_database, SessionLocal, MonitoringLocation, TrafficObservation, MonitoringRun,
    User, UserPermission, AuditLog, BenchmarkSource, HistoricalBackfillJob, HistoricalTrafficSample, ResearchSurveySession, GNSSTrackPoint, CorridorProbe, CorridorProbeObservation, ArchiveServiceState
)
from .schemas import LocationCreate, LocationUpdate, TrafficPointEvaluationRequest, LocationFromSearch, ResearchSurveyCreate, GNSSTrackPointCreate
from .tomtom_traffic import TomTomTrafficClient
from .traffic_service import acquire_location_traffic_data, LocationNotFound, MissingCoordinates, ProviderUnavailable
from .monitoring import monitoring_manager
from .central_access import gateway_configured, submit_access_request, central_login, sync_central_user
from .security import (
    current_user_optional, require_permission, authenticate, create_session, revoke_session,
    check_login_rate_limit, clear_login_rate_limit, audit, hash_password, permissions_for, ALL_PERMISSIONS
)
from .validation import ensure_benchmark_sources, validation_payload
from .search_service import TomTomSearchClient, SearchUnavailable, evaluate_traffic_point
from .weather_service import current_weather, era5_land_reference, weather_intelligence_forecast, weather_history_summary, WeatherUnavailable
from .diagnostics import provider_readiness
from .analytics import analyze_location, network_summary
from .reporting import export_bytes, FORMATS
from .historical_traffic import submit_backfill, refresh_job, list_jobs, coverage as historical_coverage, HistoricalTrafficUnavailable, configured as historical_configured, auto_refresh_loop, refresh_pending_jobs_once
from .spatial_intelligence import spatial_summary
from .map_proxy import tile as map_tile, MapTileUnavailable
from .static_map import render_static_map
from .research_engine import research_catalog, objective_matrix, survey_summary, ensure_corridor_probes, build_research_package, build_individual_tool_output
from .research_quality import gnss_quality
from .corridor_intelligence import acquire_corridor_probe_evidence, corridor_analysis, workflow_status
from .archive_collector import status_payload as archive_status_payload
from .supabase_archive import configured as supabase_archive_configured, sync_location_to_cloud, sync_all_to_cloud, cloud_status, cloud_coverage_for_location, import_cloud_history
from .archive_intelligence import archive_overview, archive_failures, location_research_readiness, archive_research_csv
from .prediction_engine import forecast_location, prediction_history
from .prediction_reporting import prediction_decision_package
from .prediction_context import collect_prediction_context
from .prediction_calibration import calibrate_context_effects, latest_context_calibration
from .prediction_monitoring import prediction_verification

FRONTEND = ASSET_ROOT / "frontend"

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_database()
    ensure_benchmark_sources()
    if supabase_archive_configured():
        try:
            await sync_all_to_cloud()
        except Exception:
            pass
    if settings.embedded_monitoring_enabled:
        await monitoring_manager.start()
    historical_stop = asyncio.Event()
    historical_task = asyncio.create_task(auto_refresh_loop(historical_stop))
    yield
    historical_stop.set()
    try:
        await historical_task
    except Exception:
        pass
    if settings.embedded_monitoring_enabled:
        await monitoring_manager.stop()

app = FastAPI(
    title=settings.app_name,
    version=settings.version,
    description="Nationwide traffic monitoring, validated congestion intelligence and prediction platform for Nigeria.",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=str(FRONTEND / "static")), name="static")
@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="14" fill="#4dd4ff"/><text x="32" y="42" text-anchor="middle" font-family="Arial,sans-serif" font-size="30" font-weight="700" fill="#08111f">IT</text></svg>'
    return Response(content=svg, media_type="image/svg+xml", headers={"Cache-Control":"public, max-age=86400"})

templates = Jinja2Templates(directory=str(FRONTEND / "templates"))
templates.env.globals["developer_credit"] = settings.developer_credit

def context(request: Request, **extra):
    user = current_user_optional(request)
    return {
        "request": request, "app_name": settings.app_name, "short_name": settings.app_short_name,
        "developer_name": settings.developer_name, "developer_credit": settings.developer_credit, "stage": settings.stage, "version": settings.version,
        "current_user": user, **extra
    }

def html_auth(request: Request):
    user = current_user_optional(request)
    if not user:
        return None, RedirectResponse("/login", status_code=303)
    return user, None

def clean_text(value): return value.strip() if isinstance(value, str) else value

def serialize_location(x):
    return {"id":x.id,"name":x.name,"road_name":x.road_name,"city":x.city,"state":x.state,"country":x.country,
            "latitude":x.latitude,"longitude":x.longitude,"radius_m":x.radius_m,"active":bool(x.active),
            "geocode_source":x.geocode_source,"geocode_query":x.geocode_query,
            "geocoded_at":x.geocoded_at.isoformat() if x.geocoded_at else None}

def find_duplicate(db,name,city,state,exclude_id=None):
    clauses=[func.lower(MonitoringLocation.name)==name.strip().lower(),func.lower(MonitoringLocation.state)==state.strip().lower()]
    clauses.append(func.lower(MonitoringLocation.city)==city.strip().lower() if city else MonitoringLocation.city.is_(None))
    if exclude_id is not None: clauses.append(MonitoringLocation.id != exclude_id)
    return db.scalar(select(MonitoringLocation).where(and_(*clauses)))

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if current_user_optional(request): return RedirectResponse("/",303)
    return templates.TemplateResponse(request,"login.html", context(request))

@app.post("/login")
async def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    check_login_rate_limit(request)
    if gateway_configured():
        try: profile=await central_login(username,password)
        except RuntimeError:
            return templates.TemplateResponse(request,"login.html",context(request,error="ITICAS central access service is temporarily unavailable. Please try again shortly."),status_code=503)
        if not profile:
            return templates.TemplateResponse(request,"login.html",context(request,error="Invalid credentials or account is not yet approved."),status_code=401)
        user=sync_central_user(profile,password)
    else:
        user=authenticate(username,password)
        if not user:
            return templates.TemplateResponse(request,"login.html",context(request,error="Invalid credentials, account pending, disabled, or temporarily locked."),status_code=401)
    clear_login_rate_limit(request)
    raw=create_session(user,request)
    response=RedirectResponse("/",303)
    response.set_cookie(settings.security_cookie_name,raw,httponly=True,secure=settings.security_cookie_secure,samesite="strict",max_age=settings.security_session_hours*3600,path="/")
    return response

@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse(request,"register.html", context(request))

@app.post("/register")
async def register_submit(request:Request,full_name:str=Form(...),username:str=Form(...),email:str=Form(...),organisation:str=Form(""),phone:str=Form(""),intended_use:str=Form(...),password:str=Form(...),confirm_password:str=Form(...)):
    if password!=confirm_password:
        return templates.TemplateResponse(request,"register.html",context(request,error="Passwords do not match."),status_code=400)
    if not gateway_configured():
        return templates.TemplateResponse(request,"register.html",context(request,error="Central ITICAS access service is not yet activated on this build."),status_code=503)
    try:
        result=await submit_access_request({"full_name":full_name.strip(),"username":username.strip(),"email":email.strip().lower(),"organisation":organisation.strip(),"phone":phone.strip(),"intended_use":intended_use.strip(),"password":password})
    except RuntimeError as exc:
        return templates.TemplateResponse(request,"register.html",context(request,error=str(exc)),status_code=502)
    return templates.TemplateResponse(request,"register.html",context(request,success=result.get("message") or "Access request submitted."))

@app.post("/logout")
async def logout(request:Request):
    user=current_user_optional(request)
    revoke_session(request.cookies.get(settings.security_cookie_name))
    if user: audit("auth.logout",request,user_id=user.id)
    response=RedirectResponse("/login",303); response.delete_cookie(settings.security_cookie_name,path="/"); return response

@app.get("/", response_class=HTMLResponse)
async def dashboard(request:Request):
    user,redirect=html_auth(request)
    if redirect:return redirect
    return templates.TemplateResponse(request,"index.html",context(request))

@app.get("/locations", response_class=HTMLResponse)
async def locations_page(request:Request):
    user,redirect=html_auth(request)
    if redirect:return redirect
    return templates.TemplateResponse(request,"locations.html",context(request))


@app.get("/archive", response_class=HTMLResponse)
async def archive_page(request:Request):
    user,redirect=html_auth(request)
    if redirect:return redirect
    return templates.TemplateResponse(request,"archive.html",context(request))

@app.get("/api/archive/status")
async def archive_status(request:Request):
    require_permission(request,"monitoring:view")
    local=archive_status_payload()
    try: cloud=await cloud_status()
    except Exception as exc: cloud={"configured":supabase_archive_configured(),"error":str(exc)}
    return {**local,"local":local,"cloud":cloud}


@app.post("/api/archive/cloud-import/{location_id}")
async def archive_cloud_import(location_id:int,request:Request,days:int=30):
    actor=require_permission(request,"analytics:view")
    try:result=await import_cloud_history(location_id,max(1,min(int(days),3660)))
    except Exception as exc:raise HTTPException(502,str(exc))
    audit("archive.cloud_import",request,actor.id,"location",str(location_id),details=result)
    return result

@app.get("/api/archive/intelligence/overview")
async def archive_intelligence_overview(request:Request):
    require_permission(request,"monitoring:view")
    try:return await archive_overview()
    except Exception as exc:raise HTTPException(502,str(exc))

@app.get("/api/archive/intelligence/failures")
async def archive_intelligence_failures(request:Request,limit:int=100):
    require_permission(request,"monitoring:view")
    try:return await archive_failures(limit)
    except Exception as exc:raise HTTPException(502,str(exc))

@app.get("/api/archive/intelligence/readiness/{location_id}")
async def archive_intelligence_readiness(location_id:int,request:Request,days:int=30):
    require_permission(request,"analytics:view")
    try:return await location_research_readiness(location_id,days)
    except KeyError:raise HTTPException(404,"Location not found.")
    except Exception as exc:raise HTTPException(502,str(exc))

@app.get("/api/archive/intelligence/export/{location_id}")
async def archive_intelligence_export(location_id:int,request:Request,days:int=30):
    actor=require_permission(request,"reports:export")
    try:name,data=await archive_research_csv(location_id,days)
    except KeyError:raise HTTPException(404,"Location not found.")
    except Exception as exc:raise HTTPException(502,str(exc))
    audit("archive.research_export",request,actor.id,"location",str(location_id),details={"days":days,"filename":name,"source":"Supabase autonomous archive"})
    return Response(content=data,media_type="text/csv; charset=utf-8",headers={"Content-Disposition":f'attachment; filename="{name}"',"X-ITICAS-Provenance":"Supabase autonomous archive / TomTom Traffic API"})

@app.post("/api/archive/cloud-sync")
async def archive_cloud_sync(request:Request):
    actor=require_permission(request,"monitoring:manage")
    try: result=await sync_all_to_cloud()
    except Exception as exc: raise HTTPException(502,str(exc))
    audit("archive.cloud_sync",request,actor.id,"archive","supabase",details={"targets":result.get("targets"),"locations":result.get("locations")})
    return result

@app.get("/api/archive/cloud-coverage/{location_id}")
async def archive_cloud_coverage(location_id:int,request:Request,days:int=30):
    require_permission(request,"analytics:view")
    try:return await cloud_coverage_for_location(location_id,max(1,min(int(days),3660)))
    except Exception as exc:raise HTTPException(502,str(exc))

@app.get("/monitoring", response_class=HTMLResponse)
async def monitoring_page(request:Request):
    user,redirect=html_auth(request)
    if redirect:return redirect
    return templates.TemplateResponse(request,"monitoring.html",context(request))

@app.get("/map", response_class=HTMLResponse)
async def live_map_page(request: Request):
    user, redirect = html_auth(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(
        request,
        "map.html",
        context(
            request,
            map_default_latitude=settings.map_default_latitude,
            map_default_longitude=settings.map_default_longitude,
            map_default_zoom=settings.map_default_zoom,
            map_primary_style_url=settings.map_primary_style_url,
            map_fallback_tile_url=settings.map_fallback_tile_url,
            map_fallback_tile_attribution=settings.map_fallback_tile_attribution,
            map_evaluation_radius_m=settings.map_evaluation_radius_m,
        ),
    )

@app.get("/weather", response_class=HTMLResponse)
async def weather_page(request: Request):
    user, redirect = html_auth(request)
    if redirect: return redirect
    try: require_permission(request, "traffic:view")
    except HTTPException: return RedirectResponse("/", 303)
    return templates.TemplateResponse(request, "weather.html", context(request))

@app.get("/analytics", response_class=HTMLResponse)
async def analytics_page(request: Request):
    user, redirect = html_auth(request)
    if redirect: return redirect
    try: require_permission(request,"analytics:view")
    except HTTPException: return RedirectResponse("/",303)
    return templates.TemplateResponse(request,"analytics.html",context(request))

@app.get("/reports", response_class=HTMLResponse)
async def reports_page(request: Request):
    user, redirect = html_auth(request)
    if redirect: return redirect
    try: require_permission(request,"reports:view")
    except HTTPException: return RedirectResponse("/",303)
    return templates.TemplateResponse(request,"reports.html",context(request))


@app.get("/research", response_class=HTMLResponse)
async def research_page(request: Request):
    user, redirect=html_auth(request)
    if redirect:return redirect
    return templates.TemplateResponse(request,"research.html",context(request))

@app.get("/predictions", response_class=HTMLResponse)
async def predictions_page(request: Request):
    user, redirect = html_auth(request)
    if redirect:
        return redirect
    try:
        require_permission(request, "prediction:run")
    except HTTPException:
        return RedirectResponse("/", 303)
    return templates.TemplateResponse(request, "predictions.html", context(request))

@app.get("/historical", response_class=HTMLResponse)
async def historical_page(request: Request):
    user, redirect = html_auth(request)
    if redirect: return redirect
    try: require_permission(request,"analytics:view")
    except HTTPException: return RedirectResponse("/",303)
    return templates.TemplateResponse(request,"historical.html",context(request))

@app.get("/spatial", response_class=HTMLResponse)
async def spatial_page(request: Request):
    user, redirect = html_auth(request)
    if redirect: return redirect
    try: require_permission(request,"analytics:view")
    except HTTPException: return RedirectResponse("/",303)
    return templates.TemplateResponse(request,"spatial.html",context(request))

@app.get("/diagnostics", response_class=HTMLResponse)
async def diagnostics_page(request: Request):
    user, redirect = html_auth(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(request, "diagnostics.html", context(request))

@app.get("/admin/security", response_class=HTMLResponse)
async def security_page(request:Request):
    try: user=require_permission(request,"admin:security")
    except HTTPException: return RedirectResponse("/",303)
    return templates.TemplateResponse(request,"security.html",context(request))

@app.get("/api/health")
async def health():
    return {"status":"ok","application":settings.app_short_name,"application_name":settings.app_name,"stage":settings.stage,"version":settings.version,"scope":"Nigeria","database":"SQLite persistent store","security":"authentication_required","deployment_modes":["web","windows_exe"],"timestamp_utc":datetime.now(timezone.utc).isoformat(),"capabilities":["Nationwide monitoring","Search any Nigerian road, junction, town, city, LGA, state, landmark or coordinates","On-demand traffic evaluation beyond preconfigured monitoring points","Interactive Nigeria live map","Resilient map tile diagnostics","TomTom live traffic","Provider retry/backoff and failure classification","Automatic scheduler","Validation and benchmark registry","Provider-reference validation with explicit independence status","Authentication","Role and granular module permissions","Approval workflow","Audit logging","Standalone Windows EXE build path","Arbitrary-horizon predictive traffic intelligence","Congestion intelligence and statistical analytics","Temporal traffic profiles","Nationwide network congestion ranking","Publication-ready CSV/XLSX/DOCX/PDF/SVG/PNG exports","Research ZIP export package","Historical traffic backfill jobs","Interactive server-rendered cache-backed basemap with TomTom/OSM fallback","Spatial hotspot intelligence","Congestion-weighted kernel exposure","Decision-priority analytics","Standalone current weather intelligence","Hourly and 7-day weather forecast","Historical weather research context","Traffic-weather advisory context with empirical calibration boundary"]}

@app.get("/api/security/status")
async def security_status():
    with SessionLocal() as db:
        users=db.scalar(select(func.count()).select_from(User)) or 0
        admins=db.scalar(select(func.count()).select_from(User).where(User.role=="admin",User.status=="approved")) or 0
    return {"authentication_required":True,"password_hashing":"scrypt","session":"server-side opaque token","cookie":{"http_only":True,"same_site":"strict","secure":bool(settings.security_cookie_secure)},"login_rate_limit":{"attempts":settings.security_login_max_attempts,"window_seconds":settings.security_login_window_seconds},"users":users,"approved_admins":admins,"granular_permissions":list(ALL_PERMISSIONS),"web_https_required_for_production":True}

@app.get("/api/me")
async def me(request:Request):
    user=require_permission(request,"traffic:view")
    return {"id":user.id,"username":user.username,"email":user.email,"role":user.role,"status":user.status,"permissions":sorted(permissions_for(user))}

@app.get("/api/admin/users")
async def admin_users(request:Request):
    require_permission(request,"admin:users")
    with SessionLocal() as db:
        rows=db.scalars(select(User).order_by(User.created_at.desc())).all()
        return [{"id":u.id,"username":u.username,"email":u.email,"role":u.role,"status":u.status,"is_primary_admin":bool(u.is_primary_admin)} for u in rows]

@app.post("/api/admin/users/{user_id}/approve")
async def approve_user(user_id:int,request:Request):
    admin=require_permission(request,"admin:users")
    with SessionLocal() as db:
        u=db.get(User,user_id)
        if not u: raise HTTPException(404,"User not found.")
        u.status="approved"; u.approved_at=datetime.now(timezone.utc); db.commit()
    audit("admin.user.approve",request,admin.id,"user",str(user_id))
    return {"status":"approved","user_id":user_id}

@app.put("/api/admin/users/{user_id}/permissions")
async def set_user_permissions(user_id:int,permissions:list[str],request:Request):
    admin=require_permission(request,"admin:users")
    unknown=[p for p in permissions if p not in ALL_PERMISSIONS]
    if unknown: raise HTTPException(422,f"Unknown permissions: {unknown}")
    with SessionLocal() as db:
        u=db.get(User,user_id)
        if not u: raise HTTPException(404,"User not found.")
        db.query(UserPermission).filter(UserPermission.user_id==user_id).delete()
        for p in sorted(set(permissions)): db.add(UserPermission(user_id=user_id,permission=p,granted=1))
        db.commit()
    audit("admin.permissions.replace",request,admin.id,"user",str(user_id),details={"permissions":permissions})
    return {"status":"ok","user_id":user_id,"permissions":sorted(set(permissions))}

@app.get("/api/admin/audit")
async def audit_rows(request:Request,limit:int=50):
    require_permission(request,"admin:audit"); limit=max(1,min(200,limit))
    with SessionLocal() as db:
        rows=db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)).all()
        return [{"id":x.id,"occurred_at":x.occurred_at.isoformat() if x.occurred_at else None,"user_id":x.user_id,"action":x.action,"resource_type":x.resource_type,"resource_id":x.resource_id,"outcome":x.outcome,"client_ip":x.client_ip} for x in rows]

@app.get("/api/benchmark/sources")
async def benchmark_sources(request:Request):
    require_permission(request,"validation:view")
    with SessionLocal() as db:
        rows=db.scalars(select(BenchmarkSource).where(BenchmarkSource.active==1).order_by(BenchmarkSource.name)).all()
        return [{"code":x.code,"name":x.name,"source_type":x.source_type,"standard_alignment":x.standard_alignment,"independence_level":x.independence_level,"notes":x.notes} for x in rows]

@app.get("/api/database/health")
async def database_health(request:Request):
    require_permission(request,"admin:security")
    init_database()
    with SessionLocal() as db:
        return {"status":"ok","engine":"SQLite","monitoring_locations":db.scalar(select(func.count()).select_from(MonitoringLocation)) or 0,"traffic_observations":db.scalar(select(func.count()).select_from(TrafficObservation)) or 0,"monitoring_runs":db.scalar(select(func.count()).select_from(MonitoringRun)) or 0}

@app.get("/api/dashboard/summary")
async def dashboard_summary(request:Request):
    require_permission(request,"traffic:view")
    init_database()
    with SessionLocal() as db:
        locations=db.scalars(select(MonitoringLocation).where(MonitoringLocation.active==1)).all()
        latest=[]
        for loc in locations:
            row=db.scalar(select(TrafficObservation).where(TrafficObservation.location_id==loc.id).order_by(TrafficObservation.observed_at.desc(),TrafficObservation.id.desc()))
            if row:latest.append((loc,row))
        free=moderate=heavy=severe=0
        for _,row in latest:
            ci=row.congestion_index
            if ci is None:continue
            if ci<.20:free+=1
            elif ci<.50:moderate+=1
            elif ci<.70:heavy+=1
            else:severe+=1
        status=monitoring_manager.status()
        return {"monitored_locations":len(locations),"geocoded_locations":sum(1 for x in locations if x.latitude is not None and x.longitude is not None),"states_covered":len({x.state for x in locations if x.state}),"free_flow":free,"moderate":moderate,"heavy":heavy,"severe":severe,"average_jam_factor":None,"average_speed_kmh":round(sum(r.current_speed_kmh for _,r in latest if r.current_speed_kmh is not None)/max(1,sum(1 for _,r in latest if r.current_speed_kmh is not None)),2) if latest else None,"worst_location":None,"data_status":f"Nationwide automatic monitoring {'active' if status['scheduler_running'] and status['provider_configured'] else 'waiting'} · {status['eligible_locations']} eligible locations · every {status['interval_seconds']//60} min"}

@app.get("/api/locations")
async def locations(request:Request):
    require_permission(request,"locations:view")
    with SessionLocal() as db:return [serialize_location(x) for x in db.scalars(select(MonitoringLocation).order_by(MonitoringLocation.state,MonitoringLocation.city,MonitoringLocation.name)).all()]

@app.post("/api/locations",status_code=201)
async def create_location(payload:LocationCreate,request:Request):
    actor=require_permission(request,"locations:manage")
    name=payload.name.strip();city=clean_text(payload.city);state=payload.state.strip()
    with SessionLocal() as db:
        if find_duplicate(db,name,city,state):raise HTTPException(409,"This location already exists in the same city/state.")
        item=MonitoringLocation(name=name,road_name=clean_text(payload.road_name),city=city,state=state,country="Nigeria",latitude=payload.latitude,longitude=payload.longitude,radius_m=payload.radius_m,active=1 if payload.active else 0,geocode_source="Manual" if payload.latitude is not None else None,geocoded_at=datetime.now(timezone.utc) if payload.latitude is not None else None)
        db.add(item);db.commit();db.refresh(item);result=serialize_location(item)
    audit("location.create",request,actor.id,"location",str(result["id"]))
    if supabase_archive_configured():
        try: await sync_location_to_cloud(result["id"])
        except Exception: pass
    return result

@app.put("/api/locations/{location_id}")
async def update_location(location_id:int,payload:LocationUpdate,request:Request):
    actor=require_permission(request,"locations:manage")
    with SessionLocal() as db:
        item=db.get(MonitoringLocation,location_id)
        if not item:raise HTTPException(404,"Location not found.")
        changes=payload.model_dump(exclude_unset=True);target_name=clean_text(changes.get("name",item.name));target_city=clean_text(changes.get("city",item.city));target_state=clean_text(changes.get("state",item.state))
        if find_duplicate(db,target_name,target_city,target_state,location_id):raise HTTPException(409,"Another location with this name already exists in the same city/state.")
        for key,value in changes.items():
            if isinstance(value,str):value=value.strip()
            if key=="active" and value is not None:value=1 if value else 0
            setattr(item,key,value)
        if "latitude" in changes or "longitude" in changes:
            if item.latitude is None or item.longitude is None:raise HTTPException(422,"Latitude and longitude must be supplied together.")
            item.geocode_source="Manual";item.geocode_query=None;item.geocoded_at=datetime.now(timezone.utc)
        db.commit();db.refresh(item);result=serialize_location(item)
    audit("location.update",request,actor.id,"location",str(location_id))
    if supabase_archive_configured():
        try: await sync_location_to_cloud(location_id)
        except Exception: pass
    return result

@app.delete("/api/locations/{location_id}")
async def delete_location(location_id:int,request:Request):
    actor=require_permission(request,"locations:manage")
    with SessionLocal() as db:
        item=db.get(MonitoringLocation,location_id)
        if not item:raise HTTPException(404,"Location not found.")
        observed=db.scalar(select(func.count()).select_from(TrafficObservation).where(TrafficObservation.location_id==location_id)) or 0
        if observed:raise HTTPException(409,"This location has historical traffic observations. Set active=false instead of deleting it.")
        db.delete(item);db.commit()
    audit("location.delete",request,actor.id,"location",str(location_id));return {"status":"deleted","id":location_id}

@app.get("/api/search/nigeria")
async def search_nigeria(request: Request, q: str, limit: int = 10):
    actor = require_permission(request, "traffic:view")
    query = q.strip()
    if len(query) < 2:
        raise HTTPException(422, "Enter at least two characters, a road/junction/place name, or coordinates.")
    try:
        rows = await TomTomSearchClient().search_nigeria(query, limit=limit)
    except SearchUnavailable as exc:
        raise HTTPException(503 if getattr(exc, "retryable", False) else 502, detail=exc.as_dict() if hasattr(exc, "as_dict") else str(exc))
    audit("traffic.search", request, actor.id, "search", query[:120], details={"result_count": len(rows), "scope": "Nigeria"})
    return {
        "query": query,
        "scope": "Nigeria",
        "provider": ((rows[0].get("provenance") or {}).get("provider") if rows else "TomTom Search API / OpenStreetMap fallback"),
        "service": ((rows[0].get("provenance") or {}).get("service") if rows else "Nigeria search"),
        "country_filter": "NG",
        "results": rows,
        "result_count": len(rows),
        "message": None if rows else "No matching Nigerian location was returned. Try a road, junction, town, LGA, state, landmark, or coordinates.",
    }

@app.get("/api/search/reverse")
async def reverse_geocode_nigeria(request: Request, latitude: float, longitude: float):
    actor = require_permission(request, "traffic:view")
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise HTTPException(422, "Invalid latitude/longitude.")
    try:
        row = await TomTomSearchClient().reverse_geocode_nigeria(latitude, longitude)
    except SearchUnavailable as exc:
        raise HTTPException(503 if getattr(exc, "retryable", False) else 502, detail=exc.as_dict() if hasattr(exc, "as_dict") else str(exc))
    audit("traffic.reverse_geocode", request, actor.id, "coordinate", f"{latitude:.6f},{longitude:.6f}", details={"found": bool(row), "scope": "Nigeria"})
    return {"status": "ok" if row else "not_found", "result": row}

@app.post("/api/traffic/evaluate")
async def evaluate_traffic(payload: TrafficPointEvaluationRequest, request: Request):
    actor = require_permission(request, "traffic:view")
    try:
        result = await evaluate_traffic_point(payload.latitude, payload.longitude, payload.radius_m, payload.label)
    except SearchUnavailable as exc:
        raise HTTPException(503 if getattr(exc, "retryable", False) else 502, detail=exc.as_dict() if hasattr(exc, "as_dict") else str(exc))
    audit(
        "traffic.evaluate",
        request,
        actor.id,
        "coordinate",
        f"{payload.latitude:.6f},{payload.longitude:.6f}",
        details={"label": payload.label, "radius_m": payload.radius_m, "scope": "Nigeria", "status": result.get("status")},
    )
    return result

@app.post("/api/locations/from-search", status_code=201)
async def create_location_from_search(payload: LocationFromSearch, request: Request):
    actor = require_permission(request, "locations:manage")
    name = payload.name.strip()
    city = clean_text(payload.city)
    state = payload.state.strip()
    with SessionLocal() as db:
        if find_duplicate(db, name, city, state):
            raise HTTPException(409, "This location already exists in the same city/state.")
        item = MonitoringLocation(
            name=name,
            road_name=clean_text(payload.road_name),
            city=city,
            state=state,
            country="Nigeria",
            latitude=payload.latitude,
            longitude=payload.longitude,
            radius_m=payload.radius_m,
            active=1,
            geocode_source="TomTom Search API",
            geocode_query=clean_text(payload.search_query),
            geocoded_at=datetime.now(timezone.utc),
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        result = serialize_location(item)
    audit("location.create_from_search", request, actor.id, "location", str(result["id"]), details={"query": payload.search_query})
    if supabase_archive_configured():
        try: await sync_location_to_cloud(result["id"])
        except Exception: pass
    return result

@app.get("/api/analytics/location/{location_id}")
async def analytics_location(location_id:int, request:Request, days:int=30):
    require_permission(request,"analytics:view")
    if supabase_archive_configured():
        try: await import_cloud_history(location_id,days)
        except Exception: pass
    result=analyze_location(location_id,days)
    if result is None: raise HTTPException(404,"Location not found.")
    return result

@app.get("/api/analytics/network")
async def analytics_network(request:Request, days:int=30):
    require_permission(request,"analytics:view")
    return network_summary(max(1,min(days,3650)))

@app.get("/api/reports/location/{location_id}/export")
async def report_export(location_id:int, request:Request, days:int=30, format:str="pdf"):
    actor=require_permission(request,"reports:export")
    fmt=format.lower().strip(); days=max(1,min(int(days),3650))
    if supabase_archive_configured():
        try: await import_cloud_history(location_id,days)
        except Exception: pass
    if fmt not in FORMATS: raise HTTPException(422,f"Unsupported format. Choose one of: {', '.join(sorted(FORMATS))}")
    try: data,mime,name=export_bytes(location_id,days,fmt)
    except KeyError: raise HTTPException(404,"Location not found.")
    audit("report.export",request,actor.id,"location",str(location_id),details={"days":days,"format":fmt,"filename":name,"validation":"provider_reference"})
    return Response(content=data,media_type=mime,headers={"Content-Disposition":f'attachment; filename="{name}"',"X-ITICAS-Validation":"provider_reference","X-ITICAS-Independent-Benchmark":"not_configured"})

@app.get("/api/historical/status")
async def historical_status(request:Request, location_id:int, days:int=30):
    require_permission(request,"analytics:view")
    days=max(1,min(int(days),366))
    # Traffic Stats is asynchronous. Opportunistically poll a few pending jobs
    # on every status request in addition to the lifespan background worker so
    # completed provider results are ingested promptly even after sleep/restart.
    if historical_configured():
        await asyncio.to_thread(refresh_pending_jobs_once, 3)
    cloud={"configured":False}
    cloud_import={"configured":False,"imported":0}
    if supabase_archive_configured():
        try:
            cloud=await cloud_coverage_for_location(location_id,days)
            # Historical Data must show the autonomous observations ITICAS has
            # already stored in Supabase. Pull them into the validated local
            # analytics database before calculating local coverage.
            cloud_import=await import_cloud_history(location_id,days)
        except Exception as exc:
            cloud={"configured":True,"error":str(exc)}
            cloud_import={"configured":True,"error":str(exc)}
    return {
        "configured":historical_configured(),
        "coverage":historical_coverage(location_id,days),
        "jobs":list_jobs(100),
        "autonomous_cloud_archive":cloud,
        "cloud_import":cloud_import,
    }

@app.get("/api/historical/archive-observations")
async def historical_archive_observations(request:Request, location_id:int, days:int=7, limit:int=1000):
    require_permission(request,"analytics:view")
    days=max(1,min(int(days),3660)); limit=max(1,min(int(limit),5000))
    if supabase_archive_configured():
        try:
            await import_cloud_history(location_id,days)
        except Exception:
            # Local historical observations remain usable if the cloud is
            # temporarily unreachable. The status endpoint reports cloud errors.
            pass
    start=datetime.now(timezone.utc).replace(tzinfo=None)-timedelta(days=days)
    with SessionLocal() as db:
        loc=db.get(MonitoringLocation,location_id)
        if not loc: raise HTTPException(404,"Location not found.")
        rows=db.scalars(select(TrafficObservation).where(
            TrafficObservation.location_id==location_id,
            TrafficObservation.observed_at>=start
        ).order_by(TrafficObservation.observed_at.desc(),TrafficObservation.id.desc()).limit(limit)).all()
        observations=[{
            "id":r.id,
            "observed_at":r.observed_at.isoformat() if r.observed_at else None,
            "current_speed_kmh":r.current_speed_kmh,
            "free_flow_speed_kmh":r.free_flow_speed_kmh,
            "congestion_index":r.congestion_index,
            "delay_seconds":r.delay_seconds,
            "current_travel_time_seconds":r.current_travel_time_seconds,
            "free_flow_travel_time_seconds":r.free_flow_travel_time_seconds,
            "confidence":r.confidence,
            "road_closed":bool(r.road_closed) if r.road_closed is not None else None,
            "functional_road_class":r.functional_road_class,
            "provider":r.provider,
        } for r in rows]
    return {
        "location":{"id":loc.id,"name":loc.name,"road_name":loc.road_name,"city":loc.city,"state":loc.state},
        "days":days,"count":len(observations),"limit":limit,"observations":observations,
        "provenance":"ITICAS local observations plus autonomous cloud archive observations imported with explicit provider labels",
    }

@app.post("/api/historical/backfill/{location_id}")
async def historical_backfill(location_id:int, request:Request, days:int=30):
    actor=require_permission(request,"analytics:view")
    try:
        result=submit_backfill(location_id,max(1,min(int(days),366)))
    except HistoricalTrafficUnavailable as exc:
        raise HTTPException(getattr(exc,"status_code",502),detail={"message":str(exc),"category":exc.category})
    audit("historical.backfill.submit",request,actor.id,"location",str(location_id),details={"days":days})
    return result

@app.post("/api/historical/jobs/{job_id}/refresh")
async def historical_job_refresh(job_id:int, request:Request):
    actor=require_permission(request,"analytics:view")
    try:
        result=refresh_job(job_id)
    except HistoricalTrafficUnavailable as exc:
        raise HTTPException(getattr(exc,"status_code",502),detail={"message":str(exc),"category":exc.category})
    audit("historical.backfill.refresh",request,actor.id,"historical_job",str(job_id),details={"state":result.get("state")})
    return result

@app.get("/api/spatial/summary")
async def spatial_api(request:Request, days:int=30, bandwidth_km:float=5.0):
    require_permission(request,"analytics:view")
    return spatial_summary(days,bandwidth_km)

@app.get("/api/map/tile/{z}/{x}/{y}")
async def map_tile_proxy(z:int,x:int,y:int,request:Request):
    require_permission(request,"traffic:view")
    try:
        raw,mime,provider=await asyncio.to_thread(map_tile,z,x,y)
    except MapTileUnavailable as exc:
        raise HTTPException(503,str(exc))
    return Response(content=raw,media_type=mime,headers={"Cache-Control":"public, max-age=86400","X-ITICAS-Map-Provider":provider})


@app.get("/api/map/static")
async def map_static(request:Request, latitude:float=settings.map_default_latitude, longitude:float=settings.map_default_longitude, zoom:int=settings.map_default_zoom, width:int=1100, height:int=650):
    require_permission(request,"traffic:view")
    raw,provider=await asyncio.to_thread(render_static_map,latitude,longitude,zoom,width,height)
    return Response(content=raw,media_type="image/png",headers={"Cache-Control":"no-store","X-ITICAS-Map-Provider":provider})

@app.post("/api/historical/target/from-search")
async def historical_target_from_search(payload:LocationFromSearch, request:Request):
    actor=require_permission(request,"analytics:view")
    name=payload.name.strip(); city=clean_text(payload.city); state=(payload.state or "Unknown").strip()
    with SessionLocal() as db:
        existing=db.scalar(select(MonitoringLocation).where(
            func.lower(MonitoringLocation.name)==name.lower(),
            MonitoringLocation.latitude.between(payload.latitude-0.00005,payload.latitude+0.00005),
            MonitoringLocation.longitude.between(payload.longitude-0.00005,payload.longitude+0.00005)
        ))
        if existing:
            result=serialize_location(existing); result["analysis_target_only"]=not bool(existing.active); return result
        item=MonitoringLocation(name=name,road_name=clean_text(payload.road_name),city=city,state=state,country="Nigeria",latitude=payload.latitude,longitude=payload.longitude,radius_m=payload.radius_m,active=0,geocode_source="Historical ad-hoc analysis target",geocode_query=clean_text(payload.search_query),geocoded_at=datetime.now(timezone.utc))
        db.add(item);db.commit();db.refresh(item);result=serialize_location(item)
    result["analysis_target_only"]=True
    audit("historical.target.create",request,actor.id,"location",str(result["id"]),details={"query":payload.search_query,"active_monitoring":False})
    return result




@app.get("/api/research/tool-output/{location_id}/{tool}")
async def research_tool_output(location_id:int, tool:str, request:Request, days:int=30):
    require_permission(request,"analytics:view")
    try:name,data,mime=build_individual_tool_output(location_id,days,tool)
    except ValueError as exc:raise HTTPException(400,str(exc))
    return Response(content=data,media_type=mime,headers={"Content-Disposition":f'attachment; filename="{name}"'})

@app.get("/api/research/workflow/{location_id}")
async def research_workflow_status(location_id:int, request:Request, days:int=30):
    require_permission(request,"analytics:view")
    return workflow_status(location_id,days)

@app.post("/api/research/corridor-scan/{location_id}")
async def research_corridor_scan(location_id:int, request:Request):
    actor=require_permission(request,"analytics:view")
    try:data=await acquire_corridor_probe_evidence(location_id)
    except ValueError as exc:raise HTTPException(404,str(exc))
    audit("research.corridor_scan",request,actor.id,"monitoring_location",str(location_id))
    return data

@app.get("/api/research/corridor-analysis/{location_id}")
async def research_corridor_analysis(location_id:int, request:Request, days:int=30):
    require_permission(request,"analytics:view")
    return corridor_analysis(location_id,days)

@app.get("/api/research/catalog/{location_id}")
async def research_catalog_api(location_id:int, request:Request, days:int=30):
    require_permission(request,"analytics:view")
    data=research_catalog(location_id,days)
    if not data: raise HTTPException(404,"Location not found.")
    return data

@app.get("/api/research/objectives/{location_id}")
async def research_objectives_api(location_id:int, request:Request, days:int=30):
    require_permission(request,"analytics:view")
    data=objective_matrix(location_id,days)
    if not data: raise HTTPException(404,"Location not found.")
    return data

@app.post("/api/research/corridor-probes/{location_id}")
async def research_corridor_probes(location_id:int, request:Request, spacing_m:int=100):
    require_permission(request,"analytics:view")
    result=ensure_corridor_probes(location_id,spacing_m)
    if supabase_archive_configured():
        try: await sync_location_to_cloud(location_id)
        except Exception: pass
    return result

@app.post("/api/research/surveys", status_code=201)
async def research_survey_create(payload:ResearchSurveyCreate, request:Request):
    actor=require_permission(request,"analytics:view")
    with SessionLocal() as db:
        if payload.location_id is not None and not db.get(MonitoringLocation,payload.location_id):
            raise HTTPException(404,"Location not found.")
        item=ResearchSurveySession(location_id=payload.location_id,name=payload.name.strip(),
            operator=payload.operator,purpose=payload.purpose,notes=payload.notes,
            created_by_user_id=actor.id,status="active")
        db.add(item);db.commit();db.refresh(item)
        result={"id":item.id,"name":item.name,"status":item.status,"started_at":item.started_at.isoformat()}
    audit("research.survey.create",request,actor.id,"research_survey",str(result["id"]))
    return result

@app.post("/api/research/surveys/{session_id}/points", status_code=201)
async def research_survey_point(session_id:int, payload:GNSSTrackPointCreate, request:Request):
    actor=require_permission(request,"analytics:view")
    with SessionLocal() as db:
        session=db.get(ResearchSurveySession,session_id)
        if not session: raise HTTPException(404,"Survey session not found.")
        if session.status!="active": raise HTTPException(409,"Survey session is not active.")
        if session.location_id is not None:
            quality=gnss_quality(session.location_id,payload.latitude,payload.longitude,payload.accuracy_m)
            if not quality.get("valid"):
                raise HTTPException(422, quality.get("reason") or "GNSS point is outside the selected study corridor.")
        item=GNSSTrackPoint(session_id=session_id,captured_at=(payload.captured_at or datetime.now(timezone.utc)),
            latitude=payload.latitude,longitude=payload.longitude,altitude_m=payload.altitude_m,
            accuracy_m=payload.accuracy_m,speed_mps=payload.speed_mps,heading_deg=payload.heading_deg,
            traffic_state=payload.traffic_state,queue_length_m=payload.queue_length_m,
            notes=payload.notes,source="browser_gnss")
        db.add(item);db.commit();db.refresh(item)
        return {"id":item.id,"session_id":session_id,"captured_at":item.captured_at.isoformat()}

@app.post("/api/research/surveys/{session_id}/stop")
async def research_survey_stop(session_id:int, request:Request):
    actor=require_permission(request,"analytics:view")
    with SessionLocal() as db:
        session=db.get(ResearchSurveySession,session_id)
        if not session: raise HTTPException(404,"Survey session not found.")
        session.status="completed";session.ended_at=datetime.now(timezone.utc);db.commit()
    audit("research.survey.stop",request,actor.id,"research_survey",str(session_id))
    return {"id":session_id,"status":"completed"}

@app.get("/api/research/surveys/summary")
async def research_survey_summary(request:Request, location_id:int|None=None):
    require_permission(request,"analytics:view")
    return survey_summary(location_id)

@app.get("/api/research/package/{location_id}")
async def research_package(location_id:int, request:Request, days:int=30):
    require_permission(request,"analytics:view")
    try:name,data,mime=build_research_package(location_id,days)
    except ValueError as exc:raise HTTPException(404,str(exc))
    return Response(content=data,media_type=mime,headers={"Content-Disposition":f'attachment; filename="{name}"'})

@app.post("/api/predictions/run")
async def run_prediction(request: Request):
    actor = require_permission(request, "prediction:run")
    payload = await request.json()
    try:
        location_id = int(payload.get("location_id"))
        start = datetime.fromisoformat(str(payload.get("forecast_start")).replace("Z", "+00:00"))
        end = datetime.fromisoformat(str(payload.get("forecast_end")).replace("Z", "+00:00"))
        step_minutes = int(payload.get("step_minutes", 15))
        lookback_days = int(payload.get("lookback_days", 30))
    except Exception:
        raise HTTPException(422, "location_id, forecast_start and forecast_end are required and must be valid.")
    if supabase_archive_configured():
        try:
            await import_cloud_history(location_id, days=max(1, min(lookback_days, 3650)))
        except Exception:
            pass
    try:
        try:
            prediction_context = await collect_prediction_context(location_id, start, end)
        except Exception as context_exc:
            prediction_context = {"status": "unavailable", "reason": str(context_exc)}
        result = forecast_location(location_id, start, end, step_minutes=step_minutes, lookback_days=lookback_days, external_context=prediction_context)
    except LookupError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    audit("prediction.run", request, actor.id, "location", str(location_id), details={"forecast_start": start.isoformat(), "forecast_end": end.isoformat(), "step_minutes": step_minutes, "lookback_days": lookback_days, "status": result.get("status")})
    return result

@app.post("/api/predictions/calibrate-context")
async def calibrate_prediction_context(request: Request):
    actor = require_permission(request, "prediction:run")
    payload = await request.json()
    try:
        location_id = int(payload.get("location_id"))
        lookback_days = int(payload.get("lookback_days", 90))
        result = await calibrate_context_effects(location_id, lookback_days=lookback_days)
    except LookupError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    audit("prediction.calibrate_context", request, actor.id, "location", str(location_id), details={"lookback_days":lookback_days,"rain_validated":bool((result.get("rain") or {}).get("validated")),"incident_validated":bool((result.get("incident") or {}).get("validated"))})
    return result

@app.get("/api/predictions/calibration/{location_id}")
async def prediction_calibration_status(location_id:int, request:Request):
    require_permission(request, "prediction:run")
    return latest_context_calibration(location_id)

@app.get("/api/predictions/verification/{location_id}")
async def prediction_verification_status(location_id:int, request:Request):
    require_permission(request, "prediction:run")
    return prediction_verification(location_id)

@app.post("/api/predictions/export/decision-package")
async def export_prediction_decision_package(request: Request):
    actor = require_permission(request, "prediction:run")
    payload = await request.json()
    try:
        name, data, mime = prediction_decision_package(payload)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    audit("prediction.export_decision_package", request, actor.id, "prediction", str(payload.get("request_id") or "unsaved"), details={"filename": name, "location": (payload.get("location") or {}).get("name")})
    return Response(content=data, media_type=mime, headers={"Content-Disposition": f'attachment; filename="{name}"'})

@app.get("/api/predictions/history")
async def predictions_history(request: Request, limit: int = 30):
    require_permission(request, "prediction:run")
    return prediction_history(limit)

@app.get("/api/diagnostics/readiness")
async def diagnostics_readiness(request: Request):
    require_permission(request, "traffic:view")
    return await provider_readiness()

@app.get("/api/weather/current")
async def weather_current(request: Request, latitude: float, longitude: float):
    require_permission(request, "traffic:view")
    try:
        return await current_weather(latitude, longitude)
    except WeatherUnavailable as exc:
        raise HTTPException(503 if exc.retryable else 502, detail=exc.as_dict())

@app.get("/api/weather/intelligence")
async def weather_intelligence(request: Request, latitude: float, longitude: float, days: int = 7):
    require_permission(request, "traffic:view")
    try:
        return await weather_intelligence_forecast(latitude, longitude, days)
    except WeatherUnavailable as exc:
        raise HTTPException(503 if exc.retryable else 502, detail=exc.as_dict())

@app.get("/api/weather/history")
async def weather_history(request: Request, latitude: float, longitude: float, days: int = 30):
    require_permission(request, "traffic:view")
    try:
        return await weather_history_summary(latitude, longitude, days)
    except WeatherUnavailable as exc:
        raise HTTPException(503 if exc.retryable else 502, detail=exc.as_dict())

@app.get("/api/weather/reference/era5-land")
async def weather_reference(request: Request, latitude: float, longitude: float, days_ago: int = 7):
    require_permission(request, "validation:view")
    try:
        return await era5_land_reference(latitude, longitude, days_ago)
    except WeatherUnavailable as exc:
        raise HTTPException(503 if exc.retryable else 502, detail=exc.as_dict())

@app.get("/api/providers/tomtom/status")
async def tomtom_provider_status(request:Request):
    require_permission(request,"traffic:view")
    provider=TomTomTrafficClient()
    return {"provider":provider.provider_name,"configured":provider.configured,"country_scope":"Nigeria","flow_service":"Flow Segment Data v4","incident_service":"Incident Details v5","credential_exposed":False}

@app.post("/api/traffic/acquire/{location_id}")
async def acquire_traffic(location_id:int,request:Request):
    actor=require_permission(request,"traffic:acquire")
    try:result=await acquire_location_traffic_data(location_id)
    except LocationNotFound as exc:raise HTTPException(404,str(exc))
    except MissingCoordinates as exc:raise HTTPException(422,str(exc))
    except ProviderUnavailable as exc:raise HTTPException(502,str(exc))
    audit("traffic.acquire",request,actor.id,"location",str(location_id))
    return result

@app.get("/api/traffic/latest/{location_id}")
async def latest_traffic(location_id:int,request:Request):
    require_permission(request,"traffic:view")
    with SessionLocal() as db:
        location=db.get(MonitoringLocation,location_id)
        if not location:raise HTTPException(404,"Location not found.")
        row=db.scalar(select(TrafficObservation).where(TrafficObservation.location_id==location_id).order_by(TrafficObservation.observed_at.desc(),TrafficObservation.id.desc()))
        if not row:return {"location_id":location_id,"location":location.name,"observation":None,"validation":{"validation_status":"no_observation"},"message":"No live traffic observation stored yet."}
        return {"location_id":location_id,"location":location.name,"city":location.city,"state":location.state,"observed_at":row.observed_at.isoformat() if row.observed_at else None,"observation":{"current_speed_kmh":row.current_speed_kmh,"free_flow_speed_kmh":row.free_flow_speed_kmh,"congestion_index":row.congestion_index,"delay_seconds":row.delay_seconds,"current_travel_time_seconds":row.current_travel_time_seconds,"free_flow_travel_time_seconds":row.free_flow_travel_time_seconds,"confidence":row.confidence,"road_closed":bool(row.road_closed) if row.road_closed is not None else None,"functional_road_class":row.functional_road_class,"provider":row.provider},"validation":validation_payload(row.id)}

@app.get("/api/monitoring/status")
async def monitoring_status(request:Request):
    require_permission(request,"monitoring:view");return monitoring_manager.status()

@app.post("/api/monitoring/run-now",status_code=202)
async def monitoring_run_now(request:Request):
    actor=require_permission(request,"monitoring:run")
    if not TomTomTrafficClient().configured:raise HTTPException(503,"TomTom Traffic API is not configured.")
    if not monitoring_manager.trigger_now():return {"status":"busy","message":"A nationwide monitoring cycle is already running."}
    audit("monitoring.run_now",request,actor.id)
    return {"status":"accepted","scope":"Nigeria","message":"Nationwide monitoring cycle started in the background."}

@app.get("/api/monitoring/runs")
async def monitoring_runs(request:Request,limit:int=20):
    require_permission(request,"monitoring:view");limit=max(1,min(100,limit))
    with SessionLocal() as db:
        rows=db.scalars(select(MonitoringRun).order_by(MonitoringRun.id.desc()).limit(limit)).all()
        return [{"id":x.id,"started_at":x.started_at.isoformat() if x.started_at else None,"finished_at":x.finished_at.isoformat() if x.finished_at else None,"trigger":x.trigger,"status":x.status,"total_active_locations":x.total_active_locations,"eligible_locations":x.eligible_locations,"attempted_locations":x.attempted_locations,"successful_locations":x.successful_locations,"failed_locations":x.failed_locations,"skipped_locations":x.skipped_locations,"provider":x.provider,"message":x.message} for x in rows]


# ITICAS_STAGE06_MULTI_PROVIDER
from .multi_provider_traffic import traffic_broker
try:
    from fastapi import Depends
    @app.get("/api/providers/traffic/status")
    def iticas_traffic_provider_status():
        return traffic_broker.status()

    @app.get("/api/providers/traffic/google-corridor")
    async def iticas_google_corridor(origin_lat:float,origin_lon:float,dest_lat:float,dest_lon:float):
        return await traffic_broker.google_corridor(origin_lat,origin_lon,dest_lat,dest_lon)
except Exception:
    pass

# ITICAS_STAGE07_NIGERIA_TRAFFIC
from .nigeria_traffic_broker import nigeria_traffic_broker
@app.get("/api/providers/nigeria-traffic/status")
def nigeria_traffic_status(): return nigeria_traffic_broker.status()
@app.get("/api/providers/nigeria-traffic/mapbox-corridor")
async def nigeria_mapbox_corridor(origin_lat:float,origin_lon:float,dest_lat:float,dest_lon:float):
 return await nigeria_traffic_broker.mapbox_corridor(origin_lat,origin_lon,dest_lat,dest_lon)

# ITICAS_STAGE09_TRAFFIC_AWARE_ROUTING
from dataclasses import asdict as _stage09_asdict
from .tomtom_route_traffic import TomTomTrafficAwareRouting, safe_status as _stage09_status
@app.get("/api/providers/tomtom-route-traffic/status")
def stage09_status(): return _stage09_status()
@app.get("/api/providers/tomtom-route-traffic/evaluate")
def stage09_eval(origin_lat:float,origin_lon:float,destination_lat:float,destination_lon:float):
 return _stage09_asdict(TomTomTrafficAwareRouting().acquire((origin_lat,origin_lon),(destination_lat,destination_lon)))

# ITICAS_STAGE10_TRAFFIC_INTELLIGENCE
from .traffic_intelligence_integration import status as _s10status
@app.get("/api/traffic-intelligence/status")
def stage10_status(): return _s10status()

# ITICAS_STAGE11_UI_BRIDGE
from .stage11_ui_bridge import latest as _s11latest
@app.get("/api/traffic-intelligence/ui-summary")
def stage11_ui_summary(study_id:str="stage10_ibadan"): return _s11latest(study_id)

# ITICAS_STAGE12_RESEARCH_MAP
from .stage12_research_map import dashboard as _s12dash
@app.get("/api/research/traffic-intelligence")
def stage12_research_traffic(study_id:str="stage10_ibadan"): return _s12dash(study_id)

# ITICAS_STAGE13_REQUEST_CONSERVATION
from .request_conservation import status as _rcs
from .temporal_route_intelligence import analyse as _tra
@app.get("/api/providers/request-conservation/status")
def stage13_rc(days:int=1): return _rcs(days)
@app.get("/api/traffic-intelligence/temporal")
def stage13_temporal(study_id:str="stage10_ibadan"): return _tra(study_id)

# ITICAS_STAGE14_SPATIAL_ENFORCEMENT
from .spatial_route_intelligence import analyse as _s14spatial
from .request_policy import policy as _s14policy
@app.get("/api/traffic-intelligence/spatial")
def stage14_spatial(study_id:str="stage10_ibadan"): return _s14spatial(study_id)
@app.get("/api/providers/request-conservation/policy")
def stage14_request_policy(): return _s14policy()

# ITICAS_STAGE15_COMPLETION_INTELLIGENCE
from .completion_intelligence import reliability as _s15rel, completion as _s15comp
from .provider_call_audit import audit as _s15audit
@app.get("/api/traffic-intelligence/reliability")
def stage15_reliability(study_id:str="stage10_ibadan"): return _s15rel(study_id)
@app.get("/api/traffic-intelligence/completion")
def stage15_completion(study_id:str="stage10_ibadan"): return _s15comp(study_id)
@app.get("/api/providers/provider-call-audit")
def stage15_provider_audit(): return _s15audit()

# ITICAS_STAGE16_PROVIDER_ENFORCEMENT
from .provider_enforcement import authorize as _s16auth, diagnostics_policy as _s16diag
@app.get("/api/providers/enforcement/status")
def stage16_enforcement_status(): return {"policy":_s16diag(),"passive_map":_s16auth("map_open"),"explicit_live":_s16auth("explicit_live_acquisition",explicit_live=True)}

# ITICAS_STAGE17_CORE_COMPLETION_GATE
from .core_completion_gate import evaluate as _s17gate
@app.get("/api/system/core-completion")
def stage17_core_completion(): return _s17gate()

# ITICAS_STAGE18_RELEASE_QUALIFICATION
from .release_qualification import report as _s18report, write_json as _s18write
from .delivery_readiness import readiness as _s18ready
@app.get("/api/release/research-report")
def stage18_report(study_id:str="stage10_ibadan"): return _s18report(study_id)
@app.post("/api/release/research-report/export")
def stage18_export(study_id:str="stage10_ibadan"): return {"path":_s18write(study_id)}
@app.get("/api/release/readiness")
def stage18_readiness(): return _s18ready()

# ITICAS_STAGE19_CENTRAL_RELEASE_GATE
from .central_release_gate import status as _s19status
@app.get("/api/release/central-access-readiness")
def stage19_central_access_readiness(): return _s19status()
