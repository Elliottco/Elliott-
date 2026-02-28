'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import maplibregl, { GeoJSONSource, LngLatBoundsLike, Map } from 'maplibre-gl';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:8000';
const defaultCategories = 'gas,hospital,police,pharmacy,grocery,parking,chargers,shelter,banks';

type StatusMap = Record<string, { status: string; detail?: string }>;

export default function DashboardPage() {
  const mapRef = useRef<Map | null>(null);
  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const [bbox, setBbox] = useState<string>('');
  const [search, setSearch] = useState('');
  const [statuses, setStatuses] = useState<StatusMap>({});
  const [selected, setSelected] = useState<any>(null);
  const [timeStart, setTimeStart] = useState('');
  const [timeEnd, setTimeEnd] = useState('');
  const [refreshToken, setRefreshToken] = useState(0);

  const [layers, setLayers] = useState({
    imports: true,
    nwsAlerts: false,
    flights: false,
    pois: false,
    seamarks: false
  });

  const bboxToBounds = (b: string): LngLatBoundsLike | null => {
    const p = b.split(',').map(Number);
    if (p.length !== 4 || p.some(Number.isNaN)) return null;
    return [[p[0], p[1]], [p[2], p[3]]];
  };

  useEffect(() => {
    if (!mapContainerRef.current || mapRef.current) return;

    const map = new maplibregl.Map({
      container: mapContainerRef.current,
      style: 'https://demotiles.maplibre.org/style.json',
      center: [-98.58, 39.82],
      zoom: 4
    });

    map.addControl(new maplibregl.NavigationControl(), 'top-right');
    map.on('load', () => {
      map.addSource('imports', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
      map.addLayer({ id: 'imports-fill', type: 'fill', source: 'imports', filter: ['==', ['geometry-type'], 'Polygon'], paint: { 'fill-color': '#34d399', 'fill-opacity': 0.25 } });
      map.addLayer({ id: 'imports-line', type: 'line', source: 'imports', filter: ['==', ['geometry-type'], 'LineString'], paint: { 'line-color': '#10b981', 'line-width': 2 } });
      map.addLayer({ id: 'imports-circle', type: 'circle', source: 'imports', filter: ['==', ['geometry-type'], 'Point'], paint: { 'circle-radius': 5, 'circle-color': '#34d399' } });

      map.addSource('alerts', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
      map.addLayer({ id: 'alerts-fill', type: 'fill', source: 'alerts', paint: { 'fill-color': '#f97316', 'fill-opacity': 0.2 } });
      map.addLayer({ id: 'alerts-line', type: 'line', source: 'alerts', paint: { 'line-color': '#f97316', 'line-width': 2 } });

      map.addSource('flights', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
      map.addLayer({ id: 'flights-circle', type: 'circle', source: 'flights', paint: { 'circle-radius': 4, 'circle-color': '#60a5fa' } });

      map.addSource('pois', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
      map.addLayer({ id: 'pois-circle', type: 'circle', source: 'pois', paint: { 'circle-radius': 4, 'circle-color': '#eab308' } });

      map.addSource('seamarks', { type: 'raster', tiles: ['https://tiles.openseamap.org/seamark/{z}/{x}/{y}.png'], tileSize: 256 });
      map.addLayer({ id: 'seamarks-raster', type: 'raster', source: 'seamarks', paint: { 'raster-opacity': 0.7 }, layout: { visibility: 'none' } });

      ['imports-circle','imports-line','imports-fill','alerts-fill','alerts-line','flights-circle','pois-circle'].forEach((id) => {
        map.on('click', id, (e) => {
          const feature = e.features?.[0];
          if (feature) setSelected(feature.properties || {});
        });
      });

      const updateBbox = () => {
        const b = map.getBounds();
        setBbox(`${b.getWest().toFixed(5)},${b.getSouth().toFixed(5)},${b.getEast().toFixed(5)},${b.getNorth().toFixed(5)}`);
      };
      updateBbox();
      map.on('moveend', updateBbox);
    });

    mapRef.current = map;
    return () => map.remove();
  }, []);

  const loadLayer = async (name: string, path: string, sourceId: string) => {
    if (!bbox || !mapRef.current) return;
    try {
      const res = await fetch(`${API_BASE}${path}`);
      const json = await res.json();
      const data = json.data || json;
      const src = mapRef.current.getSource(sourceId) as GeoJSONSource;
      src?.setData(data);
      if (json.warning) console.warn(json.warning);
    } catch (err) {
      console.error(name, err);
    }
  };

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !bbox) return;
    const vis = (ids: string[], on: boolean) => ids.forEach((id) => map.setLayoutProperty(id, 'visibility', on ? 'visible' : 'none'));
    vis(['imports-circle','imports-line','imports-fill'], layers.imports);
    vis(['alerts-fill','alerts-line'], layers.nwsAlerts);
    vis(['flights-circle'], layers.flights);
    vis(['pois-circle'], layers.pois);
    map.setLayoutProperty('seamarks-raster', 'visibility', layers.seamarks ? 'visible' : 'none');

    if (layers.imports) loadLayer('imports', `/api/features?bbox=${bbox}&time_start=${timeStart}&time_end=${timeEnd}&limit=5000`, 'imports');
    if (layers.nwsAlerts) loadLayer('alerts', `/api/nws/alerts?bbox=${bbox}`, 'alerts');
    if (layers.flights) loadLayer('flights', `/api/opensky/states?bbox=${bbox}`, 'flights');
    if (layers.pois) loadLayer('pois', `/api/osm/pois?bbox=${bbox}&categories=${defaultCategories}`, 'pois');
  }, [layers, bbox, refreshToken, timeStart, timeEnd]);

  useEffect(() => {
    fetch(`${API_BASE}/api/status`).then((r) => r.json()).then(setStatuses).catch(() => undefined);
  }, [refreshToken]);

  const doSearch = async () => {
    if (!search.trim()) return;
    const res = await fetch(`${API_BASE}/api/geocode?q=${encodeURIComponent(search)}`);
    const json = await res.json();
    const first = json.results?.[0];
    if (!first || !mapRef.current) return;
    mapRef.current.flyTo({ center: [first.lon, first.lat], zoom: 11 });
  };

  const importFile = async (endpoint: string, file?: File | null) => {
    if (!file) return;
    const fd = new FormData();
    fd.append('file', file);
    await fetch(`${API_BASE}${endpoint}`, { method: 'POST', body: fd });
    setRefreshToken((x) => x + 1);
  };

  const statusBadges = useMemo(() => Object.entries(statuses), [statuses]);

  return (
    <div className="app-shell">
      <div className="sidebar">
        <h2>worldview-local</h2>
        <div className="section">
          <h3>Service Status</h3>
          {statusBadges.map(([key, value]) => (
            <div key={key} className="small"><span className={`badge ${value.status || 'unknown'}`}>{value.status || 'unknown'}</span>{key}</div>
          ))}
        </div>

        <div className="section">
          <h3>Search + Jump</h3>
          <div className="row"><input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="City, address, lat/lon" /></div>
          <button onClick={doSearch}>Jump to</button>
        </div>

        <div className="section">
          <h3>Layer Toggles</h3>
          {Object.entries(layers).map(([key, val]) => (
            <div className="row" key={key}>
              <label>{key}</label>
              <input type="checkbox" checked={val} onChange={(e) => setLayers((s) => ({ ...s, [key]: e.target.checked }))} />
            </div>
          ))}
          <button onClick={() => setRefreshToken((x) => x + 1)}>Refresh now</button>
        </div>

        <div className="section">
          <h3>Import Data</h3>
          <div className="row">
            <input type="file" accept=".csv" onChange={(e) => importFile('/api/ingest/csv', e.target.files?.[0])} />
          </div>
          <div className="row">
            <input type="file" accept=".geojson,.json" onChange={(e) => importFile('/api/ingest/geojson', e.target.files?.[0])} />
          </div>
        </div>

        <div className="section">
          <h3>Time Filter (imports)</h3>
          <div className="row"><input type="datetime-local" value={timeStart} onChange={(e) => setTimeStart(e.target.value)} /></div>
          <div className="row"><input type="datetime-local" value={timeEnd} onChange={(e) => setTimeEnd(e.target.value)} /></div>
        </div>

        <div className="section">
          <h3>Entity Inspector</h3>
          <div className="inspector">{selected ? JSON.stringify(selected, null, 2) : 'Click a feature to inspect.'}</div>
          <button disabled={!selected} onClick={() => navigator.clipboard.writeText(JSON.stringify(selected, null, 2))}>Copy JSON</button>
        </div>

        <div className="small">bbox: {bbox}</div>
      </div>
      <div className="map-wrap"><div className="map" ref={mapContainerRef} /></div>
    </div>
  );
}
