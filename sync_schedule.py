#!/usr/bin/env python3
"""
Loggt sich bei Moodle (study.hamburgmediaschool.com) ein, laedt die
persoenliche ICS-Stundenplan-Datei herunter und speichert sie als
schedule.ics im Projektordner.
"""
import os
import re
import sys

import requests

BASE = "https://study.hamburgmediaschool.com"
LOGIN_URL = f"{BASE}/login/index.php"
OUTPUT_FILE = "schedule.ics"


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

    with open(OUTPUT_FILE, "wb") as f:
        f.write(content)

    print(f"OK: {OUTPUT_FILE} aktualisiert ({len(content)} Bytes).")


if __name__ == "__main__":
    main()
