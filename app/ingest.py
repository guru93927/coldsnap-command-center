"""Ingestion: messy building documents -> Building Memory (a knowledge graph for a portfolio).

Layout:
    data/shared/vendors.txt          vendor list used by all buildings
    data/<building-folder>/01_...    one folder per building (stammdaten, assets, leases,
                                     insurance, ticket history, handover notes)

Every extracted fact keeps a pointer to the document it came from, so the agent can
show its evidence. For real scanned PDFs, swap `parse_blocks` for OCR + an LLM extractor
that returns the same field names (see README, "Production path").
"""
from __future__ import annotations

import csv
import json
import re
import sys
from datetime import date
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
NON_BUILDING_DIRS = {"shared", "scenarios"}

# German field labels -> canonical keys
FIELD_MAP = {
    "Objekt-ID": "id", "Adresse": "address", "Baujahr": "year_built", "Heizung": "heating",
    "Koordinaten": "coords", "Winterdienst": "winter_service", "Eigentümer": "owner",
    "Einheit": "unit", "Lage": "position", "Fläche": "area", "Ausstattung": "equipment",
    "Besonderheit": "note", "Leerstand": "vacant",
    "Anlage": "asset", "Bezeichnung": "name", "Kategorie": "category", "Ort": "location",
    "Betrifft": "scope", "Einbau": "installed", "Errichter": "installer",
    "Gewährleistung bis": "warranty_until", "Wartungsvertrag": "maintenance_contract",
    "Wartung durch": "maintainer", "Letzte Wartung": "last_maintenance",
    "Mieter": "tenant", "Sprache": "language", "Mietbeginn": "lease_start", "Warmmiete": "warm_rent",
    "Kleinreparaturklausel": "small_repair_clause",
    "Kleinreparatur Einzelbetrag max": "small_repair_item_cap",
    "Kleinreparatur Jahresbetrag max": "small_repair_year_cap",
    "Mitvermietet": "included",
    "Dienstleister": "vendor", "Name": "name", "Gewerk": "trade",
    "Notdienst 24/7": "emergency_service", "Telefon": "phone",
    "Police": "policy", "Art": "type", "Versicherer": "insurer",
    "Gedeckte Gefahren": "perils", "Ausschlüsse": "exclusions", "Obliegenheiten": "duties",
    "Selbstbeteiligung": "deductible", "Meldefrist Tage": "report_within_days",
}

GAP_PATTERNS = re.compile(
    r"(nicht auffindbar|nicht vor|unvollständig|fehlen|fehlt|\?\?|unklar|gekündigt|keine regelung|"
    r"nicht abgesperrt|noch offen|verschlissen)", re.I)


def parse_blocks(text: str) -> list[dict]:
    """Split a document on '---' and read 'Label: value' lines into dicts."""
    blocks = []
    for chunk in re.split(r"^\s*---\s*$", text, flags=re.M):
        rec = {}
        for line in chunk.splitlines():
            m = re.match(r"^\s*([^:=\n]{2,40}?):\s*(.+?)\s*$", line)
            if m and m.group(1).strip() in FIELD_MAP:
                rec[FIELD_MAP[m.group(1).strip()]] = m.group(2).strip()
        if rec:
            blocks.append(rec)
    return blocks


