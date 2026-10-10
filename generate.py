import os
import re
import hashlib
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

SOURCE_URL = "https://www.buergerhaeuser-dreieich.de/programm/veranstaltungen"
BASE_URL = "https://www.buergerhaeuser-dreieich.de"
FUENFZIG_DATEI = "fuenfzig_jahre.txt"

# Stichworte fuer 50 Jahre Dreieich, falls die Datei fuenfzig_jahre.txt fehlt
FUENFZIG_STANDARD = ["50 Jahre Dreieich", "Jubiläumsjahr", "Parkschwimmbad", "Elementaro"]

# Offensichtliche Tippfehler der Webseite, links falsch, rechts richtig
TIPPFEHLER = {
    "Parkschiwmmbad": "Parkschwimmbad",
    "Thater Karo Acht": "Theater Karo Acht",
}

# Ab hier endet der Text unter dem Titel
STOPP = ("Infos & Tickets", "Ort:", "Veranstalter:", "Ausverkauft", "Tickets")

DATUM = r"(Mo|Di|Mi|Do|Fr|Sa|So),\s*(\d{2}\.\d{2}\.\d{4}),\s*(\d{1,2}:\d{2})\s*Uhr"


def ics_escape(value):
    return (
        str(value or "")
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def falten(zeile):
    """Zeilen laenger als 75 Byte nach RFC 5545 umbrechen."""
    b = zeile.encode("utf-8")
    out = []
    while len(b) > 74:
        c = 74
        while (b[c] & 0xC0) == 0x80:
            c -= 1
        out.append(b[:c].decode("utf-8"))
        b = b" " + b[c:]
    out.append(b.decode("utf-8"))
    return "\r\n".join(out)


def korrigiere(text):
    for falsch, richtig in TIPPFEHLER.items():
        text = text.replace(falsch, richtig)
    return text


def lade_stichworte():
    if os.path.exists(FUENFZIG_DATEI):
        with open(FUENFZIG_DATEI, encoding="utf-8") as fh:
            worte = [z.strip() for z in fh if z.strip() and not z.startswith("#")]
        if worte:
            return [w.lower() for w in worte]
    return [w.lower() for w in FUENFZIG_STANDARD]


def parse_events(html=None):
    if html is None:
        response = requests.get(
            SOURCE_URL,
            timeout=30,
            headers={"User-Agent": "Buergerhaeuser-Dreieich-Calendar"},
        )
        response.raise_for_status()
        html = response.text

    soup = BeautifulSoup(html, "html.parser")
    events = []

    for heading in soup.find_all("h3"):
        link = heading.find("a", href=True)
        if not link:
            continue

        title = link.get_text(" ", strip=True)
        event_url = urljoin(BASE_URL, link["href"])

        container = heading
        for _ in range(6):
            container = container.parent
            if not container:
                break
            if re.search(DATUM, container.get_text("\n", strip=True)):
                break

        if not container:
            continue

        text = container.get_text("\n", strip=True)
        match = re.search(DATUM, text)
        if not match:
            continue

        try:
            start = datetime.strptime(
                f"{match.group(2)} {match.group(3)}", "%d.%m.%Y %H:%M"
            )
        except ValueError:
            continue

        location = ""
        location_match = re.search(r"Ort:\s*(.+)", text)
        if location_match:
            location = location_match.group(1).strip()

        organizer = ""
        organizer_match = re.search(r"Veranstalter:\s*(.+)", text)
        if organizer_match:
            organizer = organizer_match.group(1).strip()

        # Untertitel und Beschreibung: Zeilen zwischen Titel und "Infos & Tickets"
        zeilen = text.split("\n")
        extra = []
        if title in zeilen:
            for zeile in zeilen[zeilen.index(title) + 1:]:
                if zeile.startswith(STOPP):
                    break
                extra.append(zeile)

        starke_stuecke = any(
            "starkestuecke" in (img.get("src") or "").lower()
            for img in container.find_all("img")
        )

        uid_source = f"{event_url}|{start.isoformat()}|{title}"
        uid = hashlib.sha256(uid_source.encode()).hexdigest()[:24]

        events.append({
            "uid": uid + "@buergerhaeuser-dreieich",
            "title": title,
            "start": start,
            "location": location,
            "organizer": organizer,
            "url": event_url,
            "extra": extra,
            "starke_stuecke": starke_stuecke,
        })

    unique = {event["uid"]: event for event in events}
    return sorted(unique.values(), key=lambda event: event["start"])


def baue_titel(event, stichworte):
    titel = korrigiere(event["title"])
    suchtext = korrigiere(" ".join([event["title"]] + event["extra"])).lower()
    if any(w in suchtext for w in stichworte):
        return f"▼⭐️5o {titel}"
    if event["starke_stuecke"]:
        return f"▼ 🎭Starke Stücke: {titel}"
    return titel


def baue_notiz(event):
    zeilen = [korrigiere(z) for z in event["extra"]]
    ort = event["location"]
    uhr = f"{event['start']:%H:%M} Uhr"
    zeilen.append(f"{uhr}, {ort}" if ort else uhr)
    if event["organizer"] and not event["organizer"].startswith("Bürgerhäuser"):
        zeilen.append(f"Veranstalter: {event['organizer']}")
    return "\n".join(zeilen)


def generate_ics(events):
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    stichworte = lade_stichworte()

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Buergerhaeuser Dreieich//DE",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Bürgerhäuser Dreieich",
        "X-WR-TIMEZONE:Europe/Berlin",
    ]

    for event in events:
        start = event["start"]
        end = start + timedelta(hours=2)

        lines.extend([
            "BEGIN:VEVENT",
            f"UID:{event['uid']}",
            f"DTSTAMP:{now}",
            f"DTSTART;TZID=Europe/Berlin:{start.strftime('%Y%m%dT%H%M%S')}",
            f"DTEND;TZID=Europe/Berlin:{end.strftime('%Y%m%dT%H%M%S')}",
            falten(f"SUMMARY:{ics_escape(baue_titel(event, stichworte))}"),
            falten(f"LOCATION:{ics_escape(event['location'])}"),
            falten(f"DESCRIPTION:{ics_escape(baue_notiz(event))}"),
            falten(f"URL:{event['url']}"),
            "END:VEVENT",
        ])

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


if __name__ == "__main__":
    events = parse_events()

    if not events:
        raise RuntimeError("Keine Veranstaltungen gefunden.")

    with open("buergerhaeuser-dreieich.ics", "w", encoding="utf-8", newline="") as file:
        file.write(generate_ics(events))

    print(f"{len(events)} Veranstaltungen exportiert.")
