#!/usr/bin/env python3
"""
Loggt sich bei Moodle (study.hamburgmediaschool.com) ein, laedt die
persoenliche ICS-Stundenplan-Datei herunter, filtert unerwuenschte
Termine raus und speichert das Ergebnis als schedule.ics.
"""
import os
import re
import sys

import requests

BASE = "https://study.hamburgmediaschool.com"
LOGIN_URL = f"{BASE}/login/index.php"
OUTPUT_FILE = "schedule.ics"

# Termine, deren SUMMARY mit einem dieser Texte beginnt, werden
# komplett aus dem Kalender entfernt (z.B. der woechentliche
# "frei fuer Studijobs"-Platzhalter).
FILTER_SUMMARY_PREFIXES = [
    "Studijobs",
]


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


def filter_events(ics_text: str, prefixes: list) -> str:
    """Entfernt komplette VEVENT-Bloecke, deren SUMMARY mit einem der
    angegebenen Prefixe beginnt (z.B. "Studijobs")."""
    if not prefixes:
        return ics_text

    lines = ics_text.splitlines(keepends=True)
    output = []
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]
        if line.lstrip().startswith("BEGIN:VEVENT"):
            block = [line]
            i += 1
            while i < n and not lines[i].lstrip().startswith("END:VEVENT"):
                block.append(lines[i])
                i += 1
            if i < n:
                block.append(lines[i])  # END:VEVENT-Zeile mit anhaengen
                i += 1

            # ICS-Zeilenfaltung rueckgaengig machen, um SUMMARY zuverlaessig
            # zu erkennen (Folgezeilen beginnen laut RFC5545 mit Leerzeichen/Tab).
            unfolded = "".join(block)
            unfolded = re.sub(r'\r?\n[ \t]', '', unfolded)

            summary_match = re.search(r'SUMMARY:(.*)', unfolded)
            summary = summary_match.group(1).strip() if summary_match else ""

            if any(summary.startswith(prefix) for prefix in prefixes):
                continue  # Block ueberspringen = Termin wird entfernt

            output.extend(block)
        else:
            output.append(line)
            i += 1

    return "".join(output)


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
    filtered = filter_events(text, FILTER_SUMMARY_PREFIXES)

    with open(OUTPUT_FILE, "w", encoding="utf-8", newline="") as f:
        f.write(filtered)

    print(f"OK: {OUTPUT_FILE} aktualisiert ({len(filtered)} Zeichen, gefiltert nach {FILTER_SUMMARY_PREFIXES}).")


if __name__ == "__main__":
    main()
