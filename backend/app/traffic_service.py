from datetime import datetime, timezone
from sqlalchemy import select
from .database import SessionLocal, MonitoringLocation, TrafficObservation, TrafficIncident
from .tomtom_traffic import TomTomTrafficClient, ProviderRequestError, ProviderNotConfigured
from .validation import validate_observation

class AcquisitionError(RuntimeError): pass
class LocationNotFound(AcquisitionError): pass
class MissingCoordinates(AcquisitionError): pass
class ProviderUnavailable(AcquisitionError): pass

async def acquire_location_traffic_data(location_id: int, provider_factory=TomTomTrafficClient):
    with SessionLocal() as db:
        location = db.get(MonitoringLocation, location_id)
        if not location:
            raise LocationNotFound("Location not found.")
        if location.latitude is None or location.longitude is None:
            raise MissingCoordinates("Location requires verified latitude and longitude before live traffic acquisition.")

        provider = provider_factory()
        if not provider.configured:
            raise ProviderUnavailable("TomTom Traffic API is not configured.")

        try:
            flow_payload = await provider.fetch_flow(location.latitude, location.longitude)
            incident_payload = await provider.fetch_incidents(location.latitude, location.longitude, location.radius_m)
        except (ProviderRequestError, ProviderNotConfigured) as exc:
            raise ProviderUnavailable(str(exc)) from exc

        observed_at = datetime.now(timezone.utc)
        flow_row = provider.normalize_flow(flow_payload, observed_at=observed_at)
        incident_rows = provider.normalize_incidents(incident_payload, observed_at=observed_at)

        observation_id = None
        if flow_row:
            observation = TrafficObservation(
                location_id=location.id,
                observed_at=observed_at,
                provider=provider.provider_name,
                **flow_row,
            )
            db.add(observation)
            db.flush()
            observation_id = observation.id

        new_incidents = 0
        for row in incident_rows:
            provider_id = row.get("provider_incident_id")
            existing = None
            if provider_id:
                existing = db.scalar(
                    select(TrafficIncident).where(
                        TrafficIncident.location_id == location.id,
                        TrafficIncident.provider == provider.provider_name,
                        TrafficIncident.provider_incident_id == provider_id,
                    )
                )
            if existing:
                for key, value in row.items():
                    setattr(existing, key, value)
            else:
                db.add(TrafficIncident(location_id=location.id, provider=provider.provider_name, **row))
                new_incidents += 1

        db.commit()
        validation_id = validate_observation(observation_id) if observation_id is not None else None
        return {
            "status": "ok",
            "provider": provider.provider_name,
            "location_id": location.id,
            "location": location.name,
            "city": location.city,
            "state": location.state,
            "observation_id": observation_id,
            "flow_observation_stored": 1 if observation_id is not None else 0,
            "validation_id": validation_id,
            "incidents_received": len(incident_rows),
            "new_incidents_stored": new_incidents,
        }
