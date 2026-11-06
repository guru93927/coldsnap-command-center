"""Replay a cold night: the command center vs. two realistic baselines.

    python -m app.simulate                # prints the comparison
    python -m app.simulate --timeline     # also prints the agent's timeline

Baselines (same tenant messages, same boiler failure, same technician speed):
  office   messages are read when the office opens (08:00), one ticket at a time
  on_call  a person on call answers every message 20 minutes after it arrives
Neither baseline has the technician's note about the worn part, so the technician has to fetch it.
All assumptions live in data/scenarios/<name>/events.json.
"""
from __future__ import annotations

import heapq
import json
import sys
from datetime import date, datetime, timedelta

from .command_center import CommandCenter, Config, hhmm
from .ingest import build_memory
from .prevention import plan
from .weather import SCENARIO_DIR, DEFAULT_SCENARIO, get_forecasts, temp_at


def load_events(scenario: str = DEFAULT_SCENARIO) -> dict:
    return json.loads((SCENARIO_DIR / scenario / "events.json").read_text(encoding="utf-8"))


def _at(day: date, hm: str) -> datetime:
    h, m = map(int, hm.split(":"))
    return datetime.combine(day, datetime.min.time()).replace(hour=h, minute=m)


def vendor_timeline(dispatch: datetime, vm: dict, part_on_hand: bool) -> dict:
    travel = vm["travel_night_min"] if dispatch.hour < vm["night_until_hour"] else vm["travel_day_min"]
    arrival = dispatch + timedelta(minutes=travel)
    diagnosed = arrival + timedelta(minutes=vm["diagnose_min"])
    fix = vm["repair_min"] + (0 if part_on_hand else vm["fetch_part_min"])
    return {"ack": dispatch + timedelta(minutes=vm["ack_min"]), "arrival": arrival,
            "diagnosed": diagnosed, "restored": diagnosed + timedelta(minutes=fix)}


def run_agent(mem: dict, fc: dict, ev: dict, cfg: Config | None = None) -> CommandCenter:
    day = date.fromisoformat(ev["date"])
    cc = CommandCenter(mem, fc, day, cfg)
    queue: list = []
    for i, e in enumerate(ev["feed"]):
        heapq.heappush(queue, (_at(day, e["t"]), i, e))
    seq = len(queue)
    fail = ev["failure"]
    while queue:
        at, _, e = heapq.heappop(queue)
        if e["type"] == "tenant":
            cc.on_tenant(at, e["unit"], e["text"])
        elif e["type"] == "checkin":
            cc.on_checkin(at, e["building"], e["vendor"], e.get("photo", True))
        elif e["type"] == "vendor":
            cc.on_vendor(at, e["incident"], e["status"], e.get("eta"), e.get("diag", ""))
        # schedule the technician for every new dispatch (same speed model as the baselines)
        for inc in cc.new_dispatches:
            part_ok = bool(inc.part_hint) and inc.part_hint.lower() in fail["part"].lower()
            vt = vendor_timeline(cc.now, ev["vendor_model"], part_ok)
            diag = f"{fail['part']} defekt" + (", Ersatzteil dabei" if part_ok else ", Ersatzteil wird geholt")
            for status, t, eta in (("ack", vt["ack"], vt["arrival"]), ("on_site", vt["diagnosed"], vt["restored"]),
                                   ("resolved", vt["restored"], None)):
                seq += 1
                heapq.heappush(queue, (t, seq, {"type": "vendor", "incident": inc.id, "status": status,
                                                "eta": eta, "diag": diag}))
        cc.new_dispatches.clear()
    cc.advance(_at(day, "12:00"))
    return cc


def run_baseline(mem: dict, fc: dict, ev: dict, mode: str) -> dict:
    day = date.fromisoformat(ev["date"])
    bl, vm, fail = ev["baseline"], ev["vendor_model"], ev["failure"]
    msgs = [e for e in ev["feed"] if e["type"] == "tenant"]
    units_in_b = {u for u, n in mem["nodes"].items() if n["type"] == "unit" and n.get("building") == fail["building"]}
    handled = []
    clock = _at(day, bl["office_opens"])
    for m in msgs:
        at = _at(day, m["t"])
        if mode == "office":
            clock = max(clock, at) + timedelta(minutes=bl["triage_min_per_ticket"])
            handled.append((m, clock))
        else:
            handled.append((m, at + timedelta(minutes=bl["on_call_response_min"])))
    heat = [h for m, h in handled if m["unit"] in units_in_b]
    dispatch = min(heat)
    vt = vendor_timeline(dispatch, vm, part_on_hand=False)
    ice = next((h for m, h in handled if "glatt" in m["text"].lower() or "icy" in m["text"].lower()), None)
    return {"mode": mode, "tickets": len(msgs), "dispatch": dispatch, "restored": vt["restored"],
            "ice_action": ice, "tenant_updates": 0, "radiator_visits": 1, "handled": handled}


