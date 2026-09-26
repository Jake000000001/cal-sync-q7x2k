#!/usr/bin/env python3
"""
Loggt sich bei Moodle (study.hamburgmediaschool.com) ein, laedt die
persoenliche ICS-Stundenplan-Datei herunter, raeumt sie auf
(Titel, Ort, Erinnerungen, Kalendername) und filtert unerwuenschte
Termine raus. Speichert das Ergebnis als schedule.ics.
"""
import os
import re
import sys

import requests

BASE = "https://study.hamburgmediaschool.com"
LOGIN_URL = f"{BASE}/login/index.php"
OUTPUT_FILE = "schedule.ics"

# Termine, deren Titel (aus dem "Veranstaltung"-Feld) mit einem dieser
# Texte beginnt, werden komplett aus dem Kalender entfernt (z.B. der
# woechentliche "frei fuer Studijobs"-Platzhalter).
FILTER_SUMMARY_PREFIXES = [
    "Studijobs",
]

# Wie viele Minuten vor jedem Termin eine Erinnerung ausgeloest wird.
ALARM_MINUTES_BEFORE = 15

# Reine, geocodierbare Adresse fuers LOCATION-Feld (ohne Raumnummer davor,
# sonst finden Karten-Apps den Ort nicht mehr).
HMS_ADDRESS = "Hamburg Media School, Finkenau 35, 22081 Hamburg"

# "Art"-Werte, die NICHT als Praefix vor den Titel gesetzt werden (weil sie
# der Normalfall sind und keine zusaetzliche Kennzeichnung brauchen).
ART_PREFIX_SKIP = {"Vorlesung", ""}

# Name, unter dem der abonnierte Kalender auf dem iPhone erscheint.
CALENDAR_NAME = "HMS Stundenplan"


def get_login_token(session: requests.Session) -> str:
    resp = session.get(LOGIN_URL, timeout=30)
    resp.raise_for_status()
    match = re.search(r'name="logintoken"\s+value="([^"]+)"', resp.text)
    if not match:
        print("Konnte logintoken nicht finden - Moodle-Loginseite hat sich evtl. geaendert.", file=sys.stderr)
        sys.exit(1)
    return match.group(1)


def login(session: requests.Session, username: str, password: str) -> None:
    token = get_login_token(session)
    payload = {
        "anchor": "",
        "logintoken": token,
        "username": username,
        "password": password,
    }
    resp = session.post(LOGIN_URL, data=payload, timeout=30, allow_redirects=True)
    resp.raise_for_status()
    if "loginerrors" in resp.text or ("logintoken" in resp.text and "Ungueltige Anmeldung" in resp.text):
        print("Login fehlgeschlagen - bitte MOODLE_USER / MOODLE_PASS pruefen.", file=sys.stderr)
        sys.exit(1)


def download_ics(session: requests.Session, ics_url: str) -> bytes:
    resp = session.get(ics_url, timeout=30)
    resp.raise_for_status()
    content = resp.content
    if not content.strip().startswith(b"BEGIN:VCALENDAR"):
        print(
            "Antwort sieht nicht wie eine gueltige ICS-Datei aus "
            "(vermutlich war der Login nicht erfolgreich oder die URL hat sich geaendert).",
            file=sys.stderr,
        )
        sys.exit(1)
    return content


def escape_ics_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")


