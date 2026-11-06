"""Generate the synthetic cold-snap scenario (forecast + event feed). Deterministic.

    python scripts/make_scenario.py
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "scenarios" / "cold-snap-dec-2026"
START = datetime(2026, 12, 1, 18, 0)          # Tuesday evening: when the prevention run happens
HOURS = 73

# (hour offset from START, temperature °C) for Düsseldorf; Essen runs ~1 °C colder
KEYPOINTS = [(0, 3), (6, 1), (12, 0), (18, 1), (24, -1), (30, -1.5), (35, -1.5), (36, -6), (37, -7),
             (42, -3), (48, -6), (54, -9), (60, -10), (66, -4), (72, -6)]
SNOW_HOURS = range(31, 36)                    # Thu 03 Dec 01:00-05:00, ~3 cm
OFFSET = {"OBJ-LIND12": 0.0, "OBJ-RHEIN88": 0.3, "OBJ-KAST4": -1.0}


def interp(h: float) -> float:
    for (h0, t0), (h1, t1) in zip(KEYPOINTS, KEYPOINTS[1:]):
        if h0 <= h <= h1:
            return t0 + (t1 - t0) * (h - h0) / (h1 - h0) if h1 != h0 else t0
    return KEYPOINTS[-1][1]


def forecast(offset: float) -> list[dict]:
    rows = []
    for h in range(HOURS):
        t = START + timedelta(hours=h)
        snow = 0.6 if h in SNOW_HOURS else 0.0
        rows.append({"t": t.strftime("%Y-%m-%dT%H:00"), "temp": round(interp(h) + offset, 1),
                     "snow_cm": snow, "precip_mm": 0.9 if snow else 0.0,
                     "gust": 40.0 if snow else 25.0})
    return rows


EVENTS = {
    "date": "2026-12-03",
    "prevention_run_at": START.isoformat(),
    "failure": {"building": "OBJ-RHEIN88", "asset": "RA-HEIZ-01", "fails_at": "2026-12-03T04:50",
                "part": "Zündelektrode"},
    "vendor_model": {"ack_min": 8, "travel_night_min": 75, "travel_day_min": 60, "diagnose_min": 20,
                     "repair_min": 30, "fetch_part_min": 150, "night_until_hour": 7},
    "baseline": {"office_opens": "08:00", "triage_min_per_ticket": 6, "on_call_response_min": 20},
    "feed": [
        {"t": "05:58", "type": "tenant", "unit": "RA-03", "text": "Heizung ist komplett kalt, alle Heizkörper sind aus"},
        {"t": "06:07", "type": "tenant", "unit": "RA-06", "text": "No heating at all in the flat, it's freezing"},
        {"t": "06:15", "type": "tenant", "unit": "RA-01", "text": "Kaloriferler hiç ısınmıyor, ev buz gibi"},
        {"t": "06:21", "type": "tenant", "unit": "RA-07", "text": "Bei uns sind alle Heizkörper eiskalt"},
        {"t": "06:30", "type": "tenant", "unit": "WE04", "text": "Ein Heizkörper im Schlafzimmer bleibt kalt und gluckert"},
        {"t": "06:35", "type": "checkin", "building": "OBJ-LIND12", "vendor": "V10", "photo": True},
        {"t": "06:40", "type": "tenant", "unit": "RA-02", "text": "Heizung geht nicht!!"},
        {"t": "06:50", "type": "checkin", "building": "OBJ-RHEIN88", "vendor": "V10", "photo": True},
        {"t": "06:52", "type": "tenant", "unit": "RA-05", "text": "radiators cold since early morning, any update?"},
        {"t": "07:05", "type": "tenant", "unit": "WE04", "text": "Hat geklappt, der Heizkörper ist wieder warm. Danke!"},
        {"t": "07:10", "type": "tenant", "unit": "WE05", "text": "Hot water is lukewarm again this morning"},
        {"t": "07:20", "type": "tenant", "unit": "KW-05", "text": "Der Gehweg vor dem Haus ist spiegelglatt, bin fast ausgerutscht"},
        {"t": "07:30", "type": "tenant", "unit": "RA-08", "text": "Wann kommt jemand? Es ist sehr kalt und wir haben ein Baby"},
        {"t": "08:05", "type": "tenant", "unit": "KW-02", "text": "There's black mould appearing on the bedroom window frame"},
        {"t": "09:30", "type": "tenant", "unit": "RA-04", "text": "Immer noch kalt bei uns"},
    ],
}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    fc = {"generated_from": "scripts/make_scenario.py (synthetic)", "start": START.isoformat(),
          "by_building": {b: forecast(o) for b, o in OFFSET.items()}}
    (OUT / "forecast.json").write_text(json.dumps(fc, indent=1), encoding="utf-8")
    (OUT / "events.json").write_text(json.dumps(EVENTS, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
