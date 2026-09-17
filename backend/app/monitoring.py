from __future__ import annotations
import asyncio
from datetime import datetime, timezone
from sqlalchemy import select, func

from .config import settings
from .database import SessionLocal, MonitoringLocation, MonitoringRun, MonitoringRunItem
from .tomtom_traffic import TomTomTrafficClient
from .traffic_service import acquire_location_traffic_data

class MonitoringManager:
    def __init__(self, acquire_func=acquire_location_traffic_data):
        self.acquire_func = acquire_func
        self._loop_task: asyncio.Task | None = None
        self._cycle_task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._cycle_lock = asyncio.Lock()
        self._last_error: str | None = None

    @property
    def running(self):
        return bool(self._loop_task and not self._loop_task.done())

    @property
    def cycle_running(self):
        return bool(self._cycle_task and not self._cycle_task.done()) or self._cycle_lock.locked()

    def provider_configured(self):
        return TomTomTrafficClient().configured

    async def start(self):
        if self.running:
            return
        self._stop_event = asyncio.Event()
        self._loop_task = asyncio.create_task(self._loop(), name="iticas-national-monitor")

    async def stop(self):
        self._stop_event.set()
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
        if self._cycle_task and not self._cycle_task.done():
            self._cycle_task.cancel()
            try:
                await self._cycle_task
            except asyncio.CancelledError:
                pass
        self._loop_task = None
        self._cycle_task = None

    async def _loop(self):
        try:
            delay = max(0, int(settings.monitoring_startup_delay_seconds))
            if delay:
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=delay)
                    return
                except asyncio.TimeoutError:
                    pass

            while not self._stop_event.is_set():
                if settings.monitoring_enabled and self.provider_configured():
                    try:
                        await self.run_cycle(trigger="scheduled")
                        self._last_error = None
                    except Exception as exc:
                        self._last_error = str(exc)

                interval = max(60, int(settings.monitoring_interval_seconds))
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=interval)
                except asyncio.TimeoutError:
                    pass
        except asyncio.CancelledError:
            raise

    def trigger_now(self):
        if self.cycle_running:
            return False
        self._cycle_task = asyncio.create_task(self.run_cycle(trigger="manual"), name="iticas-monitor-now")
        return True

    async def run_cycle(self, trigger="scheduled"):
        if self._cycle_lock.locked():
            return {"status": "busy", "message": "A monitoring cycle is already running."}
        async with self._cycle_lock:
            provider = TomTomTrafficClient()
            if not provider.configured:
                raise RuntimeError("TomTom Traffic API is not configured.")

            started = datetime.now(timezone.utc)
            with SessionLocal() as db:
                active_rows = db.scalars(
                    select(MonitoringLocation)
                    .where(MonitoringLocation.active == 1)
                    .order_by(MonitoringLocation.state, MonitoringLocation.city, MonitoringLocation.name)
                ).all()
                eligible = [x for x in active_rows if x.latitude is not None and x.longitude is not None]
                run = MonitoringRun(
                    started_at=started,
                    trigger=trigger,
                    status="running",
                    total_active_locations=len(active_rows),
                    eligible_locations=len(eligible),
                    skipped_locations=len(active_rows)-len(eligible),
                    provider=provider.provider_name,
                )
                db.add(run)
                db.commit()
                db.refresh(run)
                run_id = run.id
                location_ids = [x.id for x in eligible]

            succeeded = failed = attempted = 0
            for i, location_id in enumerate(location_ids):
                item_started = datetime.now(timezone.utc)
                with SessionLocal() as db:
                    item = MonitoringRunItem(
                        run_id=run_id,
                        location_id=location_id,
                        started_at=item_started,
                        status="running",
                    )
                    db.add(item)
                    db.commit()
                    db.refresh(item)
                    item_id = item.id

                attempted += 1
                try:
                    result = await self.acquire_func(location_id)
                    succeeded += 1
                    with SessionLocal() as db:
                        item = db.get(MonitoringRunItem, item_id)
                        item.finished_at = datetime.now(timezone.utc)
                        item.status = "success"
                        item.observation_id = result.get("observation_id")
                        item.incidents_received = result.get("incidents_received", 0)
                        item.new_incidents_stored = result.get("new_incidents_stored", 0)
                        db.commit()
                except Exception as exc:
                    failed += 1
                    with SessionLocal() as db:
                        item = db.get(MonitoringRunItem, item_id)
                        item.finished_at = datetime.now(timezone.utc)
                        item.status = "failed"
                        item.error_message = str(exc)[:2000]
                        db.commit()

                if i < len(location_ids)-1:
                    await asyncio.sleep(max(0.0, float(settings.monitoring_inter_location_delay_seconds)))

            with SessionLocal() as db:
                run = db.get(MonitoringRun, run_id)
                run.finished_at = datetime.now(timezone.utc)
                run.attempted_locations = attempted
                run.successful_locations = succeeded
                run.failed_locations = failed
                run.status = "completed" if failed == 0 else "completed_with_errors"
                run.message = f"{succeeded} successful, {failed} failed, {run.skipped_locations} skipped without coordinates."
                db.commit()

            return {
                "status": "completed" if failed == 0 else "completed_with_errors",
                "run_id": run_id,
                "attempted": attempted,
                "successful": succeeded,
                "failed": failed,
            }

    def status(self):
        with SessionLocal() as db:
            total_active = db.scalar(select(func.count()).select_from(MonitoringLocation).where(MonitoringLocation.active == 1)) or 0
            eligible = db.scalar(
                select(func.count()).select_from(MonitoringLocation).where(
                    MonitoringLocation.active == 1,
                    MonitoringLocation.latitude.is_not(None),
                    MonitoringLocation.longitude.is_not(None),
                )
            ) or 0
            last = db.scalar(select(MonitoringRun).order_by(MonitoringRun.id.desc()))
            return {
                "scope": "Nigeria",
                "enabled": bool(settings.monitoring_enabled),
                "provider_configured": self.provider_configured(),
                "scheduler_running": self.running,
                "cycle_running": self.cycle_running,
                "interval_seconds": max(60, int(settings.monitoring_interval_seconds)),
                "active_locations": total_active,
                "eligible_locations": eligible,
                "locations_without_coordinates": total_active - eligible,
                "last_error": self._last_error,
                "last_run": None if not last else {
                    "id": last.id,
                    "started_at": last.started_at.isoformat() if last.started_at else None,
                    "finished_at": last.finished_at.isoformat() if last.finished_at else None,
                    "trigger": last.trigger,
                    "status": last.status,
                    "attempted": last.attempted_locations,
                    "successful": last.successful_locations,
                    "failed": last.failed_locations,
                    "skipped": last.skipped_locations,
                    "message": last.message,
                },
            }

monitoring_manager = MonitoringManager()
