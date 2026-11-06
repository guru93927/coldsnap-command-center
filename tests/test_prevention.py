from datetime import datetime

from app.ingest import build_memory
from app.prevention import plan
from app.weather import get_forecasts

NOW = datetime(2026, 12, 1, 18, 0)


def run():
    m = build_memory(today=NOW.date())
    return plan(m, get_forecasts(m)["by_building"], NOW)


def test_old_boiler_with_worn_part_is_top_risk():
    top = run()["heating_risk_ranking"][0]
    assert top["asset"] == "RA-HEIZ-01" and top["level"] == "high"
    assert any("Zündelektrode" in r["text"] for r in top["reasons"])


def test_vacant_flat_gets_critical_frost_task_citing_insurance():
    tasks = [t for b in run()["buildings"] for t in b["tasks"]]
    t = next(t for t in tasks if t["kind"] == "vacant_frost")
    assert t["priority"] == "critical" and "KW-03" in t["title"]
    assert any("05_versicherung" in s for s in t["sources"])


def test_no_winter_contract_becomes_critical_task_only_where_missing():
    tasks = [t for b in run()["buildings"] for t in b["tasks"]]
    gaps = [t for t in tasks if t["kind"] == "winter_service_gap"]
    assert [t["building"] for t in gaps] == ["OBJ-KAST4"]
    assert sum(t["kind"] == "winter_service" for t in tasks) == 2


def test_tenant_tips_are_in_each_tenants_language():
    tasks = [t for b in run()["buildings"] for t in b["tasks"] if t["kind"] == "tenant_broadcast"]
    langs = {m["lang"] for t in tasks for m in t["messages"]}
    assert langs == {"de", "en", "tr"}
    assert sum(len(t["messages"]) for t in tasks) == 19  # every tenant, not the vacant flat
