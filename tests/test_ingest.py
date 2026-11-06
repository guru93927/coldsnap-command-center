from datetime import date

from app.ingest import build_memory


def mem():
    return build_memory(today=date(2026, 12, 1))


def test_portfolio_has_three_buildings_and_unique_units():
    m = mem()
    assert m["buildings"] == ["OBJ-KAST4", "OBJ-LIND12", "OBJ-RHEIN88"]
    units = [n for n in m["nodes"].values() if n["type"] == "unit"]
    assert len(units) == 20
    assert all(u["building"] in m["buildings"] for u in units)


def test_vacant_unit_is_not_a_missing_lease():
    m = mem()
    assert m["nodes"]["KW-03"]["vacant"] is True
    assert not any("KW-03: no lease" in g["issue"] for g in m["gaps"])


def test_missing_winter_service_contract_is_flagged_critical():
    gaps = [g for g in mem()["gaps"] if g["building"] == "OBJ-KAST4" and g["severity"] == "critical"]
    assert any("Winter service not contracted" in g["issue"] for g in gaps)


def test_every_fact_has_a_source():
    assert all(n["sources"] for n in mem()["nodes"].values())
