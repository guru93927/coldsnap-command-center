"""Understand a tenant message: category, urgency, language, sub-component, tenant-caused.

Default: a transparent multilingual rule classifier (DE / EN / TR) so the demo runs
offline and is fully explainable. Set USE_LLM=1 and ANTHROPIC_API_KEY to use an LLM
for this step instead; its output is validated against the same schema and falls back
to the rules if it is invalid.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, asdict, field

CATEGORIES = {
    "gas": ["gasgeruch", "riecht nach gas", "nach gas", "smell of gas", "smell gas", "smells like gas", "gas smell", "gaz kokusu"],
    "water_leak": ["tropft", "undicht", "leck", "wasserfleck", "wasserschaden", "nass", "läuft wasser",
                   "wasser kommt", "wasser läuft", "überschwemm", "leak", "leaking", "dripping", "water coming", "flood",
                   "wet stain", "water stain", "sızı", "damlıyor", "su geliyor", "su akıyor", "verstopft",
                   "clogged", "tıkandı", "spülkasten", "toilet keeps running", "wasserhahn"],
    "heating": ["heizung", "heizkörper", "heating", "radiator", "heater", "kalorifer", "petek",
                "ısınmıyor", "thermostat"],
    "hot_water": ["warmwasser", "warmes wasser", "warmem wasser", "hot water", "lukewarm", "lauwarm",
                  "sıcak su", "kein heißes", "no warm water"],
    "electrical": ["strom", "sicherung", "steckdose", "lichtschalter", "funken", "kurzschluss",
                   "power", "socket", "outlet", "fuse", "light switch", "sparks", "elektrik", "priz",
                   "sigorta"],
    "lock_door": ["schlüssel", "ausgesperrt", "schloss", "haustür", "briefkasten", "locked out", "lock",
                  "key", "front door", "mailbox", "anahtar", "kilit", "kapı", "zugefallen",
                  "stehe draußen", "can't get in", "komme nicht rein"],
    "window_glass": ["fenster", "scheibe", "glas", "window", "glass", "pencere", "cam "],
    "appliance": ["geschirrspüler", "spülmaschine", "dishwasher", "bulaşık makinesi", "backofen",
                  "herd", "oven", "stove", "fırın", "waschmaschine", "washing machine"],
    "pest": ["maus", "mäuse", "ratte", "kakerlak", "mice", "mouse", "rat ", "rats", "cockroach",
             "fare", "hamamböceği"],
    "mould": ["schimmel", "mould", "mold", "küf"],
    "roof": ["dach", "roof", "çatı"],
    "ice_snow": ["glatteis", "spiegelglatt", "ausgerutscht", "rutschig", "vereist", "nicht geräumt",
                 "nicht gestreut", "icy", "slippery", "black ice", "not gritted", "not cleared", "slipped",
                 "buzlanma", "kaygan", "kaydım", "kar temizlenmemiş"],
    "smoke_detector": ["rauchmelder", "smoke detector", "smoke alarm", "duman dedektörü"],
}
# when several categories match, the more specific/safety-relevant one wins
PRIORITY = ["gas", "smoke_detector", "mould", "pest", "appliance", "roof", "ice_snow", "hot_water", "heating",
            "electrical", "window_glass", "lock_door", "water_leak"]

STORM = ["sturm", "unwetter", "gewitter", "hagel", "storm", "hail", "fırtına", "dolu"]
TENANT_CAUSED = ["aus versehen", "versehentlich", "habe ich", "ich habe", "kaputt gemacht",
                 "fallen lassen", "mein sohn", "meine tochter", "unser kind", "verloren",
                 "accidentally", "my fault", "i dropped", "i broke", "my son", "my daughter",
                 "my kid", "i lost", "lost my", "yanlışlıkla", "kırdım", "oğlum", "kızım",
                 "kaybettim", "düşürdüm", "zugefallen", "slammed shut", "kapı kapandı",
                 "schlüssel steckt innen", "keys inside", "anahtar içeride"]
SEVERE = ["stark", "läuft aus", "wasser läuft", "überschwemm", "flood", "pouring", "a lot of water", "everywhere",
          "überall", "her yer", "çok su", "durmuyor", "won't stop", "hört nicht auf", "funken",
          "sparks", "brandgeruch", "burning smell", "yanık kokusu", "kein strom in der ganzen",
          "no power in the whole", "ausgesperrt", "locked out", "kapıda kaldım",
          "can't get in", "cannot get in", "komme nicht rein", "içeri giremiyorum", "stehe draußen"]

# sub-components inside the tenant's flat (small-repair candidates), with typical cost in EUR
SMALL_ITEMS = {
    "wasserhahn": ("tap", 90), "tap": ("tap", 90), "faucet": ("tap", 90), "musluk": ("tap", 90),
    "spülkasten": ("toilet_flush", 95), "toilet keeps running": ("toilet_flush", 95),
    "sifon": ("drain", 85), "abfluss": ("drain", 85), "verstopft": ("drain", 85), "clogged": ("drain", 85),
    "tıkandı": ("drain", 85), "duschkopf": ("shower_head", 40), "shower head": ("shower_head", 40),
    "steckdose": ("socket", 70), "socket": ("socket", 70), "outlet": ("socket", 70), "priz": ("socket", 70),
    "lichtschalter": ("light_switch", 60), "light switch": ("light_switch", 60),
    "thermostat": ("thermostat_head", 75), "thermostatkopf": ("thermostat_head", 75),
    "briefkasten": ("mailbox_lock", 45), "mailbox": ("mailbox_lock", 45),
    "fenstergriff": ("window_handle", 50), "window handle": ("window_handle", 50),
    "türgriff": ("door_handle", 60), "door handle": ("door_handle", 60),
}
ITEM_CATEGORY = {"tap": "water_leak", "toilet_flush": "water_leak", "drain": "water_leak",
                 "shower_head": "water_leak", "socket": "electrical", "light_switch": "electrical",
                 "thermostat_head": "heating", "mailbox_lock": "lock_door", "door_handle": "lock_door",
                 "window_handle": "window_glass"}
BUILDING_DOOR = ["haustür", "front door", "main door", "building door", "apartman kapısı", "bina kapısı"]
FROM_PIPES = ["decke", "ceiling", "tavan", "wand", "wall", "duvar", "rohr", "pipe", "boru", "steig",
              "von oben", "from above", "upstairs", "yukarı"]


@dataclass
class Understanding:
    category: str
    urgency: str
    language: str
    tenant_caused: bool
    storm: bool
    severe: bool
    small_item: str | None = None
    small_item_cost: float | None = None
    building_door: bool = False
    from_pipes: bool = False
    matched: dict = field(default_factory=dict)
    engine: str = "rules"


def detect_language(text: str) -> str:
    t = text.lower()
    if re.search(r"[؀-ۿ]", t):
        return "ar"
    tr_hits = len(re.findall(r"[ğış]", t)) + sum(w in t.split() for w in ["ve", "bir", "evde", "lütfen", "yok", "çok", "var"])
    de_hits = len(re.findall(r"[äöß]", t)) + sum(w in t.split() for w in ["ich", "und", "die", "der", "nicht", "bitte", "ist", "kein", "meine"])
    en_hits = sum(w in t.split() for w in ["the", "and", "is", "my", "not", "please", "there", "i", "it"])
    best = max([("tr", tr_hits), ("de", de_hits), ("en", en_hits)], key=lambda x: x[1])
    return best[0] if best[1] > 0 else "de"


def _has(t, words):
    return [w for w in words if w in t]


def classify_rules(text: str, month: int) -> Understanding:
    t = " " + text.lower() + " "
    matched = {c: _has(t, kws) for c, kws in CATEGORIES.items()}
    hits = [c for c in PRIORITY if matched[c]]
    category = hits[0] if hits else "other"
    # a leak that comes with a storm, or a roof mention, is a roof leak
    storm = bool(_has(t, STORM))
    if category == "water_leak" and matched["roof"]:
        category = "roof"
    tenant_caused = bool(_has(t, TENANT_CAUSED))
    severe = bool(_has(t, SEVERE))
    small = next(((v[0], v[1]) for k, v in SMALL_ITEMS.items()
                  if k in t and ITEM_CATEGORY[v[0]] == category), (None, None))
    heating_season = month in (10, 11, 12, 1, 2, 3, 4)

    if category == "gas":
        urgency = "emergency"
    elif category in ("water_leak", "roof", "electrical") and severe:
        urgency = "emergency"
    elif category == "ice_snow":
        urgency = "emergency" if _has(t, ["gestürzt", "hingefallen", "verletzt", "fell", "injured", "düştüm"]) else "urgent"
    elif category == "lock_door" and severe:
        urgency = "urgent"
    elif category == "heating" and heating_season and not small[0]:
        urgency = "urgent"
    elif category == "electrical" and not small[0]:
        urgency = "urgent"
    elif category in ("water_leak", "roof", "hot_water", "window_glass", "pest") and not small[0]:
        urgency = "urgent"
    elif category == "lock_door" and _has(t, BUILDING_DOOR):
        urgency = "urgent"
    else:
        urgency = "normal"

    return Understanding(category=category, urgency=urgency, language=detect_language(text),
                         tenant_caused=tenant_caused, storm=storm, severe=severe,
                         small_item=small[0], small_item_cost=small[1],
                         building_door=bool(_has(t, BUILDING_DOOR)), from_pipes=bool(_has(t, FROM_PIPES)),
                         matched={k: v for k, v in matched.items() if v})


def classify_llm(text: str, month: int) -> Understanding | None:
    """Optional LLM path. Returns None on any failure so the caller falls back to rules."""
    key = os.getenv("ANTHROPIC_API_KEY")
    if not (key and os.getenv("USE_LLM") == "1"):
        return None
    try:
        import httpx
        schema = {k: "" for k in ["category", "urgency", "language", "tenant_caused", "storm", "severe",
                                  "small_item", "building_door", "from_pipes"]}
        prompt = (
            "You triage tenant maintenance messages for a German property manager. "
            f"Allowed categories: {list(CATEGORIES)} or 'other'. Urgency: emergency|urgent|normal "
            f"(it is month {month}; heating loss in Oct-Apr is urgent). language: de|en|tr|ar. "
            f"small_item: one of {sorted({v[0] for v in SMALL_ITEMS.values()})} or null. "
            f"Return ONLY JSON with keys {list(schema)}.\n\nMessage: {text}")
        r = httpx.post("https://api.anthropic.com/v1/messages", timeout=20, headers={
            "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": os.getenv("LLM_MODEL", "claude-haiku-5-5"), "max_tokens": 300,
                  "messages": [{"role": "user", "content": prompt}]})
        data = json.loads(re.search(r"\{.*\}", r.json()["content"][0]["text"], re.S).group(0))
        if data["category"] not in list(CATEGORIES) + ["other"] or data["urgency"] not in ("emergency", "urgent", "normal"):
            return None
        cost = next((v[1] for v in SMALL_ITEMS.values() if v[0] == data.get("small_item")), None)
        return Understanding(category=data["category"], urgency=data["urgency"],
                             language=data.get("language", "de"), tenant_caused=bool(data["tenant_caused"]),
                             storm=bool(data["storm"]), severe=bool(data["severe"]),
                             small_item=data.get("small_item"), small_item_cost=cost,
                             building_door=bool(data["building_door"]), from_pipes=bool(data["from_pipes"]),
                             engine="llm")
    except Exception:
        return None


def understand(text: str, month: int) -> Understanding:
    return classify_llm(text, month) or classify_rules(text, month)


def as_dict(u: Understanding) -> dict:
    return asdict(u)
