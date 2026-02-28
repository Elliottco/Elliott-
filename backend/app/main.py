import csv
import io
import json
import os
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import Point, shape, mapping
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from .cache import cache
from .database import Base, engine, get_db
from .models import ImportedFeature
from .validators import bbox_area, parse_bbox

app = FastAPI(title="worldview-local API")

cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in cors_origins if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

Base.metadata.create_all(bind=engine)

USER_AGENT = "worldview-local/1.0 (local situational dashboard)"
OSM_CATEGORY_TAGS = {
    "gas": '["amenity"="fuel"]',
    "hospital": '["amenity"="hospital"]',
    "police": '["amenity"="police"]',
    "pharmacy": '["amenity"="pharmacy"]',
    "grocery": '["shop"="supermarket"]',
    "parking": '["amenity"="parking"]',
    "chargers": '["amenity"="charging_station"]',
    "shelter": '["amenity"="shelter"]',
    "banks": '["amenity"~"bank|atm"]',
}


@app.get("/api/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"ok": True}


@app.get("/api/status")
def status():
    statuses = {}
    for name in ["opensky", "nominatim", "overpass", "nws_alerts"]:
        entry = cache.get(f"status:{name}")
        statuses[name] = entry.value if entry else {"status": "unknown", "detail": "No requests yet"}
    return statuses


async def fetch_json_with_status(url: str, service: str, headers: dict[str, str] | None = None, timeout: int = 20):
    headers = headers or {}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url, headers=headers)
        if response.status_code in (429, 503):
            cache.set(f"status:{service}", {"status": "rate_limited", "detail": f"HTTP {response.status_code}"}, 120)
            return None, response.status_code
        response.raise_for_status()
        cache.set(f"status:{service}", {"status": "ok", "detail": "Healthy", "last_updated": datetime.now(timezone.utc).isoformat()}, 120)
        return response.json(), 200
    except Exception as exc:
        cache.set(f"status:{service}", {"status": "offline", "detail": str(exc)}, 120)
        return None, 500


@app.get("/api/geocode")
async def geocode(q: str = Query(min_length=2, max_length=120)):
    key = f"geocode:{q.lower().strip()}"
    cached = cache.get(key)
    if cached:
        return {"results": cached.value, "cached": True}

    data, code = await fetch_json_with_status(
        f"https://nominatim.openstreetmap.org/search?format=jsonv2&limit=5&q={httpx.QueryParams({'q': q})['q']}",
        service="nominatim",
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    if data is None:
        stale = cache.get(key)
        if stale:
            return {"results": stale.value, "cached": True, "warning": "Rate limited – serving cached"}
        raise HTTPException(status_code=code if code != 500 else 502, detail="Geocoder unavailable")

    results = [{"display_name": r.get("display_name"), "lat": float(r["lat"]), "lon": float(r["lon"])} for r in data]
    cache.set(key, results, 3600)
    return {"results": results, "cached": False}


@app.get("/api/nws/alerts")
async def nws_alerts(bbox: str = Query(...)):
    min_lon, min_lat, max_lon, max_lat = parse_bbox(bbox)
    area = bbox_area(min_lon, min_lat, max_lon, max_lat)
    if area > 4000:
        raise HTTPException(status_code=400, detail="BBox too large for alerts; zoom in")

    key = f"nws_alerts:{bbox}"
    cached = cache.get(key)
    if cached:
        return {"data": cached.value, "cached": True}

    data, code = await fetch_json_with_status("https://api.weather.gov/alerts/active", "nws_alerts", {"User-Agent": USER_AGENT})
    if data is None:
        if cached:
            return {"data": cached.value, "cached": True, "warning": "Rate limited – serving cached"}
        raise HTTPException(status_code=code if code != 500 else 502, detail="NWS alerts unavailable")

    features = []
    for feat in data.get("features", []):
        geom = feat.get("geometry")
        props = feat.get("properties", {})
        if geom:
            try:
                g = shape(geom)
                if g.bounds[2] < min_lon or g.bounds[0] > max_lon or g.bounds[3] < min_lat or g.bounds[1] > max_lat:
                    continue
                features.append({"type": "Feature", "geometry": geom, "properties": props})
            except Exception:
                continue
        else:
            geocode = props.get("geocode", {})
            area_desc = props.get("areaDesc")
            if area_desc:
                centroid = Point((min_lon + max_lon) / 2, (min_lat + max_lat) / 2)
                features.append({"type": "Feature", "geometry": mapping(centroid), "properties": props})

    out = {"type": "FeatureCollection", "features": features}
    cache.set(key, out, 300)
    return {"data": out, "cached": False}


@app.get("/api/nws/point")
async def nws_point(lat: float = Query(..., ge=-90, le=90), lon: float = Query(..., ge=-180, le=180)):
    points_url = f"https://api.weather.gov/points/{lat},{lon}"
    point_data, code = await fetch_json_with_status(points_url, "nws_point", {"User-Agent": USER_AGENT})
    if point_data is None:
        raise HTTPException(status_code=code if code != 500 else 502, detail="NWS point lookup unavailable")
    forecast_url = point_data.get("properties", {}).get("forecast")
    if not forecast_url:
        raise HTTPException(status_code=502, detail="NWS did not return forecast URL")
    forecast_data, code = await fetch_json_with_status(forecast_url, "nws_forecast", {"User-Agent": USER_AGENT})
    if forecast_data is None:
        raise HTTPException(status_code=code if code != 500 else 502, detail="NWS forecast unavailable")

    simplified = {
        "point": {
            "gridId": point_data.get("properties", {}).get("gridId"),
            "gridX": point_data.get("properties", {}).get("gridX"),
            "gridY": point_data.get("properties", {}).get("gridY"),
        },
        "forecast": forecast_data.get("properties", {}).get("periods", [])[:6],
    }
    return simplified


@app.get("/api/opensky/states")
async def opensky_states(bbox: str = Query(...)):
    min_lon, min_lat, max_lon, max_lat = parse_bbox(bbox)
    key = f"opensky:{bbox}"
    cached = cache.get(key)
    rate_lock = cache.get("opensky:rate_lock")
    if cached and not rate_lock:
        return {"data": cached.value, "cached": True}

    if rate_lock and cached:
        return {"data": cached.value, "cached": True, "warning": "Rate limited – serving cached"}

    url = f"https://opensky-network.org/api/states/all?lamin={min_lat}&lamax={max_lat}&lomin={min_lon}&lomax={max_lon}"
    data, code = await fetch_json_with_status(url, "opensky", {"User-Agent": USER_AGENT})
    if data is None:
        cache.set("opensky:rate_lock", True, 30)
        if cached:
            return {"data": cached.value, "cached": True, "warning": "Rate limited – serving cached"}
        raise HTTPException(status_code=code if code != 500 else 502, detail="OpenSky unavailable")

    features = []
    for state in data.get("states", []) or []:
        lon, lat = state[5], state[6]
        if lon is None or lat is None:
            continue
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {
                    "icao24": state[0],
                    "callsign": (state[1] or "").strip(),
                    "origin_country": state[2],
                    "baro_altitude": state[7],
                    "velocity": state[9],
                    "heading": state[10],
                },
            }
        )

    out = {"type": "FeatureCollection", "features": features}
    cache.set(key, out, 20)
    return {"data": out, "cached": False}


