"""Before the cold snap: read the forecast + Building Memory, rank heating risk, plan preventive tasks.

Every task says what to do, by when, who does it, why, and which document the reason came from.
Nothing is sent automatically: the manager approves the plan (or single tasks).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from .memory import BuildingMemory
from .weather import summarize
from . import winter_texts as T

PRIO = {"critical": 0, "high": 1, "normal": 2}


def _fmt(ts: str | None, now: datetime | None = None) -> str:
    if not ts:
        return "-"
    d = datetime.fromisoformat(ts)
    if now and d <= now:
        return "now"
    return d.strftime("%a %d.%m. %H:%M")


def heating_risk(bm: BuildingMemory, building: str) -> dict:
    """Simple, explainable score: which central heating is most likely to fail in the cold snap."""
    assets = [a for a in bm.by_type("asset", building) if a.get("category") == "heating"]
    if not assets:
        return {"building": building, "asset": None, "score": 0, "reasons": []}
    a = assets[0]
    score, reasons = 0, []
    year = int((a.get("installed") or "2000")[:4])
    age = bm.today.year - year
    if age >= 15:
        score += 3
        reasons.append((f"{age} years old (installed {year})", bm.src(a)))
    elif age >= 10:
        score += 1
        reasons.append((f"{age} years old", bm.src(a)))
    if not a.get("under_warranty"):
        score += 1
        reasons.append(("out of warranty", bm.src(a)))
    lm = a.get("last_maintenance")
    if a.get("maintenance_contract") == "unklar":
        score += 2
        reasons.append(("maintenance contract unclear", bm.src(a)))
    elif lm and (bm.today - date.fromisoformat(lm)).days > 365:
        score += 2
        reasons.append((f"annual maintenance overdue (last {lm})", bm.src(a)))
    fails = [t for t in bm.by_type("ticket", building) if t.get("asset") == a["id"]
             and t.get("category") == "heating"
             and (bm.today - date.fromisoformat(t["date"])).days <= 365]
    if fails:
        score += min(len(fails), 3)
        reasons.append((f"{len(fails)} heating failures in the last 12 months", "06_ticket_historie.csv"))
    worn = [g for g in bm.building_gaps(building) if "verschlissen" in g["issue"].lower()]
    for g in worn:
        score += 2
        reasons.append((f"technician note: {g['issue']}", g["source"]))
    return {"building": building, "asset": a["id"], "asset_name": a["name"], "score": score,
            "maintainer": a.get("maintainer") or a.get("installer"),
            "level": "high" if score >= 6 else "medium" if score >= 3 else "low",
            "reasons": [{"text": r, "source": s} for r, s in reasons]}


def plan(mem: dict, forecasts: dict, now: datetime) -> dict:
    bm = BuildingMemory(mem, now.date())
    buildings, all_tasks, risks = [], [], []
    for b in mem["buildings"]:
        node = mem["nodes"][b]
        wx = summarize(forecasts[b])
        tasks: list[dict] = []
        first_frost = wx["first_frost"]
        frost_due = None
        if first_frost:
            frost_due = max(datetime.fromisoformat(first_frost) - timedelta(hours=12), now).isoformat()
        policy = next(iter(bm.by_type("policy", b)), None)

        def task(prio, title, owner, due, why, sources, kind):
            tasks.append({"building": b, "priority": prio, "title": title, "owner": owner, "due": due,
                          "due_label": _fmt(due, now), "why": why, "sources": sources, "kind": kind})

        if wx["frost_hours"]:
            # 1. vacant units: insurance duty to heat or drain
            for u in bm.units(b):
                if u.get("vacant"):
                    why = f"{u['id']} is vacant and {wx['frost_hours']} frost hours are forecast (min {wx['min_temp']} °C)."
                    srcs = [bm.src(u)]
                    if policy and policy.get("duties"):
                        why += (" The building policy requires heating or draining unused parts in winter, "
                                "so a frost claim could be cut if this is skipped.")
                        srcs.append(bm.src(policy))
                    for g in bm.building_gaps(b):
                        if u["id"] in g["issue"]:
                            why += f" Handover note: '{g['issue']}'."
                            srcs.append(g["source"])
                    task("critical", f"Frost-protect vacant flat {u['id']}: radiators on frost setting, shut off and drain water, "
                                     "check every 2 days", "Hausmeister (V08)", frost_due, why, srcs, "vacant_frost")
            # 2. outdoor taps
            for a in bm.by_type("asset", b):
                if a.get("category") == "outdoor_tap":
                    task("high", f"Shut off and drain outdoor tap {a['id']} ({a['location']})", "Hausmeister (V08)",
                         frost_due, f"Exposed pipe, first frost {_fmt(first_frost)}.", [bm.src(a)], "outdoor_tap")
        # 3. winter service (snow / ice)
        if wx["winter_service_days"]:
            days = ", ".join(datetime.fromisoformat(d).strftime("%a %d.%m") for d in wx["winter_service_days"])
            ws_due = max(datetime.fromisoformat(wx["winter_service_days"][0]) - timedelta(hours=6), now).isoformat()
            vendor_id = node.get("winter_service_vendor")
            if vendor_id:
                v = bm.n[vendor_id]
                task("high", f"Alert {v['name']}: snow/ice on {days}. Photo check-in required by 07:00 (Sun 09:00)",
                     v["name"], ws_due, f"Contract: {node['winter_service']}. Monitoring is armed: if there is "
                     "no check-in by the deadline, the manager gets an alert.", [bm.src(node)], "winter_service")
            else:
                task("critical", f"No winter service contract: book one for {days} now",
                     "Manager", ws_due,
                     f"Current arrangement: '{node['winter_service']}'. A house-rules notice does not move the "
                     "clearing duty to tenants (that needs a lease clause), and the owner stays liable even after "
                     "delegating. Ice is forecast.",
                     [bm.src(node)] + [g["source"] for g in bm.building_gaps(b) if "Winterdienst" in g["issue"]],
                     "winter_service_gap")
        # 4. heating risk -> standby / pre-check
        risk = heating_risk(bm, b)
        risks.append(risk)
        if risk["asset"] and wx["hard_frost_hours"] and risk["level"] == "high":
            v = bm.n.get(risk["maintainer"] or "")
            worn = [r["text"] for r in risk["reasons"] if "technician note" in r["text"]]
            task("critical", f"Pre-frost check of {risk['asset']} and 24/7 standby with {v['name'] if v else 'heating firm'}"
                             + (" (replace the worn part now)" if worn else ""),
                 v["name"] if v else "Manager", frost_due,
                 f"Highest heating risk in the portfolio (score {risk['score']}): "
                 + "; ".join(r["text"] for r in risk["reasons"]) + f". Hard frost down to {wx['min_temp']} °C.",
                 sorted({r["source"] for r in risk["reasons"]}), "heating_standby")
        # 5. tenant broadcast
        tenants = [t for t in bm.tenants(b)]
        if wx["frost_hours"]:
            msgs = [{"unit": t["unit"], "tenant": t["name"], "lang": T.pick(t["language"]),
                     "text": T.WINTER_TIPS[T.pick(t["language"])].format(first_frost=_fmt(first_frost))}
                    for t in tenants]
            task("normal", f"Send winter tips to {len(msgs)} tenants in their language", "Agent (after approval)",
                 frost_due, "Heating on low while away and short full airing prevent frozen pipes and condensation mould.",
                 [bm.src(t) for t in tenants[:1]], "tenant_broadcast")
            tasks[-1]["messages"] = msgs
        tasks.sort(key=lambda t: (PRIO[t["priority"]], t["due"] or ""))
        all_tasks += tasks
        buildings.append({"id": b, "address": node["address"], "weather": wx, "tasks": tasks, "risk": risk})
    risks.sort(key=lambda r: -r["score"])
    return {"generated_at": now.isoformat(), "buildings": buildings, "heating_risk_ranking": risks,
            "counts": {p: sum(t["priority"] == p for t in all_tasks) for p in PRIO}}
