from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import create_engine, String, Float, Integer, DateTime, ForeignKey, Text, Index, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from .config import settings

from .paths import DATA_ROOT
DATABASE_DIR = DATA_ROOT / "database"
DATABASE_DIR.mkdir(parents=True, exist_ok=True)

class Base(DeclarativeBase):
    pass

class MonitoringLocation(Base):
    __tablename__ = "monitoring_locations"
    __table_args__ = (Index("ix_location_place", "state", "city", "name"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(150), index=True)
    road_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    state: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    country: Mapped[str] = mapped_column(String(120), default="Nigeria")
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    radius_m: Mapped[int] = mapped_column(Integer, default=1000)
    active: Mapped[int] = mapped_column(Integer, default=1)
    geocode_source: Mapped[str | None] = mapped_column(String(120), nullable=True)
    geocode_query: Mapped[str | None] = mapped_column(String(300), nullable=True)
    geocoded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

class TrafficObservation(Base):
    __tablename__ = "traffic_observations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("monitoring_locations.id"), index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    current_speed_kmh: Mapped[float | None] = mapped_column(Float, nullable=True)
    free_flow_speed_kmh: Mapped[float | None] = mapped_column(Float, nullable=True)
    jam_factor: Mapped[float | None] = mapped_column(Float, nullable=True)
    congestion_index: Mapped[float | None] = mapped_column(Float, nullable=True)
    delay_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_travel_time_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    free_flow_travel_time_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    road_closed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    functional_road_class: Mapped[str | None] = mapped_column(String(30), nullable=True)
    segment_geometry_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider: Mapped[str | None] = mapped_column(String(80), nullable=True)
    source_timestamp: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    raw_reference: Mapped[str | None] = mapped_column(Text, nullable=True)

class TrafficIncident(Base):
    __tablename__ = "traffic_incidents"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    location_id: Mapped[int | None] = mapped_column(ForeignKey("monitoring_locations.id"), nullable=True)
    provider_incident_id: Mapped[str | None] = mapped_column(String(180), nullable=True, index=True)
    incident_type: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    severity: Mapped[str | None] = mapped_column(String(50), nullable=True)
    magnitude_of_delay: Mapped[int | None] = mapped_column(Integer, nullable=True)
    delay_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    road_from: Mapped[str | None] = mapped_column(String(250), nullable=True)
    road_to: Mapped[str | None] = mapped_column(String(250), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    source_timestamp: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    provider: Mapped[str | None] = mapped_column(String(80), nullable=True)
    raw_json: Mapped[str | None] = mapped_column(Text, nullable=True)

class WeatherObservation(Base):
    __tablename__ = "weather_observations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    location_id: Mapped[int | None] = mapped_column(ForeignKey("monitoring_locations.id"), nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    rainfall_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    temperature_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    humidity_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    visibility_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    provider: Mapped[str | None] = mapped_column(String(80), nullable=True)

class MonitoringRun(Base):
    __tablename__ = "monitoring_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    trigger: Mapped[str] = mapped_column(String(30), default="scheduled")
    status: Mapped[str] = mapped_column(String(30), default="running", index=True)
    total_active_locations: Mapped[int] = mapped_column(Integer, default=0)
    eligible_locations: Mapped[int] = mapped_column(Integer, default=0)
    attempted_locations: Mapped[int] = mapped_column(Integer, default=0)
    successful_locations: Mapped[int] = mapped_column(Integer, default=0)
    failed_locations: Mapped[int] = mapped_column(Integer, default=0)
    skipped_locations: Mapped[int] = mapped_column(Integer, default=0)
    provider: Mapped[str | None] = mapped_column(String(80), nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)

class MonitoringRunItem(Base):
    __tablename__ = "monitoring_run_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("monitoring_runs.id"), index=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("monitoring_locations.id"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(30), index=True)
    observation_id: Mapped[int | None] = mapped_column(ForeignKey("traffic_observations.id"), nullable=True)
    incidents_received: Mapped[int] = mapped_column(Integer, default=0)
    new_incidents_stored: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

# Prediction tables exist now so prediction remains Nigeria-wide and arbitrary-horizon by architecture.
class PredictionRequest(Base):
    __tablename__ = "prediction_requests"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("monitoring_locations.id"), index=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    forecast_start_at: Mapped[datetime] = mapped_column(DateTime)
    forecast_end_at: Mapped[datetime] = mapped_column(DateTime)
    horizon_minutes: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), default="pending")
    model_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    validation_status: Mapped[str | None] = mapped_column(String(80), nullable=True)
    limitations: Mapped[str | None] = mapped_column(Text, nullable=True)