@app.get("/api/osm/pois")
async def osm_pois(bbox: str = Query(...), categories: str = "gas,hospital,police,pharmacy"):
    min_lon, min_lat, max_lon, max_lat = parse_bbox(bbox)
    if bbox_area(min_lon, min_lat, max_lon, max_lat) > 25:
        raise HTTPException(status_code=400, detail="BBox too large for Overpass POI query; zoom in")

    category_list = [c.strip() for c in categories.split(",") if c.strip()]
    unknown = [c for c in category_list if c not in OSM_CATEGORY_TAGS]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown categories: {', '.join(unknown)}")

    key = f"osm:{bbox}:{','.join(sorted(category_list))}"
    cached = cache.get(key)
    if cached:
        return {"data": cached.value, "cached": True}

    query_parts = []
    for cat in category_list:
        tag = OSM_CATEGORY_TAGS[cat]
        query_parts.append(f"node{tag}({min_lat},{min_lon},{max_lat},{max_lon});")
        query_parts.append(f"way{tag}({min_lat},{min_lon},{max_lat},{max_lon});")
    query = f"[out:json][timeout:20];({''.join(query_parts)});out center tags;"

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post("https://overpass-api.de/api/interpreter", data=query, headers={"User-Agent": USER_AGENT})
        if resp.status_code in (429, 503, 504):
            cache.set("status:overpass", {"status": "rate_limited", "detail": f"HTTP {resp.status_code}"}, 120)
            if cached:
                return {"data": cached.value, "cached": True, "warning": "Rate limited – serving cached"}
            raise HTTPException(status_code=429, detail="Overpass rate-limited; try again later")
        resp.raise_for_status()
        cache.set("status:overpass", {"status": "ok", "detail": "Healthy", "last_updated": datetime.now(timezone.utc).isoformat()}, 120)
        data = resp.json()
    except HTTPException:
        raise
    except Exception as exc:
        cache.set("status:overpass", {"status": "offline", "detail": str(exc)}, 120)
        if cached:
            return {"data": cached.value, "cached": True, "warning": "Overpass unavailable – serving cached"}
        raise HTTPException(status_code=502, detail="Overpass unavailable")

    features = []
    for el in data.get("elements", []):
        lon = el.get("lon") or el.get("center", {}).get("lon")
        lat = el.get("lat") or el.get("center", {}).get("lat")
        if lon is None or lat is None:
            continue
        tags = el.get("tags", {})
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {
                    "osm_id": el.get("id"),
                    "osm_type": el.get("type"),
                    "name": tags.get("name"),
                    **tags,
                },
            }
        )

    out = {"type": "FeatureCollection", "features": features}
    cache.set(key, out, 120)
    return {"data": out, "cached": False}


