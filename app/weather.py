"""Weather: hourly forecast per building and the winter events derived from it.

source="scenario" (default) reads data/scenarios/<name>/forecast.json so the demo is reproducible.
source="live" calls the free Open-Meteo API (no key) for each building's coordinates and falls back
to the scenario if the network is unavailable.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

SCENARIO_DIR = Path(__file__).resolve().parent.parent / "data" / "scenarios"
DEFAULT_SCENARIO = "cold-snap-dec-2026"
OPEN_METEO = "https://api.open-meteo.com/v1/forecast"

FROST, HARD_FROST, STORM_GUST = 0.0, -5.0, 75.0


def load_scenario_forecast(scenario: str = DEFAULT_SCENARIO) -> dict:
    return json.loads((SCENARIO_DIR / scenario / "forecast.json").read_text(encoding="utf-8"))


def fetch_live(lat: float, lon: float, timeout: float = 8.0) -> list[dict]:
    import httpx
    r = httpx.get(OPEN_METEO, timeout=timeout, params={
        "latitude": lat, "longitude": lon, "forecast_days": 3, "timezone": "Europe/Berlin",
        "hourly": "temperature_2m,snowfall,precipitation,wind_gusts_10m"})
    r.raise_for_status()
    h = r.json()["hourly"]
    return [{"t": t, "temp": tmp, "snow_cm": sn or 0.0, "precip_mm": pr or 0.0, "gust": g or 0.0}
            for t, tmp, sn, pr, g in zip(h["time"], h["temperature_2m"], h["snowfall"],
                                         h["precipitation"], h["wind_gusts_10m"])]


def get_forecasts(mem: dict, source: str = "scenario", scenario: str = DEFAULT_SCENARIO) -> dict:
    """Returns {"source": ..., "by_building": {building_id: [hourly dicts]}}."""
    if source == "live":
        try:
            out = {}
            for b in mem["buildings"]:
                node = mem["nodes"][b]
                out[b] = fetch_live(node["lat"], node["lon"])
            return {"source": "live (Open-Meteo)", "by_building": out}
        except Exception as exc:  # network blocked, API down, ...
            data = load_scenario_forecast(scenario)
            return {"source": f"scenario (live failed: {type(exc).__name__})", "by_building": data["by_building"]}
    data = load_scenario_forecast(scenario)
    return {"source": f"scenario: {scenario}", "by_building": data["by_building"]}


def _windows(hours: list[dict], pred) -> list[tuple[str, str]]:
    out, start, prev = [], None, None
    for h in hours:
        if pred(h):
            start = start or h["t"]
            prev = h["t"]
        elif start:
            out.append((start, prev))
            start = None
    if start:
        out.append((start, prev))
    return out


def summarize(hours: list[dict]) -> dict:
    """Winter events a property manager cares about."""
    coldest = min(hours, key=lambda h: h["temp"])
    snow_total = round(sum(h["snow_cm"] for h in hours), 1)
    # ice risk: below or near zero within 12 h after any precipitation (refreezing / snow)
    ice_hours, last_wet = [], -99
    for i, h in enumerate(hours):
        if h["precip_mm"] > 0.1 or h["snow_cm"] > 0:
            last_wet = i
        if h["temp"] <= 0.5 and i - last_wet <= 12 and last_wet >= 0:
            ice_hours.append(h)
    ice_days = sorted({h["t"][:10] for h in ice_hours})
    snow_days = sorted({h["t"][:10] for h in hours if h["snow_cm"] > 0})
    events = []
    for s, e in _windows(hours, lambda h: h["temp"] < FROST):
        events.append({"type": "frost", "start": s, "end": e})
    for s, e in _windows(hours, lambda h: h["temp"] <= HARD_FROST):
        events.append({"type": "hard_frost", "start": s, "end": e})
    for s, e in _windows(hours, lambda h: h["snow_cm"] > 0):
        events.append({"type": "snow", "start": s, "end": e})
    for s, e in _windows(hours, lambda h: h["gust"] >= STORM_GUST):
        events.append({"type": "storm", "start": s, "end": e})
    return {
        "min_temp": coldest["temp"], "min_temp_at": coldest["t"],
        "frost_hours": sum(h["temp"] < FROST for h in hours),
        "hard_frost_hours": sum(h["temp"] <= HARD_FROST for h in hours),
        "first_frost": next((h["t"] for h in hours if h["temp"] < FROST), None),
        "snow_cm": snow_total, "snow_days": snow_days, "ice_days": ice_days,
        "winter_service_days": sorted(set(snow_days) | set(ice_days)),
        "max_gust": max(h["gust"] for h in hours),
        "events": sorted(events, key=lambda x: x["start"]),
    }


def temp_at(hours: list[dict], when: datetime) -> float:
    key = when.strftime("%Y-%m-%dT%H:00")
    for h in hours:
        if h["t"] == key:
            return h["temp"]
    return hours[-1]["temp"] if when.isoformat() > hours[-1]["t"] else hours[0]["temp"]
