"""Tenant-facing winter texts (DE / EN / TR). Short, plain, one action per sentence."""
from __future__ import annotations

LANGS = ("de", "en", "tr")


def pick(lang: str) -> str:
    return lang if lang in LANGS else "en"


WINTER_TIPS = {
    "de": ("Kältewelle ab {first_frost}: Bitte lassen Sie die Heizung auch bei Abwesenheit auf mindestens Stufe 2 "
           "(ca. 16 °C), lüften Sie 3x täglich 5 Minuten stoß (nicht kippen) und melden Sie Heizungsprobleme sofort "
           "hier. So vermeiden wir eingefrorene Leitungen und Schimmel."),
    "en": ("Cold snap from {first_frost}: please keep the heating on at least level 2 (about 16 °C) even when you are "
           "away, air rooms fully 3 times a day for 5 minutes (don't leave windows tilted), and report any heating "
           "problem here right away. This prevents frozen pipes and mould."),
    "tr": ("{first_frost} itibarıyla soğuk hava: Evde olmasanız da kaloriferi en az 2. kademede (yaklaşık 16 °C) "
           "tutun, günde 3 kez 5 dakika pencereleri tam açarak havalandırın (vasistas değil) ve ısınma sorunlarını "
           "hemen buradan bildirin. Böylece donmuş borular ve küf oluşmaz."),
}

HOLDING = {
    "de": "Danke, ist angekommen. Wir prüfen gerade, ob das ganze Haus betroffen ist, und melden uns in wenigen Minuten.",
    "en": "Thanks, received. We're checking whether the whole building is affected and will update you within minutes.",
    "tr": "Teşekkürler, mesajınız alındı. Tüm binanın etkilenip etkilenmediğini kontrol ediyoruz, birkaç dakika içinde bilgi vereceğiz.",
}

INCIDENT_OPEN = {
    "de": ("Die Heizung im ganzen Haus ist ausgefallen. {vendor} ist bereits beauftragt (Notdienst), Ankunft ca. {eta}. "
           "Bitte halten Sie Fenster und Türen geschlossen. Sie müssen nichts weiter melden, wir halten Sie hier auf dem Laufenden."),
    "en": ("The heating is down for the whole building. {vendor} is already on the way (emergency service), arrival around "
           "{eta}. Please keep windows and doors closed. No need to report it again, we'll keep you updated here."),
    "tr": ("Binanın tamamında ısıtma arızası var. {vendor} acil servis olarak görevlendirildi, tahmini varış {eta}. "
           "Lütfen pencere ve kapıları kapalı tutun. Tekrar bildirmenize gerek yok, sizi buradan bilgilendireceğiz."),
}

INCIDENT_KNOWN = {
    "de": "Danke, der Ausfall ist bekannt. {status} Wir melden uns, sobald die Heizung wieder läuft.",
    "en": "Thanks, we know about the outage. {status} We'll message you as soon as the heating is back.",
    "tr": "Teşekkürler, arızadan haberdarız. {status} Isıtma tekrar çalıştığında size haber vereceğiz.",
}

STATUS = {
    "dispatched": {"de": "Der Techniker ist unterwegs, Ankunft ca. {eta}.",
                   "en": "The technician is on the way, arriving around {eta}.",
                   "tr": "Teknisyen yolda, tahmini varış {eta}."},
    "on_site": {"de": "Der Techniker ist vor Ort, die Heizung läuft voraussichtlich ab {eta} wieder.",
                "en": "The technician is on site; heating should be back around {eta}.",
                "tr": "Teknisyen binada; ısıtmanın yaklaşık {eta} itibarıyla tekrar çalışması bekleniyor."},
}

INCIDENT_ONSITE = {
    "de": "Update: Der Techniker ist vor Ort ({diag}). Die Heizung läuft voraussichtlich ab {eta} wieder.",
    "en": "Update: the technician is on site ({diag}). Heating should be back around {eta}.",
    "tr": "Güncelleme: teknisyen binada ({diag}). Isıtmanın yaklaşık {eta} itibarıyla tekrar çalışması bekleniyor.",
}

INCIDENT_RESOLVED = {
    "de": ("Die Heizung läuft wieder. Die Heizkörper brauchen 1-2 Stunden, bis sie warm sind. Bleibt einer kalt oder "
           "gluckert, antworten Sie einfach hier."),
    "en": ("The heating is back on. Radiators need 1-2 hours to warm up. If one stays cold or gurgles, just reply here."),
    "tr": ("Isıtma tekrar çalışıyor. Kaloriferlerin ısınması 1-2 saat sürebilir. Biri soğuk kalırsa veya guruldarsa buradan yazın."),
}

HEATER_OFFER = {
    "de": "Wir bringen Ihnen bis zur Reparatur ein Heizgerät vorbei. Ist jemand zu Hause?",
    "en": "We'll bring you a temporary heater until the repair is done. Is someone at home?",
    "tr": "Onarım bitene kadar size geçici bir ısıtıcı getireceğiz. Evde biri var mı?",
}

SELF_HELP = {
    "de": ("Das klingt nach Luft im Heizkörper. So geht's in 2 Minuten: 1) Thermostat ganz aufdrehen. 2) Mit einem "
           "Entlüftungsschlüssel (Baumarkt, ca. 2 €) das Ventil oben an der Seite eine halbe Drehung öffnen, Tuch drunter. "
           "3) Schließen, sobald Wasser statt Luft kommt. Wird er in 1 Stunde nicht warm, schreiben Sie 'immer noch kalt' "
           "und wir schicken jemanden."),
    "en": ("That sounds like air in the radiator. A 2-minute fix: 1) Turn the thermostat fully up. 2) With a radiator "
           "key (hardware store, about €2), open the small valve at the top side half a turn, cloth underneath. "
           "3) Close it once water comes out instead of air. If it isn't warm within an hour, reply 'still cold' and "
           "we'll send someone."),
    "tr": ("Kaloriferde hava kalmış gibi görünüyor. 2 dakikada çözüm: 1) Termostatı sonuna kadar açın. 2) Hava alma "
           "anahtarıyla (hırdavatçıda yaklaşık 2 €) üst yandaki küçük vanayı yarım tur açın, altına bez koyun. "
           "3) Hava yerine su gelince kapatın. 1 saat içinde ısınmazsa 'hala soğuk' yazın, birini gönderelim."),
}

SELF_HELP_DONE = {
    "de": "Super, danke für die Rückmeldung! Wir schließen die Meldung.",
    "en": "Great, thanks for letting us know! We've closed the request.",
    "tr": "Harika, bilgi verdiğiniz için teşekkürler! Talebi kapattık.",
}

ICE_REPLY = {
    "de": "Danke für den Hinweis, das ist wichtig. Der Winterdienst ist beauftragt und streut in Kürze. Bitte bis dahin vorsichtig.",
    "en": "Thanks, that's important. The winter service has been called and will grit shortly. Please take care until then.",
    "tr": "Bildiriminiz için teşekkürler. Kış hizmeti çağrıldı, kısa süre içinde kum/tuz serpilecek. O zamana kadar lütfen dikkatli olun.",
}

SELF_HELP_CHECK = {
    "de": "Kurze Nachfrage: Ist der Heizkörper jetzt warm? Antworten Sie mit 'ja' oder 'immer noch kalt'.",
    "en": "Quick check: is the radiator warm now? Reply 'yes' or 'still cold'.",
    "tr": "Kısa bir kontrol: Kalorifer şimdi ısındı mı? 'evet' veya 'hala soğuk' diye yanıtlayın.",
}
