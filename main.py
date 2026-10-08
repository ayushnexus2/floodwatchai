import time
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles

from risk import compute_risk

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
FLOOD_URL = "https://flood-api.open-meteo.com/v1/flood"
GEO_URL = "https://geocoding-api.open-meteo.com/v1/search"
CACHE_SECONDS = 600

app = FastAPI(title="FloodWatch API", version="1.0.0")
_cache = {}


async def get_json(client, url, params):
    r = await client.get(url, params=params)
    r.raise_for_status()
    return r.json()


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/geocode")
async def geocode(q: str = Query(min_length=2, max_length=80)):
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            data = await get_json(
                client, GEO_URL, {"name": q, "count": 5, "language": "en"}
            )
    except httpx.HTTPError:
        raise HTTPException(502, "Place search is unavailable right now")
    results = [
        {
            "name": p.get("name"),
            "admin1": p.get("admin1"),
            "country": p.get("country"),
            "latitude": p["latitude"],
            "longitude": p["longitude"],
        }
        for p in data.get("results", [])
    ]
    return {"results": results}


@app.get("/api/risk")
async def risk(
    lat: float = Query(ge=-90, le=90),
    lon: float = Query(ge=-180, le=180),
):
    key = (round(lat, 2), round(lon, 2))
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]

    forecast_params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "precipitation,precipitation_probability,soil_moisture_0_to_1cm",
        "past_days": 3,
        "forecast_days": 3,
        "timezone": "auto",
    }
    flood_params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "river_discharge,river_discharge_mean",
        "forecast_days": 3,
    }

    async with httpx.AsyncClient(timeout=15) as client:
        try:
            weather = await get_json(client, FORECAST_URL, forecast_params)
        except httpx.HTTPError:
            raise HTTPException(502, "Weather service is unavailable right now")
        try:  # river data is optional: many places have no river grid cell
            flood = await get_json(client, FLOOD_URL, flood_params)
        except httpx.HTTPError:
            flood = None

    try:
        result = compute_risk(weather, flood)
    except (KeyError, ValueError) as e:
        raise HTTPException(502, f"Could not read forecast data: {e}")

    _cache[key] = (time.time(), result)
    return result


# Must be last so it does not shadow /api routes
FRONTEND = Path(__file__).resolve().parent
app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")