def _to_date(v: str | None):
    try:
        return date.fromisoformat(v) if v else None
    except ValueError:
        return None


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class Ingestor:
    """Ingests the shared vendor list and every building folder into one graph."""

    def __init__(self, data_dir: str | Path, today: date | None = None):
        self.data_dir = Path(data_dir)
        self.today = today or date.today()
        self.nodes: dict[str, dict] = {}
        self.edges: list[tuple[str, str, str]] = []
        self.gaps: list[dict] = []
        self.buildings: list[str] = []
        self.documents: list[str] = []
        self.building_id = ""

    def add(self, nid: str, ntype: str, source: str, **attrs):
        node = self.nodes.setdefault(nid, {"id": nid, "type": ntype, "sources": []})
        node.update({k: v for k, v in attrs.items() if v is not None})
        if source not in node["sources"]:
            node["sources"].append(source)

    def link(self, a: str, rel: str, b: str):
        if (a, rel, b) not in self.edges:
            self.edges.append((a, rel, b))

    def gap(self, issue: str, source: str, severity: str = "warning", building: str | None = None):
        self.gaps.append({"issue": issue, "source": source, "severity": severity,
                          "building": building or self.building_id})

    def _src(self, path: Path) -> str:
        return f"{path.parent.name}/{path.name}"

    # ---- per document type -------------------------------------------------
    def _vendors(self, path: Path):
        for v in parse_blocks(_read(path)):
            if "vendor" in v:
                self.add(v["vendor"], "vendor", self._src(path), name=v.get("name"), trade=v.get("trade"),
                         emergency_service=v.get("emergency_service") == "ja", phone=v.get("phone"))

    def _building(self, path: Path):
        blocks = parse_blocks(_read(path))
        b = next(x for x in blocks if "id" in x)
        self.building_id = b["id"]
        self.buildings.append(b["id"])
        lat, lon = (float(x) for x in b.get("coords", "51.22, 6.78").split(","))
        ws = b.get("winter_service", "")
        ws_vendor = re.search(r"\bV\d{2}\b", ws)
        self.add(b["id"], "building", self._src(path), address=b.get("address"), year_built=b.get("year_built"),
                 heating=b.get("heating"), lat=lat, lon=lon, folder=path.parent.name, owner=b.get("owner"),
                 winter_service=ws, winter_service_vendor=ws_vendor.group(0) if ws_vendor else None)
        if not ws_vendor:
            self.gap(f"Winter service not contracted ('{ws}'): clearing duty and liability stay with the owner",
                     self._src(path), "critical")
        for u in (x for x in blocks if "unit" in x):
            vacant = u.get("vacant", "").lower() == "ja"
            self.add(u["unit"], "unit", self._src(path), building=b["id"], position=u.get("position"),
                     area=u.get("area"), equipment=u.get("equipment"), note=u.get("note"), vacant=vacant,
                     top_floor=("Dach" in (u.get("position", "") + u.get("note", ""))))
            self.link(u["unit"], "IN", b["id"])

    def _assets(self, path: Path):
        for a in parse_blocks(_read(path)):
            if "asset" not in a:
                continue
            w = _to_date(a.get("warranty_until"))
            self.add(a["asset"], "asset", self._src(path), building=self.building_id, name=a.get("name"),
                     category=a.get("category"), location=a.get("location"), scope=a.get("scope"),
                     installed=a.get("installed"), installer=a.get("installer"),
                     warranty_until=a.get("warranty_until"), under_warranty=bool(w and w >= self.today),
                     maintenance_contract=a.get("maintenance_contract"), maintainer=a.get("maintainer"),
                     last_maintenance=a.get("last_maintenance"))
            scope = a.get("scope", "Gebäude")
            self.link(a["asset"], "SERVES", self.building_id if scope == "Gebäude" else scope)
            for role in ("installer", "maintainer"):
                if (a.get(role) or "").startswith("V"):
                    self.link(a["asset"], role.upper(), a[role])
            if a.get("maintenance_contract") == "unklar":
                self.gap(f"{a['asset']} ({a['name']}): maintenance contract status unclear", self._src(path))
            lm = _to_date(a.get("last_maintenance"))
            if lm and (self.today - lm).days > 365:
                self.gap(f"{a['asset']} ({a['name']}): annual maintenance overdue (last {lm})",
                         self._src(path), "critical")

    def _leases(self, path: Path):
        for l in parse_blocks(_read(path)):
            if "unit" not in l:
                continue
            tid = f"T-{l['unit']}"
            clause = l.get("small_repair_clause", "nein").lower() == "ja"
            self.add(tid, "tenant", self._src(path), building=self.building_id, unit=l["unit"],
                     name=l.get("tenant"), language=l.get("language", "de"), lease_start=l.get("lease_start"),
                     warm_rent=float(l.get("warm_rent", 0)), small_repair_clause=clause,
                     small_repair_item_cap=float(l["small_repair_item_cap"]) if clause else 0.0,
                     small_repair_year_cap=float(l["small_repair_year_cap"]) if clause else 0.0,
                     included=l.get("included"))
            self.link(tid, "RENTS", l["unit"])

    def _insurance(self, path: Path):
        for p in parse_blocks(_read(path)):
            if "policy" in p:
                self.add(p["policy"], "policy", self._src(path), building=self.building_id,
                         policy_type=p.get("type"), insurer=p.get("insurer"),
                         perils=[x.strip() for x in p.get("perils", "").split(",")],
                         exclusions=p.get("exclusions"), duties=p.get("duties"),
                         deductible=float(p.get("deductible", 0)),
                         report_within_days=int(p.get("report_within_days", 7)))
                self.link(p["policy"], "COVERS", self.building_id)

    def _tickets(self, path: Path):
        with path.open(encoding="utf-8", newline="") as f:
            for i, row in enumerate(csv.DictReader(f), 1):
                tid = f"TK-{self.building_id[4:]}-{i:03d}"
                self.add(tid, "ticket", self._src(path), building=self.building_id, **row)
                self.link(tid, "IN_UNIT", row["unit"])
                if row.get("asset"):
                    self.link(tid, "CONCERNS", row["asset"])

    def _notes(self, path: Path):
        for line in _read(path).splitlines():
            line = line.strip("- ").strip()
            if line and GAP_PATTERNS.search(line):
                self.gap(line, self._src(path))

    def _ingest_building(self, folder: Path):
        order = [("01_", self._building), ("02_", self._assets), ("03_", self._leases),
                 ("05_", self._insurance), ("06_", self._tickets), ("07_", self._notes)]
        files = sorted(folder.iterdir())
        self.documents += [self._src(p) for p in files]
        for prefix, fn in order:
            for p in files:
                if p.name.startswith(prefix):
                    fn(p)
        # cross-document check: every occupied unit needs a lease
        for uid, n in self.nodes.items():
            if n["type"] == "unit" and n.get("building") == self.building_id:
                has_lease = any(e[1] == "RENTS" and e[2] == uid for e in self.edges)
                if not has_lease and not n.get("vacant"):
                    self.gap(f"{uid}: no lease found", "cross-check", "critical")

    def run(self) -> dict:
        shared = self.data_dir / "shared" / "vendors.txt"
        if shared.exists():
            self._vendors(shared)
            self.documents.append(self._src(shared))
        for folder in sorted(p for p in self.data_dir.iterdir()
                             if p.is_dir() and p.name not in NON_BUILDING_DIRS):
            self._ingest_building(folder)
        return {
            "buildings": self.buildings,
            "built_on": self.today.isoformat(),
            "documents": self.documents,
            "nodes": self.nodes,
            "edges": self.edges,
            "gaps": self.gaps,
        }


def build_memory(data_dir: str | Path = DATA_DIR, today: date | None = None) -> dict:
    return Ingestor(data_dir, today).run()


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    mem = build_memory(DATA_DIR, date(2026, 12, 1))
    out = DATA_DIR / "building_memory.json"
    out.write_text(json.dumps(mem, ensure_ascii=False, indent=2), encoding="utf-8")
    counts: dict[str, int] = {}
    for n in mem["nodes"].values():
        counts[n["type"]] = counts.get(n["type"], 0) + 1
    print(f"Ingested {len(mem['documents'])} documents for {len(mem['buildings'])} buildings -> "
          f"{sum(counts.values())} nodes {counts}, {len(mem['edges'])} edges, {len(mem['gaps'])} gaps")
    for g in mem["gaps"]:
        print(f"  [{g['severity']:8}] {g['building']:12} {g['issue']}  ({g['source']})")
    print(f"Saved {out}")


if __name__ == "__main__":
    main()
