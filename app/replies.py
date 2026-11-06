"""Drafts: tenant reply (in the tenant's language), vendor work order (German), insurance note."""
from __future__ import annotations

LANGS = ("de", "en", "tr")

ETA_TXT = {
    "de": {"2h": "innerhalb von 2 Stunden", "24h": "innerhalb von 24 Stunden", "3d": "innerhalb von 3 Werktagen"},
    "en": {"2h": "within 2 hours", "24h": "within 24 hours", "3d": "within 3 working days"},
    "tr": {"2h": "2 saat içinde", "24h": "24 saat içinde", "3d": "3 iş günü içinde"},
}
SAFETY = {
    "gas": {"de": "Bitte verlassen Sie sofort die Wohnung, betätigen Sie keine Schalter und rufen Sie 112 an.",
            "en": "Please leave the flat now, do not use any switches, and call 112.",
            "tr": "Lütfen hemen daireden çıkın, hiçbir düğmeye dokunmayın ve 112'yi arayın."},
    "water_leak": {"de": "Wenn möglich, schließen Sie bitte das Wasserventil und schützen Sie Ihre Sachen.",
                   "en": "If you can, please close the water valve and move your belongings away.",
                   "tr": "Mümkünse lütfen su vanasını kapatın ve eşyalarınızı uzaklaştırın."},
    "roof": {"de": "Bitte stellen Sie einen Eimer unter und schützen Sie Ihre Sachen.",
             "en": "Please put a bucket under the leak and protect your belongings.",
             "tr": "Lütfen altına bir kova koyun ve eşyalarınızı koruyun."},
    "electrical": {"de": "Bitte schalten Sie die Sicherung für diesen Bereich aus und berühren Sie nichts.",
                   "en": "Please switch off the fuse for that area and do not touch anything.",
                   "tr": "Lütfen o bölümün sigortasını kapatın ve hiçbir şeye dokunmayın."},
}
COST = {
    "tenant_small_repair": {
        "de": "Hinweis: Laut Mietvertrag fällt diese Kleinreparatur unter die Kleinreparaturklausel.",
        "en": "Note: under your lease, this is a small repair covered by the small-repair clause (tenant cost).",
        "tr": "Not: Kira sözleşmenize göre bu küçük onarım kiracıya aittir (küçük onarım maddesi)."},
    "tenant": {
        "de": "Hinweis: Da der Schaden laut Ihrer Nachricht nicht durch normale Nutzung entstanden ist, "
              "werden die Kosten Ihnen in Rechnung gestellt. Ihre Haftpflichtversicherung kann helfen.",
        "en": "Note: as the damage was not caused by normal use, the cost will be charged to you. "
              "Your personal liability insurance may cover it.",
        "tr": "Not: Hasar normal kullanımdan kaynaklanmadığı için masraf size ait olacaktır. "
              "Sorumluluk sigortanız bunu karşılayabilir."},
}
OWN_APPLIANCE = {
    "de": "Das Gerät gehört nicht zur Mietsache. Bitte wenden Sie sich an den Hersteller oder einen Fachbetrieb.",
    "en": "This appliance isn't part of your tenancy, so please contact the manufacturer or a repair service.",
    "tr": "Bu cihaz kira kapsamında değil. Lütfen üreticiye veya bir servise başvurun."}
MOULD = {
    "de": "Wir schicken einen Gutachter, um die Ursache festzustellen. Bitte lüften Sie bis dahin regelmäßig.",
    "en": "We'll send a specialist to find the cause. Until then, please air the room regularly.",
    "tr": "Nedeni belirlemek için bir uzman göndereceğiz. O zamana kadar lütfen düzenli havalandırın."}


def tenant_reply(lang, category, urgency, vendor, bearer, eta) -> str:
    lang = lang if lang in LANGS else "en"
    parts = {"de": ["Danke für Ihre Nachricht, wir kümmern uns darum."],
             "en": ["Thanks for letting us know, we're on it."],
             "tr": ["Mesajınız için teşekkürler, ilgileniyoruz."]}[lang]
    if category in SAFETY and urgency == "emergency" or category == "gas":
        parts.append(SAFETY[category][lang])
    if bearer == "tenant" and category == "appliance" and not vendor:
        parts.append(OWN_APPLIANCE[lang])
        return " ".join(parts)
    if bearer == "manager_review":
        parts.append({"de": "Ihre Verwalterin meldet sich innerhalb von 2 Werktagen persönlich bei Ihnen.",
                      "en": "Your property manager will get back to you personally within 2 working days.",
                      "tr": "Mülk yöneticiniz 2 iş günü içinde sizinle bizzat iletişime geçecek."}[lang])
        return " ".join(parts)
    if bearer == "assessment_required":
        parts.append(MOULD[lang])
    if vendor:
        name = vendor["name"]
        parts.append({"de": f"{name} meldet sich {ETA_TXT['de'][eta]} bei Ihnen.",
                      "en": f"{name} will contact you {ETA_TXT['en'][eta]}.",
                      "tr": f"{name} {ETA_TXT['tr'][eta]} sizinle iletişime geçecek."}[lang])
    else:
        parts.append({"de": f"Ein Handwerker meldet sich {ETA_TXT['de'][eta]}.",
                      "en": f"A technician will contact you {ETA_TXT['en'][eta]}.",
                      "tr": f"Bir teknisyen {ETA_TXT['tr'][eta]} sizinle iletişime geçecek."}[lang])
    if bearer in COST:
        parts.append(COST[bearer][lang])
    return " ".join(parts)


BILLING = {"warranty": "Gewährleistung – bitte kostenfrei beheben (Einbau durch Sie)",
           "insurance": "Versicherungsschaden – Rechnung an Verwaltung, Schadennummer folgt",
           "tenant_small_repair": "Kleinreparatur – Rechnung an Mieter/in",
           "tenant": "Vom Mieter verursacht – Rechnung an Mieter/in",
           "landlord": "Instandhaltung – Rechnung an Verwaltung",
           "assessment_required": "Ursachenfeststellung – Rechnung an Verwaltung"}
URG = {"emergency": "NOTFALL – bitte innerhalb von 2 Stunden", "urgent": "dringend – innerhalb 24 Stunden",
       "normal": "normal – innerhalb 3 Werktagen"}


def work_order(mem, unit, tenant, message, asset, bearer, secondary, policy, urgency) -> str:
    addr = mem["nodes"][unit["building"]]["address"]
    lines = [f"Auftrag | {addr}, {unit['id']} ({unit.get('position')})",
             f"Mieter/in: {tenant['name']}",
             f"Meldung: \"{message}\"",
             f"Dringlichkeit: {URG[urgency]}"]
    if asset:
        lines.append(f"Anlage: {asset['id']} {asset['name']} (Einbau {asset['installed']})")
    lines.append(f"Abrechnung: {BILLING[bearer]}")
    if secondary == "insurance" and policy:
        lines.append(f"Folgeschaden: über {policy['type']} {policy['policy']} – bitte Fotos vorher/nachher")
    return "\n".join(lines)


def insurance_note(policy, unit_id, message) -> str:
    return (f"Schadenmeldung an {policy['insurer']} | Police {policy['policy']} ({policy['type']})\n"
            f"Einheit: {unit_id} | Meldung bis: {policy['report_by']} | Selbstbeteiligung: {policy['deductible']:.0f} EUR\n"
            f"Schilderung: \"{message}\"\nAnlagen: Fotos Mieter/in, Handwerkerbericht, Rechnung")