class TrafficPrediction(Base):
    __tablename__ = "traffic_predictions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    prediction_request_id: Mapped[int] = mapped_column(ForeignKey("prediction_requests.id"), index=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("monitoring_locations.id"), index=True)
    predicted_for: Mapped[datetime] = mapped_column(DateTime, index=True)
    predicted_speed_kmh: Mapped[float | None] = mapped_column(Float, nullable=True)
    predicted_congestion_index: Mapped[float | None] = mapped_column(Float, nullable=True)
    predicted_category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    lower_bound: Mapped[float | None] = mapped_column(Float, nullable=True)
    upper_bound: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

class PredictionContextCalibration(Base):
    __tablename__ = "prediction_context_calibrations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("monitoring_locations.id"), index=True)
    calibrated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    lookback_days: Mapped[int] = mapped_column(Integer, default=90)
    status: Mapped[str] = mapped_column(String(40), default="completed")
    rain_validated: Mapped[int] = mapped_column(Integer, default=0)
    rain_adjustment_ci: Mapped[float | None] = mapped_column(Float, nullable=True)
    incident_validated: Mapped[int] = mapped_column(Integer, default=0)
    incident_adjustment_ci: Mapped[float | None] = mapped_column(Float, nullable=True)
    paired_samples: Mapped[int] = mapped_column(Integer, default=0)
    details_json: Mapped[str | None] = mapped_column(Text, nullable=True)

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(40), default="user", index=True)
    status: Mapped[str] = mapped_column(String(40), default="pending", index=True)
    is_primary_admin: Mapped[int] = mapped_column(Integer, default=0)
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

class UserPermission(Base):
    __tablename__ = "user_permissions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    permission: Mapped[str] = mapped_column(String(100), index=True)
    granted: Mapped[int] = mapped_column(Integer, default=1)
    granted_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

class AuthSession(Base):
    __tablename__ = "auth_sessions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    client_ip: Mapped[str | None] = mapped_column(String(80), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)

class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(120), index=True)
    resource_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    outcome: Mapped[str] = mapped_column(String(40), default="success")
    client_ip: Mapped[str | None] = mapped_column(String(80), nullable=True)
    details_json: Mapped[str | None] = mapped_column(Text, nullable=True)

class BenchmarkSource(Base):
    __tablename__ = "benchmark_sources"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    source_type: Mapped[str] = mapped_column(String(80))
    standard_alignment: Mapped[str | None] = mapped_column(String(300), nullable=True)
    independence_level: Mapped[str] = mapped_column(String(60), default="provider_reference")
    active: Mapped[int] = mapped_column(Integer, default=1)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

class ObservationValidation(Base):
    __tablename__ = "observation_validations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    observation_id: Mapped[int] = mapped_column(ForeignKey("traffic_observations.id"), index=True)
    benchmark_source_id: Mapped[int | None] = mapped_column(ForeignKey("benchmark_sources.id"), nullable=True)
    validated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    validation_status: Mapped[str] = mapped_column(String(80), index=True)
    reference_type: Mapped[str] = mapped_column(String(100))
    observed_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    reference_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    deviation_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    deviation_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    agreement_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    provenance_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    uncertainty_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    limitations: Mapped[str | None] = mapped_column(Text, nullable=True)


