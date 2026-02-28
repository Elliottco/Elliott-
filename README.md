# worldview-local

Local-only situational awareness dashboard (Palantir-ish MVP) built with free/public data sources and no paid APIs.

## Stack
- **Frontend:** Next.js (App Router) + MapLibre GL
- **Backend:** FastAPI + SQLAlchemy + GeoAlchemy2 + Shapely
- **DB:** Postgres + PostGIS
- **Orchestration:** Docker Compose

## Data Sources (all free/public)
- NWS / NOAA alerts + point forecast: `api.weather.gov`
- OpenSky states API (rate-limited free tier)
- OpenStreetMap Overpass API POIs
- OpenSeaMap seamark raster tiles
- User-uploaded CSV + GeoJSON
- Nominatim geocoding proxy (OSM)

## Prerequisites
- Docker + Docker Compose plugin installed

## Run (one command)
```bash
docker compose up --build
```

Services:
- Frontend: http://localhost:3000
- Backend: http://localhost:8000
- Postgres: localhost:5432

## Environment Variables
Configured in `docker-compose.yml`:
- `DATABASE_URL`
- `CORS_ORIGINS`
- `NEXT_PUBLIC_API_BASE`

## Features
- Full-screen map + left sidebar (~360px)
- Layer toggles:
  - imported data
  - NWS alerts
  - OpenSky flights
  - OSM POIs
  - OpenSeaMap seamarks overlay
- Geocode search + jump
- CSV + GeoJSON imports
- Entity inspector on click + copy JSON
- Time filtering on imported data
- Backend status badges with rate-limit/offline signals
- Refresh button to re-fetch live layers

## API Endpoints
- `GET /api/health`
- `GET /api/status`
- `GET /api/geocode?q=...`
- `GET /api/nws/alerts?bbox=minLon,minLat,maxLon,maxLat`
- `GET /api/nws/point?lat=..&lon=..`
- `GET /api/opensky/states?bbox=minLon,minLat,maxLon,maxLat`
- `GET /api/osm/pois?bbox=...&categories=...`
- `POST /api/ingest/csv`
- `POST /api/ingest/geojson`
- `GET /api/features?source=...&layer=...&bbox=...&time_start=...&time_end=...&limit=...`
- `GET /api/features/timespan?layer=...`

## Import sample data
Use included samples from `/samples`.

### CSV import
```bash
curl -X POST http://localhost:8000/api/ingest/csv \
  -F "file=@samples/sample_points.csv" \
  -F "source=sample" \
  -F "layer=sample_csv"
```

### GeoJSON import
```bash
curl -X POST http://localhost:8000/api/ingest/geojson \
  -F "file=@samples/sample_features.geojson" \
  -F "source=sample" \
  -F "layer=sample_geojson"
```

Then toggle `imports` on in UI and pan/zoom to the imported area.

## Troubleshooting
- **CORS issue:** make sure `CORS_ORIGINS=http://localhost:3000` in backend env.
- **Overpass errors/rate limits:** zoom in and retry; app caches responses and returns clear warnings.
- **OpenSky rate-limited:** app serves cached data for a cool-down period.
- **Nominatim throttling:** geocoder has caching and polite user-agent header; retry after a short wait.
- **No features shown:** verify bbox/location and layer toggles; imported points need `lat` and `lon` columns.
