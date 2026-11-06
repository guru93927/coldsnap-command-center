"""Context-aware tenant issue agent.

Pipeline (each step is logged in `steps`, each fact used is logged in `evidence`):
  1. understand the message          (classify.py)
  2. load unit + tenant + lease      get_unit_context
  3. resolve the affected asset      find_asset
  4. warranty / insurance / lease    check_warranty, check_insurance, lease clause
  5. decide who pays                 rules below, in legal priority order
  6. choose the vendor               installer for warranty work, else trade + 24/7 if needed
  7. look for patterns               ticket_history (recurring failures)
  8. draft tenant reply, work order, insurance note -> human approves

mode="baseline" skips steps 2-7: same language understanding, no Building Memory.
That is what a generic chatbot would do, and the eval compares the two.
"""
from __future__ import annotations

from datetime import date

from .classify import understand, as_dict
from .memory import BuildingMemory
from . import replies

ASSET_CATEGORY = {"water_leak": "water_pipes", "hot_water": "hot_water", "heating": "heating",
                  "electrical": "electrical", "lock_door": "lock_door", "window_glass": "window_glass",
                  "appliance": "appliance", "roof": "roof", "smoke_detector": "smoke_detector",
                  "gas": "heating"}
TRADE = {"water_leak": "plumbing", "hot_water": "heating", "heating": "heating", "gas": "heating",
         "electrical": "electrical", "lock_door": "locksmith", "window_glass": "windows",
         "roof": "roofing", "pest": "pest", "mould": "mould", "appliance": "electrical",
         "smoke_detector": "handyman", "ice_snow": "winter_service", "other": "handyman"}
GLASS_BROKEN = ["broke ", "kaputt", "gebrochen", "gesprungen", "zersprungen", "riss", "broken", "cracked",
                "shattered", "kırıldı", "çatladı", "kırık"]
APPLIANCE_WORDS = {"Geschirrspüler": ["geschirrspüler", "spülmaschine", "dishwasher", "bulaşık"]}


def _names_asset(text: str, asset: dict) -> bool:
    words = next((w for k, w in APPLIANCE_WORDS.items() if k in asset["name"]), [])
    return any(w in text for w in words)


ETA = {"emergency": "2h", "urgent": "24h", "normal": "3d"}


