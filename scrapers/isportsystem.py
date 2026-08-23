"""
Scraper pro studia bezici na rezervacnim systemu iSportSystem
(napr. rehabfit.isportsystem.cz, pilates-place.isportsystem.cz, ...).

DULEZITA POZNAMKA K TOMUTO SOUBORU:
Byl napsan bez moznosti zivého otestovani proti realnym strankam
(vyvojove prostredi nema pristup k techto webum). Presna struktura
odpovedi ajax endpointu tedy neni jista - kod je proto navrzen
defenzivne (zkousi vic zpusobu parsovani, nikdy nespadne na jednom
studiu/dni, a loguje syrova data pro pripad, ze je potreba parsovani
dolauffovat podle skutecneho vystupu z prvniho behu v GitHub Actions).

Zjisteny vzor ajax volani (nalezeno pres vyhledavani):
  https://<subdomena>.isportsystem.cz/ajax/ajax.schema.php
    ?day=D&month=M&year=Y&id_sport=infoTab&id_infotab=<N>&event=pageLoad
"""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.robotparser
from datetime import date, timedelta
from typing import Any

import requests
from bs4 import BeautifulSoup

log = logging.getLogger("isportsystem")

USER_AGENT = "BrnoFitAgregator/1.0 (+https://github.com/lokajovaveru-cpu/fit; osobni neziskovy agregator verejnych rozvrhu lekci)"
REQUEST_TIMEOUT = 15
REQUEST_DELAY_SECONDS = 0.8
DAYS_AHEAD = 7

CLASS_TYPE_KEYWORDS = [
    ("jumping", ["jumping", "trampol"]),
    ("jóga", ["jóga", "yoga", "jog a", "ashtanga", "vinyasa", "hatha", "kundalini"]),
    ("pilates", ["pilates", "reformer", "barre"]),
    ("hiit / tabata", ["hiit", "tabata", "bootcamp", "fatburn"]),
    ("funkční trénink", ["funkč", "workout", "fitbox", "kruhov", "tělocvik", "rehab"]),
    ("tanec / zumba", ["zumba", "tanec", "dance"]),
    ("spinning", ["spinning", "cyklo", "kolo"]),
]

_session_cache: dict[str, requests.Session] = {}


def _get_session() -> requests.Session:
    if "s" not in _session_cache:
        s = requests.Session()
        s.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "cs,en;q=0.8"})
        _session_cache["s"] = s
    return _session_cache["s"]


def _robots_allowed(base_url: str, path: str) -> bool:
    """Best-effort robots.txt check. Fails open (True) if robots.txt is
    unreachable or unparsable, since these are public schedule pages meant
    for browsers, not admin/private endpoints."""
    try:
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(base_url.rstrip("/") + "/robots.txt")
        rp.read()
        return rp.can_fetch(USER_AGENT, path)
    except Exception as exc:  # noqa: BLE001 - politeness check must never break scraping
        log.debug("robots.txt check failed for %s (%s), assuming allowed", base_url, exc)
        return True


def _guess_class_type(class_name: str) -> str:
    lowered = class_name.lower()
    for tag, keywords in CLASS_TYPE_KEYWORDS:
        if any(kw in lowered for kw in keywords):
            return tag
    return "ostatní"


def _discover_infotab_ids(html: str) -> list[str]:
    """Look for id_infotab references embedded in the studio's homepage
    (used by the JS widget to call the ajax endpoint per category/room)."""
    ids = set(re.findall(r"id_infotab['\"=:\s]+(\d+)", html))
    return sorted(ids)


