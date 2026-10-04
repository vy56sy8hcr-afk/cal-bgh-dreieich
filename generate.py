import re
import hashlib
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

SOURCE_URL = "https://www.buergerhaeuser-dreieich.de/programm/veranstaltungen"
BASE_URL = "https://www.buergerhaeuser-dreieich.de"


def ics_escape(value):
    return (
        str(value or "")
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def parse_events():
    response = requests.get(
        SOURCE_URL,
        timeout=30,
        headers={"User-Agent": "Buergerhaeuser-Dreieich-Calendar"}
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
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

            text = container.get_text("\n", strip=True)

            if re.search(
                r"(Mo|Di|Mi|Do|Fr|Sa|So),\s*\d{2}\.\d{2}\.\d{4},\s*\d{1,2}:\d{2}\s*Uhr",
                text
            ):
                break

        if not container:
            continue

        text = container.get_text("\n", strip=True)

        match = re.search(
            r"(Mo|Di|Mi|Do|Fr|Sa|So),\s*(\d{2}\.\d{2}\.\d{4}),\s*(\d{1,2}:\d{2})\s*Uhr",
            text
        )

        if not match:
            continue

        try:
            start = datetime.strptime(
                f"{match.group(2)} {match.group(3)}",
                "%d.%m.%Y %H:%M"
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

        uid_source = f"{event_url}|{start.isoformat()}|{title}"
        uid = hashlib.sha256(uid_source.encode()).hexdigest()[:24]

        events.append({
            "uid": uid + "@buergerhaeuser-dreieich",
            "title": title,
            "start": start,
            "location": location,
            "organizer": organizer,
            "url": event_url,
        })

    unique = {event["uid"]: event for event in events}

    return sorted(
        unique.values(),
        key=lambda event: event["start"]
    )


def generate_ics(events):
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

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

        description = (
            f"Veranstaltung der Bürgerhäuser Dreieich. "
            f"Infos & Tickets: {event['url']}"
        )

        if event["organizer"]:
            description += f"\nVeranstalter: {event['organizer']}"

        lines.extend([
            "BEGIN:VEVENT",
            f"UID:{event['uid']}",
            f"DTSTAMP:{now}",
            f"DTSTART;TZID=Europe/Berlin:{start.strftime('%Y%m%dT%H%M%S')}",
            f"DTEND;TZID=Europe/Berlin:{end.strftime('%Y%m%dT%H%M%S')}",
            f"SUMMARY:{ics_escape(event['title'])}",
            f"LOCATION:{ics_escape(event['location'])}",
            f"DESCRIPTION:{ics_escape(description)}",
            f"URL:{event['url']}",
            "END:VEVENT",
        ])

    lines.append("END:VCALENDAR")

    return "\r\n".join(lines) + "\r\n"


if __name__ == "__main__":
    events = parse_events()

    if not events:
        raise RuntimeError("Keine Veranstaltungen gefunden.")

    with open(
        "buergerhaeuser-dreieich.ics",
        "w",
        encoding="utf-8",
        newline=""
    ) as file:
        file.write(generate_ics(events))

    print(f"{len(events)} Veranstaltungen exportiert.")
