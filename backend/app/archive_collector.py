
from __future__ import annotations

import asyncio
import os
import signal
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from sqlalchemy import select, func

from .config import settings
from .paths import DATA_ROOT
from .database import (
    init_database, SessionLocal, MonitoringLocation, TrafficObservation,
    CorridorProbe, CorridorProbeObservation, ArchiveServiceState
)
from .monitoring import monitoring_manager
from .corridor_intelligence import acquire_corridor_probe_evidence


SERVICE_NAME="autonomous_archive"


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _state(db):
    row=db.scalar(select(ArchiveServiceState).where(ArchiveServiceState.service_name==SERVICE_NAME))
    if not row:
        row=ArchiveServiceState(
            service_name=SERVICE_NAME,
            mode=os.environ.get("ITICAS_ARCHIVE_MODE","local"),
            status="starting",
            started_at=_utcnow(),
            heartbeat_at=_utcnow(),
        )
        db.add(row);db.commit();db.refresh(row)
    return row


def update_state(**values):
    with SessionLocal() as db:
        row=_state(db)
        for k,v in values.items():
            if hasattr(row,k): setattr(row,k,v)
        row.updated_at=_utcnow()
        db.commit()


def status_payload():
    with SessionLocal() as db:
        row=_state(db)
        active=db.scalar(select(func.count()).select_from(MonitoringLocation).where(MonitoringLocation.active==1)) or 0
        obs=db.scalar(select(func.count()).select_from(TrafficObservation)) or 0
        probes=db.scalar(select(func.count()).select_from(CorridorProbe)) or 0
        probe_obs=db.scalar(select(func.count()).select_from(CorridorProbeObservation).where(CorridorProbeObservation.provider_status=="ok")) or 0
        first_obs=db.scalar(select(func.min(TrafficObservation.observed_at)))
        last_obs=db.scalar(select(func.max(TrafficObservation.observed_at)))
        heartbeat=row.heartbeat_at
        age=( _utcnow()-heartbeat ).total_seconds() if heartbeat else None
        healthy=bool(heartbeat and age is not None and age <= max(120,int(settings.archive_heartbeat_seconds)*4))
        return {
            "service_name":row.service_name,
            "mode":row.mode,
            "status":row.status,
            "healthy":healthy,
            "heartbeat_at":heartbeat.isoformat() if heartbeat else None,
            "heartbeat_age_seconds":round(age,1) if age is not None else None,
            "last_location_cycle_at":row.last_location_cycle_at.isoformat() if row.last_location_cycle_at else None,
            "last_probe_cycle_at":row.last_probe_cycle_at.isoformat() if row.last_probe_cycle_at else None,
            "last_backup_at":row.last_backup_at.isoformat() if row.last_backup_at else None,
            "last_location_cycle_status":row.last_location_cycle_status,
            "last_probe_cycle_status":row.last_probe_cycle_status,
            "last_error":row.last_error,
            "total_location_cycles":row.total_location_cycles,
            "total_probe_cycles":row.total_probe_cycles,
            "active_monitoring_locations":active,
            "traffic_observations":obs,
            "corridor_probes":probes,
            "corridor_probe_observations":probe_obs,
            "archive_started_at":first_obs.isoformat() if first_obs else None,
            "latest_observation_at":last_obs.isoformat() if last_obs else None,
            "location_interval_seconds":int(settings.archive_location_interval_seconds),
            "probe_interval_seconds":int(settings.archive_probe_interval_seconds),
            "automatic":True,
            "scope_note":"Autonomous collection covers configured active monitoring locations and configured corridor probes. A road never registered for monitoring cannot be reconstructed retrospectively from ITICAS's own archive."
        }


def _sqlite_db_path():
    url=settings.database_url
    if not url.startswith("sqlite:///"):
        return None
    return Path(url[len("sqlite:///"):]).resolve()


def backup_database():
    source=_sqlite_db_path()
    if not source or not source.exists():
        return None
    backup_dir=DATA_ROOT/"backups"
    backup_dir.mkdir(parents=True,exist_ok=True)
    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target=backup_dir/f"iticas_archive_{stamp}.db"
    src=sqlite3.connect(str(source))
    dst=sqlite3.connect(str(target))
    try:
        src.backup(dst)
    finally:
        dst.close();src.close()
    cutoff=datetime.now(timezone.utc)-timedelta(days=max(1,int(settings.archive_backup_retention_days)))
    for p in backup_dir.glob("iticas_archive_*.db"):
        try:
            if datetime.fromtimestamp(p.stat().st_mtime,timezone.utc)<cutoff:
                p.unlink()
        except Exception:
            pass
    return str(target)


