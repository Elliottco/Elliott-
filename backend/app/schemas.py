from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class FeatureResponse(BaseModel):
    type: str = "Feature"
    geometry: dict[str, Any]
    properties: dict[str, Any]


class FeatureCollectionResponse(BaseModel):
    type: str = "FeatureCollection"
    features: list[FeatureResponse]


class StatusResponse(BaseModel):
    status: str
    detail: str | None = None
    last_updated: datetime | None = None


class IngestResponse(BaseModel):
    inserted: int
    layer: str
    source: str


class PointForecastResponse(BaseModel):
    point: dict[str, Any]
    forecast: dict[str, Any]
