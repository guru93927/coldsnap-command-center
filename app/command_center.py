"""During the cold snap: one agent watching every building in real time.

Handles a stream of events (tenant messages, vendor updates, winter-service check-ins) and the clock:

* Incident detection   3+ flats in one building report heating within 2 h  ->  ONE building-wide
                       incident, ONE emergency work order (with the worn part from the technician's
                       notes), status updates broadcast to every tenant in their language.
* Self-help            "one radiator cold and gurgling"  ->  bleeding guide, auto-follow-up, no visit.
* Winter service       on snow/ice days every building needs a photo check-in by 07:00 (Sun 09:00);
                       missing -> alert + ad-hoc order before anyone slips.
* Rent-risk meter      outage hours x rent x guidance band  ->  € exposure, heater offers.
* Everything else      falls through to the v1 context-aware triage agent (agent.py).

Safety-critical actions (building-wide heating outage in frost, ice on paths) are dispatched
immediately and the manager is notified; everything else waits for approval.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from .agent import triage
from .classify import understand
from .memory import BuildingMemory
from .weather import summarize, temp_at
from . import winter_texts as T

SINGLE_RADIATOR = re.compile(r"(\bein heizkörper|\beiner der heizkörper|\bone radiator|\bone of the radiators|"
                             r"\bbir kalorifer|\bbir petek|gluckert|gurgl|guruld)", re.I)
RESOLVED = re.compile(r"(hat geklappt|wieder warm|funktioniert wieder|works now|it worked|warm again|fixed now|"
                      r"düzeldi|ısındı)", re.I)
STILL = re.compile(r"(immer noch|noch immer|still cold|still not|hala soğuk|hâlâ soğuk)", re.I)
COLD = re.compile(r"(kalt|heizung|heizkörper|cold|heating|radiator|soğuk|kalorifer|ısınm)", re.I)
VULNERABLE = re.compile(r"(baby|säugling|kleinkind|schwanger|pflegebedürftig|rollstuhl|newborn|infant|pregnant|"
                        r"elderly|bebek|hamile|yaşlı)", re.I)


@dataclass
class Config:
    incident_threshold: int = 3          # distinct flats
    incident_window_min: int = 120
    hold_min: int = 30                   # wait this long for more reports before a single ticket
    escalate_after_h: float = 4.0        # outage longer than this in frost -> heaters for everyone
    auto_dispatch_safety: bool = True


@dataclass
class Incident:
    id: str
    building: str
    asset: dict
    vendor: dict
    opened_at: datetime
    first_report_at: datetime
    part_hint: str | None
    reports: list = field(default_factory=list)
    units: set = field(default_factory=set)
    priority_units: set = field(default_factory=set)
    status: str = "dispatched"
    eta_arrival: datetime | None = None
    eta_restore: datetime | None = None
    resolved_at: datetime | None = None
    escalated: bool = False


def hhmm(d: datetime | None) -> str:
    return d.strftime("%H:%M") if d else "-"


class CommandCenter:
    def __init__(self, mem: dict, forecasts: dict, day: date, config: Config | None = None):
        self.mem, self.fc, self.day = mem, forecasts, day
        self.cfg = config or Config()
        self.bm = BuildingMemory(mem, day)
        self.wx = {b: summarize(h) for b, h in forecasts.items()}
        self.now = datetime.combine(day, datetime.min.time())
        self.timeline: list[dict] = []
        self.outbox: list[dict] = []
        self.incidents: dict[str, Incident] = {}
        self.tickets: list[dict] = []
        self.pending: dict[str, list[dict]] = {}
        self.selfhelp: dict[str, dict] = {}
        self.checkins: dict[str, list[datetime]] = {}
        self.ws_deadline_done: set = set()
        self.ice_orders: dict[str, datetime] = {}
        self.new_dispatches: list[Incident] = []
        self.alerts: list[dict] = []

    # ---- logging -----------------------------------------------------------------
    def log(self, kind: str, building: str | None, title: str, detail: str = "", **extra):
        self.timeline.append({"t": hhmm(self.now), "ts": self.now.isoformat(), "kind": kind, "building": building,
                              "title": title, "detail": detail, **extra})

    def send_tenant(self, unit: str, text: str, kind: str = "reply"):
        tenant = self.bm.tenant_of(unit)
        self.outbox.append({"t": hhmm(self.now), "to": "tenant", "unit": unit, "kind": kind,
                            "name": tenant["name"] if tenant else unit, "text": text})

    def broadcast(self, building: str, texts: dict, title: str, exclude: set | None = None, **fmt):
        sent = 0
        for t in self.bm.tenants(building):
            if exclude and t["unit"] in exclude:
                continue
            self.send_tenant(t["unit"], texts[T.pick(t["language"])].format(**fmt), kind="broadcast")
            sent += 1
        sample = texts["en"].format(**fmt)
        self.log("broadcast", building, f"{title} → {sent} tenants (DE/EN/TR)", sample, count=sent)
        return sent

    def alert(self, building: str, level: str, title: str, detail: str = ""):
        a = {"t": hhmm(self.now), "building": building, "level": level, "title": title, "detail": detail}
        self.alerts.append(a)
        self.log("alert", building, title, detail, level=level)

    def temp(self, building: str) -> float:
        return temp_at(self.fc[building], self.now)

    def addr(self, building: str) -> str:
        return self.mem["nodes"][building]["address"].split(",")[0]

    # ---- clock -------------------------------------------------------------------
    def advance(self, to: datetime):
        """Fire timers that fall due before `to`."""
        while True:
            due = self._next_timer()
            if not due or due[0] > to:
                break
            self.now = due[0]
            due[1]()
        self.now = max(self.now, to)

    def _next_timer(self):
        timers = []
        for asset_id, reps in self.pending.items():
            if reps:
                timers.append((reps[0]["at"] + timedelta(minutes=self.cfg.hold_min),
                               lambda a=asset_id: self._release_pending(a)))
        for unit, sh in self.selfhelp.items():
            if sh["status"] == "open" and not sh.get("checked"):
                timers.append((sh["opened"] + timedelta(hours=1), lambda u=unit: self._selfhelp_check(u)))
        for b in self.mem["buildings"]:
            if self.day.isoformat() in self.wx[b]["winter_service_days"] and b not in self.ws_deadline_done:
                hour = 9 if self.day.weekday() == 6 else 7
                timers.append((datetime.combine(self.day, datetime.min.time()).replace(hour=hour),
                               lambda b=b: self._winter_service_deadline(b)))
        return min(timers, key=lambda x: x[0]) if timers else None

    def _selfhelp_check(self, unit: str):
        sh = self.selfhelp[unit]
        sh["checked"] = True
        tenant = self.bm.tenant_of(unit)
        self.send_tenant(unit, T.SELF_HELP_CHECK[T.pick(tenant["language"])])
        self.log("agent", self.bm.building_of(unit), f"{unit}: 1-hour follow-up on the self-help guide", "")

    # ---- tenant messages ----------------------------------------------------------
    def on_tenant(self, at: datetime, unit: str, text: str):
        self.advance(at)
        b = self.bm.building_of(unit)
        tenant = self.bm.tenant_of(unit)
        u = understand(text, self.day.month)
        lang = T.pick(u.language if u.language in T.LANGS else tenant["language"])
        self.log("tenant", b, f"{unit} · {tenant['name']}", text, unit=unit, lang=u.language)

        # 1. follow-up on a self-help session
        sh = self.selfhelp.get(unit)
        if sh and sh["status"] == "open":
            if RESOLVED.search(text):
                sh["status"] = "solved"
                self.send_tenant(unit, T.SELF_HELP_DONE[lang])
                self.log("agent", b, f"{unit}: solved by self-help, no technician visit needed", "")
                return
            if STILL.search(text):
                sh["status"] = "escalated"
                return self._ticket(unit, sh["text"], b, note="self-help did not work")

        # 2. anything heating-related while a building incident is open
        inc = self._open_incident(b)
        if inc and (u.category in ("heating", "hot_water") or COLD.search(text)) and not SINGLE_RADIATOR.search(text):
            return self._attach(inc, unit, text, lang, at)

        # 2b. still cold right after an outage was fixed: usually air in the radiators after the restart
        done = self._recently_resolved(b)
        if done and (COLD.search(text) or STILL.search(text)):
            self.selfhelp[unit] = {"opened": at, "status": "open", "text": text}
            self.send_tenant(unit, T.SELF_HELP[lang])
            self.log("agent", b, f"{unit}: still cold after {done.id} was fixed → bleeding guide sent",
                     f"Heating restored at {hhmm(done.resolved_at)}; after a restart radiators often hold air. "
                     "Technician only if it stays cold.")
            return

        # 3. heating / hot water
        if u.category in ("heating", "hot_water"):
            if u.category == "heating" and SINGLE_RADIATOR.search(text):
                self.selfhelp[unit] = {"opened": at, "status": "open", "text": text}
                self.send_tenant(unit, T.SELF_HELP[lang])
                self.log("agent", b, f"{unit}: single radiator → self-help guide sent ({lang.upper()})",
                         "Bleed-the-radiator steps, auto follow-up in 1 h; technician only if it stays cold.")
                return
            asset = self.bm.find_asset(u.category, unit)
            if asset and not u.small_item:
                return self._report_central(asset, unit, text, lang, at)

        # 4. ice / snow on paths
        if u.category == "ice_snow":
            return self._ice(unit, text, lang, u.urgency)

        # 5. everything else: v1 context-aware triage
        self._ticket(unit, text, b)

    def _ticket(self, unit: str, text: str, b: str, note: str = ""):
        r = triage(text, unit, self.mem, self.day)
        tk = {"id": f"TK-{len(self.tickets) + 1:03d}", "t": hhmm(self.now), "unit": unit, "building": b,
              "category": r["understanding"]["category"], "urgency": r["understanding"]["urgency"],
              "cost_bearer": r["cost_bearer"], "vendor": (r["vendor"] or {}).get("name"),
              "flags": [f["text"] for f in r["flags"]], "note": note}
        self.tickets.append(tk)
        self.send_tenant(unit, r["tenant_reply"])
        detail = f"who pays: {r['cost_bearer']}; vendor: {tk['vendor'] or '—'}"
        if tk["flags"]:
            detail += " | " + " | ".join(tk["flags"][:2])
        self.log("ticket", b, f"{tk['id']} {unit}: {tk['category'].replace('_', ' ')} ({tk['urgency']})"
                 + (f" – {note}" if note else ""), detail, flags=tk["flags"])
        return tk

    # ---- heating incidents -----------------------------------------------------------
    def _open_incident(self, b: str) -> Incident | None:
        return next((i for i in self.incidents.values() if i.building == b and i.status != "resolved"), None)

    def _recently_resolved(self, b: str, hours: float = 6) -> Incident | None:
        return next((i for i in self.incidents.values() if i.building == b and i.status == "resolved"
                     and self.now - i.resolved_at <= timedelta(hours=hours)), None)

    def _report_central(self, asset: dict, unit: str, text: str, lang: str, at: datetime):
        reps = self.pending.setdefault(asset["id"], [])
        reps.append({"at": at, "unit": unit, "text": text, "lang": lang})
        window = at - timedelta(minutes=self.cfg.incident_window_min)
        units = {r["unit"] for r in reps if r["at"] >= window}
        if VULNERABLE.search(text):
            self.send_tenant(unit, T.HEATER_OFFER[lang])
        if len(units) >= self.cfg.incident_threshold:
            return self._open(asset, reps)
        self.send_tenant(unit, T.HOLDING[lang])
        self.log("agent", asset["building"], f"{unit}: report linked to {asset['id']} "
                 f"({len(units)}/{self.cfg.incident_threshold} flats) – watching for a building-wide outage", "")

    def _release_pending(self, asset_id: str):
        reps = self.pending.pop(asset_id, [])
        for r in reps:  # not enough reports: handle each as a normal ticket
            self._ticket(r["unit"], r["text"], self.bm.n[asset_id]["building"],
                         note="single report, no building-wide pattern")

    def _open(self, asset: dict, reps: list[dict]):
        b = asset["building"]
        self.pending.pop(asset["id"], None)
        vendor = self.bm.service_vendor(asset)
        worn = next((g["issue"] for g in self.bm.building_gaps(b) if "verschlissen" in g["issue"].lower()), None)
        part = None
        if worn:
            m = re.search(r"(\w+)\s+verschlissen", worn)
            part = m.group(1) if m else worn
        inc = Incident(id=f"INC-{len(self.incidents) + 1:03d}", building=b, asset=asset, vendor=vendor,
                       opened_at=self.now, first_report_at=reps[0]["at"], part_hint=part)
        for r in reps:
            inc.reports.append(r)
            inc.units.add(r["unit"])
            if VULNERABLE.search(r["text"]):
                inc.priority_units.add(r["unit"])
        self.incidents[inc.id] = inc
        temp = self.temp(b)
        self.log("incident", b, f"{inc.id} opened: building-wide heating outage at {self.addr(b)}",
                 f"{len(inc.units)} flats reported since {hhmm(inc.first_report_at)}; {len(reps)} messages merged "
                 f"into one incident. Outside {temp:.1f} °C.", incident=inc.id)
        wo = self._work_order(inc, temp)
        self.outbox.append({"t": hhmm(self.now), "to": "vendor", "vendor": vendor["name"], "kind": "work_order", "text": wo})
        self.log("vendor_out", b, f"Emergency work order → {vendor['name']} ({vendor['phone']})", wo, incident=inc.id)
        self.alert(b, "info", f"{inc.id}: auto-dispatched under the safety policy (frost + whole building)",
                   "Manager notified; can override in one click.")
        self.new_dispatches.append(inc)
        return inc

    def _work_order(self, inc: Incident, temp: float) -> str:
        a = inc.asset
        lines = [f"NOTDIENST | Gebäudeweiter Heizungsausfall | {self.mem['nodes'][inc.building]['address']}",
                 f"Anlage: {a['id']} {a['name']} (Einbau {a['installed'][:4]})",
                 f"Meldungen: {len(inc.units)} Wohnungen seit {hhmm(inc.first_report_at)}, Außentemperatur {temp:.1f} °C"]
        if inc.part_hint:
            lines.append(f"Hinweis aus der Akte: {inc.part_hint} bei letzter Wartung als verschlissen notiert "
                         f"– bitte Ersatzteil mitbringen")
        lines.append("Abrechnung: Instandhaltung – Rechnung an Verwaltung")
        lines.append("Bitte Ankunftszeit bestätigen.")
        return "\n".join(lines)

    def _attach(self, inc: Incident, unit: str, text: str, lang: str, at: datetime):
        new = unit not in inc.units
        inc.reports.append({"at": at, "unit": unit, "text": text, "lang": lang})
        inc.units.add(unit)
        if inc.status == "dispatched":
            status = T.STATUS["dispatched"][lang].format(eta=hhmm(inc.eta_arrival) if inc.eta_arrival else "—")
        else:
            status = T.STATUS["on_site"][lang].format(eta=hhmm(inc.eta_restore))
        self.send_tenant(unit, T.INCIDENT_KNOWN[lang].format(status=status))
        extra = ""
        if VULNERABLE.search(text) and unit not in inc.priority_units:
            inc.priority_units.add(unit)
            self.send_tenant(unit, T.HEATER_OFFER[lang])
            self.alert(inc.building, "high", f"{unit}: vulnerable household in {inc.id} – deliver a temporary heater first",
                       f"Tenant wrote: \"{text}\"")
            extra = " + heater offered"
        self.log("agent", inc.building, f"{unit}: merged into {inc.id}" + (" (new flat)" if new else " (follow-up)") + extra,
                 "Answered with live status, no new ticket.", incident=inc.id)

    def on_vendor(self, at: datetime, incident_id: str, status: str, eta: datetime | None = None, diag: str = ""):
        self.advance(at)
        inc = self.incidents[incident_id]
        b = inc.building
        if status == "ack":
            inc.eta_arrival = eta
            self.log("vendor_in", b, f"{inc.vendor['name']} confirmed, arrival ~{hhmm(eta)}", "", incident=inc.id)
            self.broadcast(b, T.INCIDENT_OPEN, f"{inc.id} status: technician on the way", vendor=inc.vendor["name"],
                           eta=hhmm(eta))
        elif status == "on_site":
            inc.status, inc.eta_restore = "on_site", eta
            self.log("vendor_in", b, f"{inc.vendor['name']} on site: {diag}; heating back ~{hhmm(eta)}", "", incident=inc.id)
            self.broadcast(b, T.INCIDENT_ONSITE, f"{inc.id} update: technician on site", diag=diag, eta=hhmm(eta))
            outage = (eta - inc.first_report_at).total_seconds() / 3600
            if outage > self.cfg.escalate_after_h and self.temp(b) < 0 and not inc.escalated:
                inc.escalated = True
                risk = self.risk(inc, at=eta)
                self.alert(b, "critical", f"{inc.id}: outage will last ~{outage:.1f} h in frost – deliver temporary heaters",
                           f"Estimated rent-reduction exposure ~€{risk['per_day']:.0f}/day for the building; "
                           f"heaters for {len(risk['units'])} flats are cheaper.")
                self.broadcast(b, T.HEATER_OFFER, f"{inc.id}: heater offer")
        elif status == "resolved":
            inc.status, inc.resolved_at = "resolved", at
            risk = self.risk(inc)
            self.log("vendor_in", b, f"{inc.vendor['name']}: heating restored", diag, incident=inc.id)
            self.broadcast(b, T.INCIDENT_RESOLVED, f"{inc.id} resolved: heating back on")
            self.log("incident", b, f"{inc.id} closed after {risk['hours']:.1f} h (from first report)",
                     f"Estimated rent-reduction exposure avoided per further day: ~€{risk['per_day']:.0f}. "
                     "Timeline stored as evidence of prompt action.", incident=inc.id)

    def risk(self, inc: Incident, at: datetime | None = None) -> dict:
        """Illustrative rent-reduction exposure using common guidance bands (not legal advice)."""
        end = inc.resolved_at or at or self.now
        hours = max((end - inc.first_report_at).total_seconds() / 3600, 0)
        tenants = self.bm.tenants(inc.building)
        min_temp = min(h["temp"] for h in self.fc[inc.building]
                       if inc.first_report_at.strftime("%Y-%m-%dT%H:00") <= h["t"] <= end.strftime("%Y-%m-%dT%H:00"))
        pct = 0.5 if (inc.asset["category"] == "heating" and min_temp < 0) else 0.3 if inc.asset["category"] == "heating" else 0.1
        per_day = sum(t["warm_rent"] for t in tenants) * pct / 30
        return {"hours": hours, "pct": pct, "min_temp": min_temp, "per_day": per_day,
                "so_far": per_day * hours / 24, "units": [t["unit"] for t in tenants]}

    # ---- winter service ----------------------------------------------------------------
    def on_checkin(self, at: datetime, building: str, vendor_id: str, photo: bool = True):
        self.advance(at)
        self.checkins.setdefault(building, []).append(at)
        v = self.bm.n[vendor_id]
        self.log("vendor_in", building, f"{v['name']} checked in at {self.addr(building)}"
                 + (" with photo" if photo else ""), "Stored as proof that clearing and gritting were done.")

    def _winter_service_deadline(self, b: str):
        self.ws_deadline_done.add(b)
        node = self.mem["nodes"][b]
        if self.checkins.get(b):
            return
        wx = self.wx[b]
        vid = node.get("winter_service_vendor")
        if vid:
            self.alert(b, "critical", f"No winter-service check-in at {self.addr(b)} by {hhmm(self.now)} on an ice day",
                       f"Calling {self.bm.n[vid]['name']}. Owner stays liable for slips.")
        else:
            v = self.bm.find_vendor(trade="winter_service")
            self.ice_orders[b] = self.now
            self.alert(b, "critical", f"Ice day and nobody is responsible for clearing {self.addr(b)}: "
                       f"ad-hoc order sent to {v['name']}",
                       f"{wx['snow_cm']} cm snow overnight, {self.temp(b):.1f} °C. Arrangement on file: "
                       f"'{node['winter_service']}', which doesn't transfer the duty. Owner liable if someone slips.")
            self.outbox.append({"t": hhmm(self.now), "to": "vendor", "vendor": v["name"], "kind": "work_order",
                                "text": f"Ad-hoc Winterdienst {node['address']}: Gehweg und Zugang räumen und streuen, "
                                        "Foto-Check-in bitte."})

    def _ice(self, unit: str, text: str, lang: str, urgency: str):
        b = self.bm.building_of(unit)
        self.send_tenant(unit, T.ICE_REPLY[lang])
        if b in self.ice_orders:
            self.log("agent", b, f"{unit}: ice report – already handled",
                     f"Ad-hoc winter service ordered at {hhmm(self.ice_orders[b])}, before this report.")
        elif self.checkins.get(b):
            self.log("agent", b, f"{unit}: ice report – re-gritting requested",
                     f"Contractor checked in at {hhmm(self.checkins[b][-1])}; asked to re-grit.")
        else:
            v = self.bm.find_vendor(trade="winter_service")
            self.ice_orders[b] = self.now
            self.alert(b, "critical", f"Ice reported at {self.addr(b)}: ad-hoc order sent to {v['name']}", text)
        if urgency == "emergency":
            self.alert(b, "critical", f"{unit}: possible injury on the path – check liability insurance, document now", text)