def parse_timestamp(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


@app.post("/api/ingest/csv")
async def ingest_csv(
    file: UploadFile = File(...),
    source: str = Form("user"),
    layer: str = Form("csv_import"),
    db: Session = Depends(get_db),
):
    raw = await file.read()
    stream = io.StringIO(raw.decode("utf-8"))
    reader = csv.DictReader(stream)
    inserted = 0
    for row in reader:
        try:
            lat = float(row.get("lat", ""))
            lon = float(row.get("lon", ""))
        except ValueError:
            continue
        name = row.get("name")
        timestamp = parse_timestamp(row.get("timestamp"))
        props = {k: v for k, v in row.items() if k not in {"lat", "lon"}}
        if name:
            props["name"] = name
        geom = from_shape(Point(lon, lat), srid=4326)
        db.add(ImportedFeature(source=source, layer=layer, geometry=geom, properties=props, timestamp=timestamp))
        inserted += 1
    db.commit()
    return {"inserted": inserted, "source": source, "layer": layer}


@app.post("/api/ingest/geojson")
async def ingest_geojson(
    file: UploadFile = File(...),
    source: str = Form("user"),
    layer: str = Form("geojson_import"),
    db: Session = Depends(get_db),
):
    raw = await file.read()
    payload = json.loads(raw)
    features = payload.get("features", []) if payload.get("type") == "FeatureCollection" else []
    inserted = 0
    for feature in features:
        geom_json = feature.get("geometry")
        if not geom_json:
            continue
        geom_shape = shape(geom_json)
        props = feature.get("properties", {}) or {}
        timestamp = parse_timestamp(props.get("timestamp"))
        db.add(
            ImportedFeature(
                source=source,
                layer=layer,
                geometry=from_shape(geom_shape, srid=4326),
                properties=props,
                timestamp=timestamp,
            )
        )
        inserted += 1
    db.commit()
    return {"inserted": inserted, "source": source, "layer": layer}


@app.get("/api/features")
def get_features(
    source: str | None = None,
    layer: str | None = None,
    bbox: str | None = None,
    time_start: str | None = None,
    time_end: str | None = None,
    limit: int = Query(1000, ge=1, le=10000),
    db: Session = Depends(get_db),
):
    stmt = select(ImportedFeature).limit(limit)
    if source:
        stmt = stmt.where(ImportedFeature.source == source)
    if layer:
        stmt = stmt.where(ImportedFeature.layer == layer)
    if time_start:
        ts = parse_timestamp(time_start)
        if ts:
            stmt = stmt.where(ImportedFeature.timestamp >= ts)
    if time_end:
        te = parse_timestamp(time_end)
        if te:
            stmt = stmt.where(ImportedFeature.timestamp <= te)
    if bbox:
        min_lon, min_lat, max_lon, max_lat = parse_bbox(bbox)
        envelope = func.ST_MakeEnvelope(min_lon, min_lat, max_lon, max_lat, 4326)
        stmt = stmt.where(func.ST_Intersects(ImportedFeature.geometry, envelope))

    rows = db.execute(stmt).scalars().all()
    features = []
    for row in rows:
        geom = mapping(to_shape(row.geometry))
        props = row.properties or {}
        props.update({"id": row.id, "source": row.source, "layer": row.layer})
        if row.timestamp:
            props["timestamp"] = row.timestamp.isoformat()
        features.append({"type": "Feature", "geometry": geom, "properties": props})

    return {"type": "FeatureCollection", "features": features}


@app.get("/api/features/timespan")
def feature_timespan(layer: str | None = None, db: Session = Depends(get_db)):
    stmt = select(func.min(ImportedFeature.timestamp), func.max(ImportedFeature.timestamp)).where(ImportedFeature.timestamp.is_not(None))
    if layer:
        stmt = stmt.where(ImportedFeature.layer == layer)
    min_ts, max_ts = db.execute(stmt).one()
    return {"min": min_ts.isoformat() if min_ts else None, "max": max_ts.isoformat() if max_ts else None}