class HistoricalBackfillJob(Base):
    __tablename__ = "historical_backfill_jobs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("monitoring_locations.id"), index=True)
    provider: Mapped[str] = mapped_column(String(120), default="TomTom Traffic Stats")
    provider_job_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    requested_from: Mapped[datetime] = mapped_column(DateTime, index=True)
    requested_to: Mapped[datetime] = mapped_column(DateTime, index=True)
    status: Mapped[str] = mapped_column(String(40), default="pending", index=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_urls_json: Mapped[str | None] = mapped_column(Text, nullable=True)

class HistoricalTrafficSample(Base):
    __tablename__ = "historical_traffic_samples"
    __table_args__ = (Index("ix_hist_location_hour_provider", "location_id", "hour_start", "provider"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("monitoring_locations.id"), index=True)
    hour_start: Mapped[datetime] = mapped_column(DateTime, index=True)
    average_speed_kmh: Mapped[float | None] = mapped_column(Float, nullable=True)
    harmonic_average_speed_kmh: Mapped[float | None] = mapped_column(Float, nullable=True)
    median_speed_kmh: Mapped[float | None] = mapped_column(Float, nullable=True)
    reference_speed_kmh: Mapped[float | None] = mapped_column(Float, nullable=True)
    congestion_index: Mapped[float | None] = mapped_column(Float, nullable=True)
    average_travel_time_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    sample_size: Mapped[float | None] = mapped_column(Float, nullable=True)
    provider: Mapped[str] = mapped_column(String(120), default="TomTom Traffic Stats")
    provider_job_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    data_origin: Mapped[str] = mapped_column(String(60), default="historical_provider")
    provenance_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class ResearchSurveySession(Base):
    __tablename__ = "research_survey_sessions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    location_id: Mapped[int | None] = mapped_column(ForeignKey("monitoring_locations.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(180), index=True)
    operator: Mapped[str | None] = mapped_column(String(150), nullable=True)
    purpose: Mapped[str | None] = mapped_column(String(250), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="active", index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

class GNSSTrackPoint(Base):
    __tablename__ = "gnss_track_points"
    __table_args__ = (Index("ix_gnss_session_time", "session_id", "captured_at"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("research_survey_sessions.id"), index=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    altitude_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    accuracy_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    speed_mps: Mapped[float | None] = mapped_column(Float, nullable=True)
    heading_deg: Mapped[float | None] = mapped_column(Float, nullable=True)
    traffic_state: Mapped[str | None] = mapped_column(String(40), nullable=True)
    queue_length_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(60), default="browser_gnss")

class CorridorProbe(Base):
    __tablename__ = "corridor_probes"
    __table_args__ = (Index("ix_probe_location_seq", "location_id", "sequence_no"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("monitoring_locations.id"), index=True)
    sequence_no: Mapped[int] = mapped_column(Integer)
    chainage_m: Mapped[float] = mapped_column(Float)
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    source_geometry: Mapped[str] = mapped_column(String(80), default="provider_segment")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))


class CorridorProbeObservation(Base):
    __tablename__ = "corridor_probe_observations"
    __table_args__ = (
        Index("ix_probe_obs_probe_time", "probe_id", "observed_at"),
        Index("ix_probe_obs_location_time", "location_id", "observed_at"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    probe_id: Mapped[int] = mapped_column(ForeignKey("corridor_probes.id"), index=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("monitoring_locations.id"), index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    current_speed_kmh: Mapped[float | None] = mapped_column(Float, nullable=True)
    free_flow_speed_kmh: Mapped[float | None] = mapped_column(Float, nullable=True)
    congestion_index: Mapped[float | None] = mapped_column(Float, nullable=True)
    delay_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_travel_time_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    free_flow_travel_time_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    road_closed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    provider: Mapped[str] = mapped_column(String(80), default="TomTom Traffic API")
    provider_status: Mapped[str] = mapped_column(String(40), default="ok")
    error_category: Mapped[str | None] = mapped_column(String(80), nullable=True)
    raw_reference: Mapped[str | None] = mapped_column(Text, nullable=True)


class ArchiveServiceState(Base):
    __tablename__ = "archive_service_state"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    service_name: Mapped[str] = mapped_column(String(80), unique=True, default="autonomous_archive")
    mode: Mapped[str] = mapped_column(String(40), default="local")
    status: Mapped[str] = mapped_column(String(40), default="starting", index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    last_location_cycle_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_probe_cycle_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_backup_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_location_cycle_status: Mapped[str | None] = mapped_column(String(80), nullable=True)
    last_probe_cycle_status: Mapped[str | None] = mapped_column(String(80), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_location_cycles: Mapped[int] = mapped_column(Integer, default=0)
    total_probe_cycles: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False, "timeout": 30},
)

@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_connection, connection_record):
    # Safe for SQLite; improves concurrent web + collector reliability.
    try:
        cur=dbapi_connection.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()
    except Exception:
        pass
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

def init_database():
    DATABASE_DIR.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