def _fetch_day_raw(session: requests.Session, base_url: str, day: date, id_infotab: str | None) -> tuple[str, str]:
    params = {
        "day": day.day,
        "month": day.month,
        "year": day.year,
        "id_sport": "infoTab",
        "event": "pageLoad",
    }
    if id_infotab:
        params["id_infotab"] = id_infotab

    url = base_url.rstrip("/") + "/ajax/ajax.schema.php"
    resp = session.get(url, params=params, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    content_type = resp.headers.get("Content-Type", "")
    return resp.text, content_type


def _parse_json_entries(raw: str) -> list[dict[str, Any]]:
    data = json.loads(raw)
    entries: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            keys = {k.lower() for k in node.keys()}
            if keys & {"nazev", "name", "cas", "time", "predmet", "kurz"}:
                entries.append(node)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    return entries


def _parse_html_entries(raw: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(raw, "html.parser")
    entries: list[dict[str, Any]] = []

    candidates = soup.select(
        "[class*='lekce'], [class*='event'], [class*='item'], [class*='schema'], tr"
    )
    for el in candidates:
        text = el.get_text(" ", strip=True)
        if not text or len(text) < 3:
            continue
        time_match = re.search(r"\b(\d{1,2}[:.]\d{2})\b", text)
        if not time_match:
            continue
        capacity_match = re.search(r"(\d+)\s*/\s*(\d+)", text)
        entries.append(
            {
                "_raw_text": text,
                "_time_match": time_match.group(1).replace(".", ":"),
                "_capacity_match": capacity_match.groups() if capacity_match else None,
            }
        )
    return entries


def _normalize_entry(entry: dict[str, Any], studio: dict[str, str], day: date) -> dict[str, Any]:
    if "_raw_text" in entry:
        # Fallback HTML-derived entry - we only confidently know the time and raw text.
        class_name = entry["_raw_text"][:80]
        start_time = entry.get("_time_match")
        cap = entry.get("_capacity_match")
        capacity_free = int(cap[0]) if cap else None
        capacity_total = int(cap[1]) if cap else None
        instructor = None
    else:
        class_name = str(entry.get("nazev") or entry.get("name") or entry.get("predmet") or entry.get("kurz") or "Lekce")
        start_time = str(entry.get("cas") or entry.get("time") or entry.get("cas_od") or "") or None
        instructor = entry.get("lektor") or entry.get("trener") or entry.get("instructor")
        capacity_free = entry.get("volno") or entry.get("volna_mista") or entry.get("free")
        capacity_total = entry.get("kapacita") or entry.get("capacity")
        try:
            capacity_free = int(capacity_free) if capacity_free is not None else None
            capacity_total = int(capacity_total) if capacity_total is not None else None
        except (TypeError, ValueError):
            capacity_free = capacity_total = None

    return {
        "studio_id": studio["id"],
        "studio_name": studio["name"],
        "city": studio["city"],
        "address": studio.get("address"),
        "class_name": class_name,
        "class_type": _guess_class_type(class_name),
        "date": day.isoformat(),
        "start_time": start_time,
        "end_time": None,
        "instructor": instructor,
        "capacity_total": capacity_total,
        "capacity_free": capacity_free,
        "booking_url": studio.get("website"),
        "source": "isportsystem",
    }


def scrape(studio: dict[str, str]) -> list[dict[str, Any]]:
    """Scrape upcoming lessons for one iSportSystem-based studio.
    Never raises - logs and returns whatever could be collected, so one
    broken studio doesn't take down the whole aggregation run."""
    subdomain = studio["subdomain"]
    base_url = f"https://{subdomain}.isportsystem.cz"
    session = _get_session()
    lessons: list[dict[str, Any]] = []

    if not _robots_allowed(base_url, "/ajax/ajax.schema.php"):
        log.warning("robots.txt zakazuje /ajax/ pro %s, preskakuji", subdomain)
        return lessons

    id_infotabs: list[str | None] = [None]
    try:
        home = session.get(base_url, timeout=REQUEST_TIMEOUT)
        home.raise_for_status()
        discovered = _discover_infotab_ids(home.text)
        if discovered:
            log.info("%s: nalezeny id_infotab kandidati %s", subdomain, discovered)
            id_infotabs = discovered
    except requests.RequestException as exc:
        log.warning("%s: nepodarilo se nacist hlavni stranku (%s), zkousim default ajax volani", subdomain, exc)

    time.sleep(REQUEST_DELAY_SECONDS)

    today = date.today()
    logged_sample = False
    for offset in range(DAYS_AHEAD):
        day = today + timedelta(days=offset)
        for id_infotab in id_infotabs:
            try:
                raw, content_type = _fetch_day_raw(session, base_url, day, id_infotab)
            except requests.RequestException as exc:
                log.warning("%s %s (id_infotab=%s): pozadavek selhal (%s)", subdomain, day, id_infotab, exc)
                continue

            if not logged_sample:
                log.info("%s: ukazka syrove odpovedi (%s): %s", subdomain, content_type, raw[:800])
                logged_sample = True

            entries: list[dict[str, Any]] = []
            try:
                entries = _parse_json_entries(raw)
            except (json.JSONDecodeError, TypeError):
                entries = _parse_html_entries(raw)

            if not entries:
                log.debug("%s %s (id_infotab=%s): zadne rozpoznatelne lekce v odpovedi", subdomain, day, id_infotab)

            for entry in entries:
                lessons.append(_normalize_entry(entry, studio, day))

            time.sleep(REQUEST_DELAY_SECONDS)

    log.info("%s: celkem nalezeno %d lekci", subdomain, len(lessons))
    return lessons
