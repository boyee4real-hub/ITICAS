from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field, model_validator

class LocationCreate(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    road_name: str | None = Field(default=None, max_length=200)
    city: str | None = Field(default=None, max_length=120)
    state: str = Field(min_length=2, max_length=120)
    country: Literal["Nigeria"] = "Nigeria"
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    radius_m: int = Field(default=1000, ge=100, le=10000)
    active: bool = True

    @model_validator(mode="after")
    def validate_coordinate_pair(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Latitude and longitude must be supplied together.")
        return self

class LocationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=150)
    road_name: str | None = Field(default=None, max_length=200)
    city: str | None = Field(default=None, max_length=120)
    state: str | None = Field(default=None, min_length=2, max_length=120)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    radius_m: int | None = Field(default=None, ge=100, le=10000)
    active: bool | None = None


class TrafficPointEvaluationRequest(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    radius_m: int = Field(default=1500, ge=100, le=10000)
    label: str | None = Field(default=None, max_length=250)

class LocationFromSearch(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    road_name: str | None = Field(default=None, max_length=200)
    city: str | None = Field(default=None, max_length=120)
    state: str = Field(min_length=2, max_length=120)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    radius_m: int = Field(default=1000, ge=100, le=10000)
    search_query: str | None = Field(default=None, max_length=300)


class ResearchSurveyCreate(BaseModel):
    name: str = Field(min_length=2, max_length=180)
    location_id: int | None = None
    operator: str | None = Field(default=None, max_length=150)
    purpose: str | None = Field(default=None, max_length=250)
    notes: str | None = Field(default=None, max_length=2000)

class GNSSTrackPointCreate(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    altitude_m: float | None = None
    accuracy_m: float | None = Field(default=None, ge=0)
    speed_mps: float | None = Field(default=None, ge=0)
    heading_deg: float | None = Field(default=None, ge=0, le=360)
    traffic_state: str | None = Field(default=None, max_length=40)
    queue_length_m: float | None = Field(default=None, ge=0)
    notes: str | None = Field(default=None, max_length=1000)
    captured_at: datetime | None = None
