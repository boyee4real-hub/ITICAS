from pydantic_settings import BaseSettings, SettingsConfigDict
from .paths import DATA_ROOT
from .runtime_env import load_runtime_env

# Explicitly load persistent runtime configuration before BaseSettings is instantiated.
# This also works in PyInstaller --windowed/frozen builds.
load_runtime_env(DATA_ROOT / '.env')

class Settings(BaseSettings):
    host: str = "127.0.0.1"
    port: int = 8765
    database_url: str = f"sqlite:///{(DATA_ROOT / 'database' / 'iticas.db').as_posix()}"

    app_name: str = "Nigeria Traffic Intelligence and Congestion Analysis System"
    app_short_name: str = "ITICAS"
    developer_name: str = "Dr. Oyeyode A.O. MNIS, MGEOSON, MNAG"
    developer_credit: str = "Developed by Dr. Oyeyode A.O. MNIS, MGEOSON, MNAG"
    stage: str = "26"
    version: str = "0.26.3"

    tomtom_api_key: str | None = None
    tomtom_timeout_seconds: float = 20.0
    provider_retry_attempts: int = 3
    provider_retry_backoff_seconds: float = 0.75

    monitoring_enabled: bool = True
    monitoring_interval_seconds: int = 300
    monitoring_startup_delay_seconds: int = 15
    monitoring_inter_location_delay_seconds: float = 0.5
    # Stage 20: autonomous historical archive.
    # Locally, embedded monitoring remains available. In cloud deployment,
    # set EMBEDDED_MONITORING_ENABLED=false and run the dedicated collector service.
    embedded_monitoring_enabled: bool = True
    archive_collector_enabled: bool = True
    archive_location_interval_seconds: int = 300
    archive_probe_interval_seconds: int = 3600
    archive_heartbeat_seconds: int = 30
    archive_backup_interval_hours: int = 24
    archive_backup_retention_days: int = 30
    archive_probe_collection_enabled: bool = True

    # Stage 21: serverless autonomous archive (Supabase primary).
    supabase_archive_enabled: bool = False
    supabase_url: str | None = None
    supabase_secret_key: str | None = None
    supabase_archive_timeout_seconds: float = 20.0
    supabase_default_location_interval_minutes: int = 5
    supabase_default_probe_interval_minutes: int = 60



    prediction_min_horizon_minutes: int = 5
    prediction_max_horizon_minutes: int = 10080

    security_session_hours: int = 8
    security_cookie_secure: bool = False
    security_cookie_name: str = "iticas_session"
    security_login_window_seconds: int = 900
    security_login_max_attempts: int = 5
    security_password_min_length: int = 12

    access_gateway_url: str | None = None
    access_gateway_timeout_seconds: float = 20.0


    weather_enabled: bool = True
    weather_timeout_seconds: float = 15.0
    weather_provider_name: str = "Open-Meteo Forecast API"
    weather_reference_name: str = "ERA5-Land reanalysis"
    diagnostics_timeout_seconds: float = 12.0

    map_default_latitude: float = 9.0820
    map_default_longitude: float = 8.6753
    map_default_zoom: int = 6
    map_evaluation_radius_m: int = 1500
    map_tile_url: str = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
    map_tile_attribution: str = "&copy; OpenStreetMap contributors"

    # Stage 11: resilient basemap and optional historical traffic backfill.
    map_primary_engine: str = "iticas_tomtom_raster_proxy"
    map_primary_style_url: str = "/api/map/tile/{z}/{x}/{y}"
    map_fallback_tile_url: str = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
    map_fallback_tile_attribution: str = "&copy; OpenStreetMap contributors"
    traffic_stats_api_key: str | None = None
    traffic_stats_timeout_seconds: float = 30.0
    traffic_stats_provider_name: str = "TomTom Traffic Stats Route Analysis"
    historical_auto_refresh_seconds: int = 12
    map_cache_hours: int = 168

    model_config = SettingsConfigDict(
        env_file=DATA_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

settings = Settings()
settings.app_name = "Nigeria Traffic Intelligence and Congestion Analysis System"
settings.app_short_name = "ITICAS"
settings.developer_name = "Dr. Oyeyode A.O. MNIS, MGEOSON, MNAG"
settings.developer_credit = "Developed by Dr. Oyeyode A.O. MNIS, MGEOSON, MNAG"
settings.stage = "26"
settings.version = "0.26.3"
