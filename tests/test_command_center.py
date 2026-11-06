from datetime import date, datetime

from app.command_center import CommandCenter
from app.ingest import build_memory
from app.simulate import compare
from app.weather import get_forecasts

DAY = date(2026, 12, 3)


def cc():
    m = build_memory(today=DAY)
    return CommandCenter(m, get_forecasts(m)["by_building"], DAY)


def at(h, mi):
    return datetime(2026, 12, 3, h, mi)


def test_three_flats_open_one_incident_and_later_reports_merge():
    c = cc()
    c.on_tenant(at(6, 0), "RA-01", "Heizung ist kalt")
    c.on_tenant(at(6, 5), "RA-02", "No heating at all")
    assert not c.incidents
    c.on_tenant(at(6, 10), "RA-03", "Kaloriferler ısınmıyor")
    assert len(c.incidents) == 1
    c.on_tenant(at(6, 20), "RA-04", "Heizkörper eiskalt")
    inc = next(iter(c.incidents.values()))
    assert inc.units == {"RA-01", "RA-02", "RA-03", "RA-04"}
    assert not c.tickets  # nothing became a separate ticket
    assert inc.part_hint == "Zündelektrode"


def test_single_report_becomes_normal_ticket_after_hold():
    c = cc()
    c.on_tenant(at(7, 0), "WE05", "Hot water is lukewarm again")
    c.advance(at(7, 45))
    assert len(c.tickets) == 1 and c.tickets[0]["category"] == "hot_water"
    assert any("Recurring" in f for f in c.tickets[0]["flags"])


def test_single_radiator_self_help_then_resolved_without_visit():
    c = cc()
    c.on_tenant(at(6, 30), "WE04", "Ein Heizkörper bleibt kalt und gluckert")
    c.on_tenant(at(7, 0), "WE04", "Hat geklappt, wieder warm")
    assert c.selfhelp["WE04"]["status"] == "solved" and not c.tickets


def test_self_help_escalates_when_still_cold():
    c = cc()
    c.on_tenant(at(6, 30), "WE04", "One radiator is cold and gurgling")
    c.on_tenant(at(7, 40), "WE04", "still cold")
    assert c.selfhelp["WE04"]["status"] == "escalated" and len(c.tickets) == 1


def test_missing_winter_service_checkin_alerts_at_seven():
    c = cc()
    c.on_checkin(at(6, 35), "OBJ-LIND12", "V10")
    c.on_checkin(at(6, 50), "OBJ-RHEIN88", "V10")
    c.advance(at(7, 1))
    crit = [a for a in c.alerts if a["level"] == "critical"]
    assert len(crit) == 1 and crit[0]["building"] == "OBJ-KAST4" and crit[0]["t"] == "07:00"


def test_vulnerable_household_gets_heater_offer():
    c = cc()
    for i, u in enumerate(["RA-01", "RA-02", "RA-03"]):
        c.on_tenant(at(6, i), u, "Heizung kalt")
    c.on_tenant(at(6, 30), "RA-08", "Es ist sehr kalt und wir haben ein Baby")
    assert "RA-08" in next(iter(c.incidents.values())).priority_units


def test_simulation_agent_beats_both_baselines():
    r = {x["metric"]: x for x in compare()["rows"]}
    hrs = r["Hours without heat (after 1st report)"]
    assert hrs["agent"] < hrs["on_call"] < hrs["office"]
    items = r["Items staff must read and handle"]
    assert items["agent"] < items["office"]