def triage(message: str, unit_id: str, mem: dict, today: date, mode: str = "context") -> dict:
    u = understand(message, today.month)
    steps, evidence, flags = [f"understand(message) -> {u.category}, {u.urgency}, lang={u.language}"], [], []
    out = {"mode": mode, "unit_id": unit_id, "understanding": as_dict(u), "steps": steps,
           "evidence": evidence, "flags": flags, "needs_human_approval": True}

    if mode == "baseline":
        out.update(cost_bearer="tenant" if u.tenant_caused else "landlord", secondary_bearer=None,
                   asset_id=None, vendor=None, eta=ETA[u.urgency])
        out["tenant_reply"] = replies.tenant_reply(u.language, u.category, u.urgency, None,
                                                   out["cost_bearer"], ETA[u.urgency])
        out["work_order"] = None
        out["insurance_note"] = None
        steps.append("no Building Memory: default cost bearer, no vendor, no history")
        return out

    bm = BuildingMemory(mem, today)
    ctx = bm.get_unit_context(unit_id)
    unit, tenant = ctx["unit"], ctx["tenant"]
    steps.append(f"get_unit_context({unit_id}) -> {tenant['name']}, lang={tenant['language']}, "
                 f"small-repair clause={'yes' if tenant['small_repair_clause'] else 'no'}")
    evidence.append({"fact": f"{unit_id}: {unit.get('position')}; tenant {tenant['name']}",
                     "source": ", ".join(unit["sources"] + tenant["sources"])})
    lang = u.language if u.language in replies.LANGS else tenant["language"]

    # ---- 3. which asset? -----------------------------------------------------
    asset = None
    t = message.lower()
    if u.category == "roof" or (u.category == "water_leak" and u.storm and unit.get("top_floor")):
        u.category = "roof"
        asset = bm.find_asset("roof", unit_id)
    elif u.category in ASSET_CATEGORY:
        in_flat_item = u.small_item and u.small_item not in ("window_handle",)
        needs_building_part = not (
            (u.category == "water_leak" and (in_flat_item or not u.from_pipes)) or
            (u.category in ("heating", "electrical") and in_flat_item) or
            (u.category == "lock_door" and not u.building_door))
        if needs_building_part:
            asset = bm.find_asset(ASSET_CATEGORY[u.category], unit_id)
            if asset and u.category == "appliance" and not _names_asset(t, asset):
                asset = None
    if asset:
        steps.append(f"find_asset({ASSET_CATEGORY.get(u.category, u.category)}) -> {asset['id']} {asset['name']}")
        evidence.append({"fact": f"{asset['id']} {asset['name']}, installed {asset['installed']}",
                         "source": ", ".join(asset["sources"])})
    else:
        steps.append("find_asset -> no building asset; issue is inside the flat" +
                     (f" ({u.small_item})" if u.small_item else ""))

    # ---- 4. warranty / insurance / lease --------------------------------------
    w = bm.check_warranty(asset) if asset else None
    if w:
        none = w["warranty_until"] in (None, "keine")
        status = ("no warranty on record" if none else
                  f"valid until {w['warranty_until']}" if w["under_warranty"] else f"expired {w['warranty_until']}")
        steps.append(f"check_warranty({asset['id']}) -> {status}")
        evidence.append({"fact": f"Warranty {asset['id']}: {status}", "source": w["source"]})
        if none:
            w["warranty_until"] = None

    peril = None
    if u.category == "water_leak" and asset and asset["category"] == "water_pipes":
        peril = "water_leak"
    elif u.category == "roof" and u.storm:
        peril = "storm"
    elif u.category == "window_glass" and any(x in t for x in GLASS_BROKEN) and not u.small_item:
        peril = "glass_breakage"
    policy = bm.check_insurance(peril, unit["building"]) if peril else None
    if policy:
        steps.append(f"check_insurance({peril}) -> {policy['type']} {policy['policy']}, "
                     f"deductible {policy['deductible']:.0f} EUR, report by {policy['report_by']}")
        evidence.append({"fact": f"{policy['type']} {policy['policy']} covers {peril}; "
                                 f"deductible {policy['deductible']:.0f} EUR; report within "
                                 f"{policy['report_within_days']} days", "source": policy["source"]})

    # ---- 5. who pays ------------------------------------------------------------
    secondary, reason = None, ""
    if u.category == "gas":
        bearer, reason = "landlord", "Safety first: emergency response, cause clarified afterwards."
    elif u.tenant_caused:
        bearer = "tenant"
        reason = "Tenant says they caused it: damage beyond normal use is the tenant's cost."
        if peril == "glass_breakage":
            reason += " Glass policy excludes tenant-caused breakage (insurer would seek recourse)."
    elif u.category == "appliance" and not asset:
        bearer, reason = "tenant", "Appliance is not part of the tenancy in this unit (tenant's own)."
    elif u.category == "other":
        bearer, reason = "manager_review", "Not a repair request: routed to the property manager."
    elif u.category == "mould":
        bearer, reason = "assessment_required", ("Cause unclear (building defect vs. ventilation); "
                                                 "policy excludes ventilation-related mould. Book an assessment first.")
    elif w and w["under_warranty"] and peril not in ("storm", "glass_breakage"):
        bearer = "warranty"
        reason = f"Defect in {asset['id']} within warranty: installer must fix it at no cost."
        if peril == "water_leak" and policy:
            secondary = "insurance"
            reason += " Consequential water damage goes to the building insurance."
    elif policy:
        bearer, reason = "insurance", f"Insured peril ({peril}) under {policy['policy']}."
    elif u.small_item and tenant["small_repair_clause"]:
        spent = sum(float(x["cost_eur"]) for x in bm.n.values() if x["type"] == "ticket"
                    and x["unit"] == unit_id and x["paid_by"] == "tenant" and x["date"][:4] == str(today.year))
        cap_item, cap_year = tenant["small_repair_item_cap"], tenant["small_repair_year_cap"]
        steps.append(f"lease small-repair clause: item cap {cap_item:.0f} EUR, year cap {cap_year:.0f} EUR, "
                     f"used this year {spent:.0f} EUR, estimate {u.small_item_cost:.0f} EUR")
        evidence.append({"fact": f"Lease {unit_id}: small repairs up to {cap_item:.0f} EUR/item, "
                                 f"{cap_year:.0f} EUR/year; {spent:.0f} EUR used in {today.year}",
                         "source": ", ".join(tenant["sources"]) + ", 06_ticket_historie.csv"})
        if u.small_item_cost <= cap_item and spent + u.small_item_cost <= cap_year:
            bearer, reason = "tenant_small_repair", "Small repair on an item the tenant uses daily, within lease caps."
        else:
            bearer, reason = "landlord", "Small repair, but above the caps in the lease."
    else:
        bearer = "landlord"
        reason = "Maintenance of the rented property is the landlord's duty (§ 535 BGB)."
        if u.small_item and not tenant["small_repair_clause"]:
            reason += " Lease has no small-repair clause."
        if w and not w["under_warranty"] and w["warranty_until"]:
            reason += f" Warranty on {asset['id']} expired {w['warranty_until']}."
        if u.category == "roof" and not u.storm:
            reason += " No storm mentioned: wear and tear is not insured."
    steps.append(f"decide_cost_bearer -> {bearer}" + (f" (+{secondary})" if secondary else ""))

    # ---- 6. vendor ----------------------------------------------------------------
    emergency = u.urgency == "emergency"
    if (bearer == "tenant" and u.category == "appliance") or bearer == "manager_review":
        vendor = None
    elif bearer == "warranty":
        vendor = bm.find_vendor(vendor_id=asset["installer"])
    else:
        trade = TRADE.get(u.category, "handyman")
        if u.category == "lock_door" and not (u.severe or u.building_door or u.tenant_caused):
            trade = "handyman"
        vendor = bm.find_vendor(trade=trade, emergency=emergency)
    if vendor:
        steps.append(f"find_vendor -> {vendor['id']} {vendor['name']}" +
                     (" (original installer)" if bearer == "warranty" else "") +
                     (" (24/7)" if emergency and vendor.get("emergency_service") else ""))
        evidence.append({"fact": f"{vendor['name']}, {vendor['trade']}, tel {vendor['phone']}",
                         "source": ", ".join(vendor["sources"])})
        if emergency and not vendor.get("emergency_service"):
            flags.append({"level": "critical", "text": f"{vendor['name']} has no 24/7 service: call manually."})

    # ---- 7. patterns & known gaps ----------------------------------------------
    hist = bm.ticket_history(asset["id"] if asset else None, unit_id if not asset else None)
    if asset and len(hist) >= 2:
        units = sorted({h["unit"] for h in hist})
        flags.append({"level": "critical",
                      "text": f"Recurring: {len(hist)} earlier tickets on {asset['id']} in 90 days "
                              f"({', '.join(units)}). Book a root-cause inspection"
                              + (" and a replacement quote (out of warranty)." if w and not w["under_warranty"] else ".")})
        evidence.append({"fact": f"{len(hist)} tickets on {asset['id']} since {hist[0]['date']}",
                         "source": "06_ticket_historie.csv"})
    steps.append(f"ticket_history -> {len(hist)} related tickets in 90 days")
    for g in bm.gaps_for(asset["id"] if asset else None):
        flags.append({"level": g["severity"], "text": f"Known gap: {g['issue']}", "source": g["source"]})
    if policy and bearer in ("insurance", "warranty", "landlord") and (bearer == "insurance" or secondary):
        flags.append({"level": "warning", "text": f"Report to {policy['insurer']} by {policy['report_by']} "
                                                  f"(policy {policy['policy']}); ask tenant for photos."})
    if u.category == "gas":
        flags.append({"level": "critical", "text": "Gas: tenant told to leave and call 112 / gas utility emergency line."})

    eta = ETA[u.urgency]
    out.update(cost_bearer=bearer, secondary_bearer=secondary, reason=reason,
               asset_id=asset["id"] if asset else None,
               vendor={k: vendor[k] for k in ("id", "name", "phone", "trade")} if vendor else None, eta=eta)
    out["understanding"] = as_dict(u)
    out["tenant_reply"] = replies.tenant_reply(lang, u.category, u.urgency, vendor, bearer, eta)
    out["work_order"] = replies.work_order(mem, unit, tenant, message, asset, bearer, secondary, policy, u.urgency) if vendor else None
    out["insurance_note"] = replies.insurance_note(policy, unit_id, message) if policy and (bearer == "insurance" or secondary) else None
    return out
