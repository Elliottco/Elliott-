from typing import Tuple

from fastapi import HTTPException


def parse_bbox(bbox: str) -> Tuple[float, float, float, float]:
    parts = bbox.split(",")
    if len(parts) != 4:
        raise HTTPException(status_code=400, detail="bbox must have 4 comma-separated numbers")
    try:
        min_lon, min_lat, max_lon, max_lat = [float(p) for p in parts]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="bbox contains invalid numbers") from exc

    if min_lon >= max_lon or min_lat >= max_lat:
        raise HTTPException(status_code=400, detail="bbox min values must be less than max values")
    if not (-180 <= min_lon <= 180 and -180 <= max_lon <= 180 and -90 <= min_lat <= 90 and -90 <= max_lat <= 90):
        raise HTTPException(status_code=400, detail="bbox out of range")
    return min_lon, min_lat, max_lon, max_lat


def bbox_area(min_lon: float, min_lat: float, max_lon: float, max_lat: float) -> float:
    return abs((max_lon - min_lon) * (max_lat - min_lat))