def compare(scenario: str = DEFAULT_SCENARIO) -> dict:
    ev = load_events(scenario)
    day = date.fromisoformat(ev["date"])
    mem = build_memory(today=day)
    fc = get_forecasts(mem, "scenario", scenario)["by_building"]
    prev_at = datetime.fromisoformat(ev["prevention_run_at"])
    prevention = plan(build_memory(today=prev_at.date()), fc, prev_at)
    cc = run_agent(mem, fc, ev)
    office, on_call = run_baseline(mem, fc, ev, "office"), run_baseline(mem, fc, ev, "on_call")

    fail = ev["failure"]
    inc = next(i for i in cc.incidents.values() if i.building == fail["building"])
    first = inc.first_report_at
    flats = [t for t in cc.bm.tenants(fail["building"])]
    risk = cc.risk(inc)
    per_day = risk["per_day"]

    def outage_h(restored):
        return (restored - first).total_seconds() / 3600

    ice_report = next(_at(day, e["t"]) for e in ev["feed"] if e["type"] == "tenant" and "glatt" in e["text"].lower())
    agent_ice = min(cc.ice_orders.values()) if cc.ice_orders else None
    work_items = len(cc.incidents) + len(cc.tickets) + sum(a["level"] in ("critical", "high") for a in cc.alerts)
    broadcasts = sum(o["kind"] == "broadcast" for o in cc.outbox)
    solved_self = sum(s["status"] == "solved" for s in cc.selfhelp.values())

    def row(label, a, o, c, better=None):
        return {"metric": label, "agent": a, "office": o, "on_call": c, "better": better}

    rows = [
        row("Tenant messages received", len(ev["feed"]) - sum(e["type"] != "tenant" for e in ev["feed"]),
            office["tickets"], on_call["tickets"]),
        row("Items staff must read and handle", work_items, office["tickets"], on_call["tickets"], "lower"),
        row("Heating technician dispatched (after 1st report)", f"+{(inc.opened_at - first).seconds // 60} min",
            f"+{(office['dispatch'] - first).seconds // 60} min", f"+{(on_call['dispatch'] - first).seconds // 60} min", "lower"),
        row("Worn part brought along (from technician's notes)", "yes" if inc.part_hint else "no", "no", "no"),
        row("Heating restored", hhmm(inc.resolved_at), hhmm(office["restored"]), hhmm(on_call["restored"]), "lower"),
        row("Hours without heat (after 1st report)", round(outage_h(inc.resolved_at), 1),
            round(outage_h(office["restored"]), 1), round(outage_h(on_call["restored"]), 1), "lower"),
        row("Flat-hours in the cold", round(outage_h(inc.resolved_at) * len(flats)),
            round(outage_h(office["restored"]) * len(flats)), round(outage_h(on_call["restored"]) * len(flats)), "lower"),
        row("Proactive status updates to tenants", broadcasts, 0, 0, "higher"),
        row("Technician visits for a radiator that just needed bleeding", 0, 1, 1, "lower"),
        row("Icy path: action taken at", hhmm(agent_ice), hhmm(office["ice_action"]), hhmm(on_call["ice_action"]), "lower"),
        row("…relative to the tenant's near-slip at " + hhmm(ice_report),
            f"{int((agent_ice - ice_report).total_seconds() // 60):+d} min" if agent_ice else "-",
            f"{int((office['ice_action'] - ice_report).total_seconds() // 60):+d} min",
            f"{int((on_call['ice_action'] - ice_report).total_seconds() // 60):+d} min", "lower"),
        row("Illustrative rent-reduction exposure for the outage",
            f"€{per_day * outage_h(inc.resolved_at) / 24:.0f}", f"€{per_day * outage_h(office['restored']) / 24:.0f}",
            f"€{per_day * outage_h(on_call['restored']) / 24:.0f}", "lower"),
    ]
    return {
        "scenario": scenario, "date": ev["date"], "failure": fail,
        "assumptions": {"baseline": ev["baseline"], "vendor_model": ev["vendor_model"],
                        "rent_band": f"{int(risk['pct'] * 100)}% of warm rent per day for a full heating failure "
                                     f"below 0 °C (common guidance range, not legal advice)",
                        "rent_per_day_building": round(per_day)},
        "rows": rows,
        "prevention": prevention,
        "timeline": cc.timeline,
        "outbox": cc.outbox,
        "alerts": cc.alerts,
        "tickets": cc.tickets,
        "incidents": [{"id": i.id, "building": i.building, "asset": i.asset["id"], "vendor": i.vendor["name"],
                       "opened_at": hhmm(i.opened_at), "first_report_at": hhmm(i.first_report_at),
                       "resolved_at": hhmm(i.resolved_at), "flats_reporting": sorted(i.units),
                       "messages_merged": len(i.reports), "priority_units": sorted(i.priority_units),
                       "part_hint": i.part_hint, "risk": {k: v for k, v in cc.risk(i).items() if k != "units"},
                       "outside_temp": temp_at(fc[i.building], i.opened_at)} for i in cc.incidents.values()],
        "kpis": {"broadcasts": broadcasts, "self_help_solved": solved_self, "work_items": work_items,
                 "messages": office["tickets"]},
    }


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    r = compare()
    print(f"\nCold-night replay: {r['date']}, boiler {r['failure']['asset']} fails at "
          f"{r['failure']['fails_at'][11:]} (synthetic scenario)\n")
    w = 52
    print(f"{'':{w}}{'agent':>12}{'office hrs':>12}{'on-call':>10}")
    for x in r["rows"]:
        print(f"{x['metric'][:w]:{w}}{str(x['agent']):>12}{str(x['office']):>12}{str(x['on_call']):>10}")
    print("\nBaseline assumptions:", json.dumps(r["assumptions"]["baseline"]),
          "| technician:", json.dumps(r["assumptions"]["vendor_model"]))
    print("Rent band:", r["assumptions"]["rent_band"])
    if "--timeline" in sys.argv:
        print("\nAgent timeline:")
        for t in r["timeline"]:
            print(f"  {t['t']}  {t['kind']:<10} {(t['building'] or ''):<12} {t['title']}")
            if t["detail"] and t["kind"] not in ("tenant",):
                print(f"{'':30}{t['detail'][:160]}")


if __name__ == "__main__":
    main()
