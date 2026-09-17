from __future__ import annotations
import json
from sqlalchemy import select
from .database import SessionLocal, TrafficObservation, BenchmarkSource, ObservationValidation

BENCHMARK_CODE = "tomtom-freeflow-reference"

def ensure_benchmark_sources():
    with SessionLocal() as db:
        source = db.scalar(select(BenchmarkSource).where(BenchmarkSource.code == BENCHMARK_CODE))
        if not source:
            db.add(BenchmarkSource(
                code=BENCHMARK_CODE,
                name="TomTom Traffic API free-flow reference",
                source_type="established_provider_reference",
                standard_alignment="OGC SensorThings API / OGC Observations, Measurements and Samples metadata alignment",
                independence_level="provider_reference",
                notes=(
                    "Operational benchmark relationship using TomTom free-flow values. "
                    "This is not an independent provider validation; ITICAS exposes that limitation explicitly."
                ),
            ))
            db.commit()

def validate_observation(observation_id: int) -> int | None:
    ensure_benchmark_sources()
    with SessionLocal() as db:
        obs = db.get(TrafficObservation, observation_id)
        if not obs:
            return None
        existing = db.scalar(
            select(ObservationValidation).where(ObservationValidation.observation_id == observation_id)
        )
        if existing:
            return existing.id

        source = db.scalar(select(BenchmarkSource).where(BenchmarkSource.code == BENCHMARK_CODE))
        observed = obs.current_speed_kmh
        reference = obs.free_flow_speed_kmh
        deviation = None
        deviation_pct = None
        agreement = None
        if observed is not None and reference not in (None, 0):
            deviation = observed - reference
            deviation_pct = (deviation / reference) * 100.0
            agreement = max(0.0, min(1.0, observed / reference))

        confidence = obs.confidence
        status = "provider_reference_validated" if reference is not None and observed is not None else "insufficient_reference_data"
        limitations = (
            "Current validation compares the live observation with the established provider's free-flow reference. "
            "It is a provider-reference benchmark, not an independent traffic-provider ground truth. "
            "Independent benchmark adapters are supported by the schema and must be used when a scientifically suitable "
            "Nigeria-wide reference source is available."
        )
        row = ObservationValidation(
            observation_id=obs.id,
            benchmark_source_id=source.id if source else None,
            validation_status=status,
            reference_type="free_flow_speed",
            observed_value=observed,
            reference_value=reference,
            deviation_value=deviation,
            deviation_percent=deviation_pct,
            agreement_score=agreement,
            source_confidence=confidence,
            provenance_json=json.dumps({
                "primary_provider": obs.provider,
                "reference_source": source.name if source else None,
                "standard_alignment": source.standard_alignment if source else None,
                "independence_level": source.independence_level if source else "provider_reference",
            }),
            uncertainty_json=json.dumps({
                "provider_confidence": confidence,
                "independent_benchmark_configured": False,
            }),
            limitations=limitations,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id

def validation_payload(observation_id: int):
    ensure_benchmark_sources()
    with SessionLocal() as db:
        row = db.scalar(
            select(ObservationValidation).where(ObservationValidation.observation_id == observation_id)
            .order_by(ObservationValidation.id.desc())
        )
        if not row:
            return {
                "validation_status": "not_yet_validated",
                "independent_benchmark_configured": False,
                "standard_alignment": "OGC SensorThings API / OGC Observations, Measurements and Samples",
            }
        source = db.get(BenchmarkSource, row.benchmark_source_id) if row.benchmark_source_id else None
        return {
            "validation_status": row.validation_status,
            "benchmark_source": source.name if source else None,
            "benchmark_type": source.source_type if source else None,
            "independence_level": source.independence_level if source else None,
            "reference_type": row.reference_type,
            "observed_value": row.observed_value,
            "reference_value": row.reference_value,
            "deviation_value": row.deviation_value,
            "deviation_percent": row.deviation_percent,
            "agreement_score": row.agreement_score,
            "source_confidence": row.source_confidence,
            "validated_at": row.validated_at.isoformat() if row.validated_at else None,
            "standard_alignment": source.standard_alignment if source else None,
            "independent_benchmark_configured": False,
            "limitations": row.limitations,
        }
