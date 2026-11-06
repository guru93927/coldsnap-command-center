"""FastAPI app: Building Memory, forecast, prevention plan, cold-night simulation, tenant triage, UI.

Run:  uvicorn app.api:app --reload      then open http://localhost:8000
"""
from __future__ import annotations

import os
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .agent import triage
from .ingest import build_memory
from .prevention import plan
from .simulate import compare, load_events
from .weather import get_forecasts, summarize

ROOT = Path(__file__).resolve().parent.parent
EVENTS = load_events()
# fixed demo date so warranty and history checks are reproducible; set DEMO_DAY=YYYY-MM-DD to override
DEMO_DAY = date.fromisoformat(os.getenv("DEMO_DAY", EVENTS["date"]))

app = FastAPI(title="Cold-Snap Command Center", version="2.0",
              description="AI winter operations for residential property management (synthetic demo data).")


@lru_cache(maxsize=1)
def memory() -> dict:
    return build_memory(today=DEMO_DAY)


@lru_cache(maxsize=1)
def simulation() -> dict:
    return compare()


class TriageIn(BaseModel):
    unit_id: str = Field(examples=["WE03"])
    message: str = Field(min_length=3, max_length=2000)
    mode: str = Field(default="context", pattern="^(context|baseline)$")


@app.get("/", include_in_schema=False)
def ui():
    return FileResponse(ROOT / "ui" / "index.html")


@app.get("/api/portfolio")
def portfolio():
    m = memory()
    n = m["nodes"]
    out = []
    for b in m["buildings"]:
        units = [u for u in n.values() if u["type"] == "unit" and u["building"] == b]
        out.append({"id": b, "address": n[b]["address"], "heating": n[b]["heating"],
                    "winter_service": n[b]["winter_service"], "units": len(units),
                    "vacant": [u["id"] for u in units if u.get("vacant")],
                    "gaps": [g for g in m["gaps"] if g["building"] == b]})
    counts: dict[str, int] = {}
    for x in n.values():
        counts[x["type"]] = counts.get(x["type"], 0) + 1
    return {"buildings": out, "documents": len(m["documents"]), "nodes": len(n), "edges": len(m["edges"]),
            "counts": counts}


@app.get("/api/units")
def units():
    n = memory()["nodes"]
    return [{"id": u["id"], "building": u["building"], "address": n[u["building"]]["address"].split(",")[0],
             "position": u.get("position"), "vacant": u.get("vacant", False),
             "tenant": n.get(f"T-{u['id']}", {}).get("name")}
            for u in n.values() if u["type"] == "unit"]


@app.get("/api/forecast")
def forecast(source: str = Query("scenario", pattern="^(scenario|live)$")):
    m = memory()
    f = get_forecasts(m, source)
    return {"source": f["source"],
            "buildings": {b: {"address": m["nodes"][b]["address"].split(",")[0], "hours": h, "summary": summarize(h)}
                          for b, h in f["by_building"].items()}}


@app.get("/api/prevention")
def prevention(source: str = Query("scenario", pattern="^(scenario|live)$")):
    if source == "scenario":
        now = datetime.fromisoformat(EVENTS["prevention_run_at"])
    else:
        now = datetime.now().replace(minute=0, second=0, microsecond=0)
    m = build_memory(today=now.date())
    f = get_forecasts(m, source)
    return {"source": f["source"], **plan(m, f["by_building"], now)}


@app.get("/api/simulation")
def simulate():
    s = simulation()
    return {k: v for k, v in s.items() if k != "prevention"}


@app.post("/api/triage")
def do_triage(body: TriageIn):
    m = memory()
    if body.unit_id not in m["nodes"] or m["nodes"][body.unit_id]["type"] != "unit":
        raise HTTPException(404, f"Unknown unit {body.unit_id}")
    if not any(e[1] == "RENTS" and e[2] == body.unit_id for e in m["edges"]):
        raise HTTPException(400, f"{body.unit_id} is vacant: no tenant to triage for")
    return triage(body.message, body.unit_id, m, DEMO_DAY, body.mode)


@app.get("/api/health")
def health():
    return {"ok": True, "demo_day": DEMO_DAY.isoformat()}
