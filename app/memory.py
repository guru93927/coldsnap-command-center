"""Building Memory: query tools the agents call. Every answer carries its source document."""
from __future__ import annotations

from datetime import date, timedelta


class BuildingMemory:
    def __init__(self, mem: dict, today: date):
        self.m = mem
        self.n = mem["nodes"]
        self.e = mem["edges"]
        self.today = today

    def by_type(self, t: str, building: str | None = None) -> list[dict]:
        return [x for x in self.n.values()
                if x["type"] == t and (building is None or x.get("building") == building)]

    @staticmethod
    def src(node: dict) -> str:
        return ", ".join(node["sources"])

    # ---- lookups -------------------------------------------------------------
    def building_of(self, unit_id: str) -> str:
        return self.n[unit_id]["building"]

    def units(self, building: str) -> list[dict]:
        return self.by_type("unit", building)

    def tenants(self, building: str) -> list[dict]:
        return self.by_type("tenant", building)

    def tenant_of(self, unit_id: str) -> dict | None:
        return next((self.n[a] for a, r, b in self.e if r == "RENTS" and b == unit_id), None)

    # ---- tools ---------------------------------------------------------------
    def get_unit_context(self, unit_id: str) -> dict:
        unit = self.n.get(unit_id)
        if not unit or unit["type"] != "unit":
            raise KeyError(f"Unknown unit {unit_id}")
        return {"unit": unit, "tenant": self.tenant_of(unit_id), "building": self.n[unit["building"]]}

    def find_asset(self, category: str, unit_id: str) -> dict | None:
        """Unit-specific asset first, then the building-wide one in the same building."""
        building = self.building_of(unit_id)
        cands = [a for a in self.by_type("asset", building) if a.get("category") == category]
        for a in cands:
            if a.get("scope") == unit_id:
                return a
        for a in cands:
            if a.get("scope") == "Gebäude":
                return a
        return None

    def check_warranty(self, asset: dict) -> dict:
        return {"asset": asset["id"], "under_warranty": asset.get("under_warranty", False),
                "warranty_until": asset.get("warranty_until"), "installer": asset.get("installer"),
                "source": self.src(asset)}

    def check_insurance(self, peril: str, building: str) -> dict | None:
        for p in self.by_type("policy", building):
            if peril in p.get("perils", []):
                return {"policy": p["id"], "type": p["policy_type"], "insurer": p["insurer"],
                        "deductible": p["deductible"], "report_within_days": p["report_within_days"],
                        "report_by": (self.today + timedelta(days=p["report_within_days"])).isoformat(),
                        "exclusions": p.get("exclusions"), "duties": p.get("duties"), "source": self.src(p)}
        return None

    def find_vendor(self, vendor_id: str | None = None, trade: str | None = None,
                    emergency: bool = False) -> dict | None:
        if vendor_id and vendor_id in self.n:
            return self.n[vendor_id]
        vs = [v for v in self.by_type("vendor") if v.get("trade") == trade]
        if emergency:
            vs.sort(key=lambda v: not v.get("emergency_service"))
        return vs[0] if vs else None

    def service_vendor(self, asset: dict, emergency: bool = True) -> dict | None:
        """Who to call for a building asset: maintainer, then installer, then any firm of that trade."""
        for role in ("maintainer", "installer"):
            vid = asset.get(role) or ""
            if vid.startswith("V") and vid in self.n:
                return self.n[vid]
        trade = {"heating": "heating", "hot_water": "heating", "water_pipes": "plumbing"}.get(asset["category"])
        return self.find_vendor(trade=trade, emergency=emergency)

    def ticket_history(self, asset_id: str | None, unit_id: str | None = None,
                       days: int = 90) -> list[dict]:
        since = self.today - timedelta(days=days)
        out = []
        for t in self.by_type("ticket"):
            d = date.fromisoformat(t["date"])
            if d < since:
                continue
            if asset_id and t.get("asset") == asset_id:
                out.append(t)
            elif not asset_id and unit_id and t.get("unit") == unit_id:
                out.append(t)
        return sorted(out, key=lambda t: t["date"])

    def gaps_for(self, asset_id: str | None) -> list[dict]:
        if not asset_id:
            return []
        asset = self.n[asset_id]
        keys = [asset_id]
        if asset.get("category") in ("heating", "hot_water"):
            keys += ["Heizung", "Kessel", "Zündelektrode"]
        return [g for g in self.m["gaps"] if g.get("building") == asset.get("building")
                and any(k.lower() in g["issue"].lower() for k in keys)]

    def building_gaps(self, building: str) -> list[dict]:
        return [g for g in self.m["gaps"] if g.get("building") == building]