async def run_probe_cycle():
    with SessionLocal() as db:
        location_ids=list(db.scalars(
            select(CorridorProbe.location_id).distinct().order_by(CorridorProbe.location_id)
        ).all())
    ok=failed=0
    details=[]
    for lid in location_ids:
        try:
            result=await acquire_corridor_probe_evidence(int(lid))
            ok += int(result.get("successful",0))
            failed += int(result.get("failed",0))
            details.append({"location_id":lid,"status":result.get("status"),"successful":result.get("successful",0),"failed":result.get("failed",0)})
        except Exception as exc:
            failed += 1
            details.append({"location_id":lid,"status":"failed","error":str(exc)[:300]})
    return {"locations":len(location_ids),"successful_probe_requests":ok,"failed_probe_requests":failed,"details":details}


class AutonomousArchiveCollector:
    def __init__(self):
        self.stop_event=asyncio.Event()
        self.last_location=0.0
        self.last_probe=0.0
        self.last_backup=0.0

    def stop(self):
        self.stop_event.set()

    async def run(self):
        init_database()
        update_state(
            mode=os.environ.get("ITICAS_ARCHIVE_MODE","cloud" if os.environ.get("ITICAS_DATA_ROOT") else "local"),
            status="running",started_at=_utcnow(),heartbeat_at=_utcnow(),last_error=None
        )
        loop=asyncio.get_running_loop()
        now=loop.time()
        self.last_location=now-max(0,int(settings.archive_location_interval_seconds))
        self.last_probe=now-max(0,int(settings.archive_probe_interval_seconds))
        self.last_backup=now-max(0,int(settings.archive_backup_interval_hours)*3600)
        try:
            while not self.stop_event.is_set():
                now=loop.time()
                update_state(status="running",heartbeat_at=_utcnow())
                if settings.archive_collector_enabled and monitoring_manager.provider_configured():
                    if now-self.last_location >= max(60,int(settings.archive_location_interval_seconds)):
                        try:
                            res=await monitoring_manager.run_cycle(trigger="autonomous_archive")
                            with SessionLocal() as db:
                                row=_state(db); row.last_location_cycle_at=_utcnow(); row.last_location_cycle_status=res.get("status")
                                row.total_location_cycles=(row.total_location_cycles or 0)+1; row.last_error=None; db.commit()
                        except Exception as exc:
                            update_state(last_location_cycle_at=_utcnow(),last_location_cycle_status="failed",last_error=str(exc)[:2000])
                        self.last_location=loop.time()

                    if settings.archive_probe_collection_enabled and now-self.last_probe >= max(300,int(settings.archive_probe_interval_seconds)):
                        try:
                            res=await run_probe_cycle()
                            status="completed" if not res["failed_probe_requests"] else "completed_with_errors"
                            with SessionLocal() as db:
                                row=_state(db); row.last_probe_cycle_at=_utcnow(); row.last_probe_cycle_status=status
                                row.total_probe_cycles=(row.total_probe_cycles or 0)+1; row.last_error=None if status=="completed" else f"{res['failed_probe_requests']} probe requests failed"; db.commit()
                        except Exception as exc:
                            update_state(last_probe_cycle_at=_utcnow(),last_probe_cycle_status="failed",last_error=str(exc)[:2000])
                        self.last_probe=loop.time()

                    if now-self.last_backup >= max(3600,int(settings.archive_backup_interval_hours)*3600):
                        try:
                            backup_database()
                            update_state(last_backup_at=_utcnow())
                        except Exception as exc:
                            update_state(last_error=f"Backup: {exc}"[:2000])
                        self.last_backup=loop.time()

                try:
                    await asyncio.wait_for(self.stop_event.wait(),timeout=max(5,int(settings.archive_heartbeat_seconds)))
                except asyncio.TimeoutError:
                    pass
        finally:
            update_state(status="stopped",heartbeat_at=_utcnow())


async def run_forever():
    collector=AutonomousArchiveCollector()
    loop=asyncio.get_running_loop()
    for sig in (signal.SIGINT,signal.SIGTERM):
        try: loop.add_signal_handler(sig,collector.stop)
        except (NotImplementedError,RuntimeError): pass
    await collector.run()