def process_event_block(block_text: str, filter_prefixes, alarm_minutes: int, address: str):
    """Verarbeitet einen einzelnen BEGIN:VEVENT...END:VEVENT-Block.
    Gibt den (moeglicherweise veraenderten) Block als String zurueck,
    oder None, wenn der Termin komplett entfernt werden soll."""
    # ICS-Zeilenfaltung aufloesen (RFC5545: Folgezeile beginnt mit Space/Tab).
    unfolded = re.sub(r"\r\n[ \t]", "", block_text)
    lines = unfolded.split("\r\n")

    summary_line = next((l for l in lines if l.startswith("SUMMARY:")), None)
    description_line = next((l for l in lines if l.startswith("DESCRIPTION:")), None)

    raw_summary = summary_line.split(":", 1)[1].strip() if summary_line else ""

    # Das DESCRIPTION-Feld enthaelt saubere, gelabelte Werte
    # ("Veranstaltung: ...\nDozent: ...\nRaum: ...\nArt: ...\nAnmerkung: ..."),
    # die wir fuers Aufraeumen von Titel und Ort verwenden.
    desc_fields = {}
    if description_line:
        desc_val = description_line.split(":", 1)[1]
        desc_text = desc_val.replace("\\n", "\n").replace("\\,", ",")
        for dl in desc_text.split("\n"):
            if ":" in dl:
                k, v = dl.split(":", 1)
                desc_fields[k.strip()] = v.strip()

    clean_title = desc_fields.get("Veranstaltung", "").strip()
    room = desc_fields.get("Raum", "").strip()
    art = desc_fields.get("Art", "").strip()
    note = desc_fields.get("Anmerkung", "").strip()

    check_value = clean_title or raw_summary
    if any(check_value.startswith(p) for p in filter_prefixes):
        return None  # Termin komplett entfernen

    has_room = bool(room) and room not in ("-", "extern")
    has_note = bool(note) and note != "-"

    # Titel: Art als Praefix (z.B. "Gastgespraech: ..."), ausser bei
    # "Vorlesung" (Normalfall). Raum als Suffix in Klammern, Anmerkung
    # (z.B. "KickOffs") ganz am Ende.
    display_title = clean_title
    if art and art not in ART_PREFIX_SKIP:
        display_title = f"{art}: {display_title}"
    if has_room:
        display_title = f"{display_title} (Raum {room})"
    if has_note:
        display_title = f"{display_title} – {note}"

    new_lines = []
    for line in lines:
        if line == "":
            continue
        if line.startswith("SUMMARY:") and clean_title:
            new_lines.append("SUMMARY:" + escape_ics_text(display_title))
            continue
        if line.startswith("LOCATION:") and has_room:
            # Nur die reine Adresse, kein Raum-Praefix - sonst koennen
            # Karten-Apps den Ort nicht mehr geocodieren.
            new_lines.append("LOCATION:" + escape_ics_text(address))
            continue
        if line.startswith("END:VEVENT") and alarm_minutes:
            new_lines.append("BEGIN:VALARM")
            new_lines.append("ACTION:DISPLAY")
            new_lines.append("DESCRIPTION:Erinnerung")
            new_lines.append(f"TRIGGER:-PT{alarm_minutes}M")
            new_lines.append("END:VALARM")
            new_lines.append(line)
            continue
        new_lines.append(line)

    return "\r\n".join(new_lines) + "\r\n"


def transform_ics(ics_text: str, filter_prefixes, alarm_minutes: int, address: str, calendar_name: str) -> str:
    pattern = re.compile(r"BEGIN:VEVENT\r\n.*?END:VEVENT\r\n", re.S)

    def repl(m):
        result = process_event_block(m.group(0), filter_prefixes, alarm_minutes, address)
        return result if result is not None else ""

    out = pattern.sub(repl, ics_text)

    # Kalendername/-zeitzone direkt nach BEGIN:VCALENDAR einfuegen, damit
    # der abonnierte Kalender auf dem iPhone einen sprechenden Namen hat.
    if "X-WR-CALNAME" not in out:
        header = (
            f"X-WR-CALNAME:{escape_ics_text(calendar_name)}\r\n"
            "X-WR-TIMEZONE:Europe/Berlin\r\n"
        )
        out = out.replace("BEGIN:VCALENDAR\r\n", "BEGIN:VCALENDAR\r\n" + header, 1)

    return out


def main() -> None:
    username = os.environ.get("MOODLE_USER")
    password = os.environ.get("MOODLE_PASS")
    ics_url = os.environ.get("ICS_URL")

    if not all([username, password, ics_url]):
        print("Bitte MOODLE_USER, MOODLE_PASS und ICS_URL als Umgebungsvariablen setzen.", file=sys.stderr)
        sys.exit(1)

    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (moodle-ics-sync)"})

    login(session, username, password)
    content = download_ics(session, ics_url)

    text = content.decode("utf-8", errors="replace")
    transformed = transform_ics(text, FILTER_SUMMARY_PREFIXES, ALARM_MINUTES_BEFORE, HMS_ADDRESS, CALENDAR_NAME)

    with open(OUTPUT_FILE, "w", encoding="utf-8", newline="") as f:
        f.write(transformed)

    print(
        f"OK: {OUTPUT_FILE} aktualisiert ({len(transformed)} Zeichen, "
        f"gefiltert nach {FILTER_SUMMARY_PREFIXES}, Alarm {ALARM_MINUTES_BEFORE} Min. vorher)."
    )


if __name__ == "__main__":
    main()
