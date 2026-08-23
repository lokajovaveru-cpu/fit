"""
Scraper pro studia bezici na rezervacnim systemu iSportSystem
(napr. rehabfit.isportsystem.cz, pilates-place.isportsystem.cz, ...).

Overeno primo ze zdrojoveho JS bundlu dane stranky (funkce loadTab() v
cache/js/<hash>.js), ktery sestavuje skutecne volani:

  $.ajax({type: "post",
      url: "ajax/ajax.schema.php",
      data: {
          id_sport: id_sport,          // z hidden inputu #id_sport (viz
                                        // <a tab_type="activity" id_sport="5">ROZVRH</a>)
          day: $("#day").val(),
          month: $("#month").val(),
          year: $("#year").val(),
          event: event,                // 'init' pri prvnim nacteni stranky
          timetableWidth: ...,
          arLabelId: ...,
          noticeCheckRequested: ...,
          noticeCheck: ...,
          idNoticeCheck: ...,
      },
      ...
  });

Dve veci, ktere predchozi verze tohoto souboru mely spatne (a proto vzdy
dostavaly status=200 s prazdnym telem, bez ohledu na parametry):
1. Je to POST, ne GET - PHP skript cte $_POST, takze cokoliv v query
   stringu je pro nej neviditelne.
2. 'id_sport' se ma brat z tab_type="activity" tabu (ROZVRH), ne z
   tab_type="infotab" tabu (ktery je pro neco uplne jineho, napr.
   "Pravidla rezervaci").
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
        # \b word-boundary matching, not bare substring - "kolo" must not match
        # inside e.g. "Sokolovna" (a room name), only as its own word/prefix.
        if any(re.search(r"\b" + re.escape(kw), lowered) for kw in keywords):
            return tag
    return "ostatní"


def _discover_activity_sport_ids(html: str) -> list[str]:
    """Find id_sport values for the real schedule ('ROZVRH') tabs, i.e.
    <a ... tab_type="activity" ... id_sport="N" ...>. A studio can have more
    than one such tab (e.g. separate rooms/branches), each needing its own
    ajax.schema.php call. Deliberately does NOT match tab_type="infotab"
    tabs (informational content like reservation rules) - those share the
    same numeric-id-in-an-attribute shape but are a different feature."""
    ids: list[str] = []
    for tag_match in re.finditer(r"<a\b[^>]*>", html):
        tag = tag_match.group(0)
        if 'tab_type="activity"' not in tag:
            continue
        m = re.search(r'id_sport="(\d+)"', tag)
        if m and m.group(1) not in ids:
            ids.append(m.group(1))
    return ids


def _fetch_day_raw(session: requests.Session, base_url: str, day: date, id_sport: str) -> requests.Response:
    # Mirrors the exact jQuery $.ajax(...) call in the site's own JS (loadTab()):
    # a POST with this form data - not a GET with a query string.
    form_data = {
        "id_sport": id_sport,
        "day": day.day,
        "month": day.month,
        "year": day.year,
        "event": "init",
        "timetableWidth": 900,
        "arLabelId": "",
        "noticeCheckRequested": 0,
        "noticeCheck": 0,
        "idNoticeCheck": "",
    }

    url = base_url.rstrip("/") + "/ajax/ajax.schema.php"
    headers = {
        "X-Requested-With": "XMLHttpRequest",
        "Referer": base_url.rstrip("/") + "/",
    }
    resp = session.post(url, data=form_data, headers=headers, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp


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


_LESSON_TEXT_RE = re.compile(
    r"(?P<start>\d{1,2}:\d{2})[–-](?P<end>\d{1,2}:\d{2})\s+"
    r"(?P<middle>.+?)\s+"
    r"(?P<status>Uplynulo|volno:\s*\d+|Obsazeno:\s*\d+\s*/\s*\d+)"
)
_FREE_RE = re.compile(r"volno:\s*(\d+)")
_OCCUPIED_RE = re.compile(r"Obsazeno:\s*(\d+)\s*/\s*(\d+)")


def _parse_html_entries(raw: str) -> list[dict[str, Any]]:
    """Parse the real iSportSystem schedule fragment (confirmed against
    live responses - there's no public documentation for this format).
    Flattened to text, each lesson is a
      'HH:MM-HH:MM <class name> [room] <instructor> <status>'
    run, where <status> is 'Uplynulo' (slot already passed today - not
    bookable, skipped), 'volno: N' (N free spots), or 'Obsazeno: X/Y' (X
    of Y taken). Matching once against the whole flattened text with a
    single global regex (rather than a CSS selector guess) avoids
    counting the same lesson more than once from overlapping nested
    elements, which is what the previous version of this function did.

    The trailing 2 words of the middle blob are taken as the instructor's
    name - every observed sample was exactly a 2-word Czech name/initial
    (e.g. "Romana Sedláčková", "Eva N."). This is a heuristic and can be
    wrong if a class name itself happens to end in two capitalized words."""
    soup = BeautifulSoup(raw, "html.parser")
    text = soup.get_text(" ", strip=True)

    entries: list[dict[str, Any]] = []
    for m in _LESSON_TEXT_RE.finditer(text):
        status = m.group("status")
        if status == "Uplynulo":
            continue

        middle_words = m.group("middle").split()
        if len(middle_words) >= 3:
            instructor = " ".join(middle_words[-2:])
            class_name = " ".join(middle_words[:-2])
        else:
            instructor = None
            class_name = m.group("middle")

        capacity_free = capacity_total = None
        free_m = _FREE_RE.match(status)
        occ_m = _OCCUPIED_RE.match(status)
        if free_m:
            capacity_free = int(free_m.group(1))
        elif occ_m:
            taken, total = int(occ_m.group(1)), int(occ_m.group(2))
            capacity_total = total
            capacity_free = total - taken

        entries.append(
            {
                "_structured": True,
                "class_name": class_name,
                "start_time": m.group("start"),
                "end_time": m.group("end"),
                "instructor": instructor,
                "capacity_free": capacity_free,
                "capacity_total": capacity_total,
            }
        )
    return entries


def _normalize_entry(entry: dict[str, Any], studio: dict[str, str], day: date) -> dict[str, Any]:
    if entry.get("_structured"):
        class_name = entry["class_name"]
        start_time = entry["start_time"]
        end_time = entry["end_time"]
        instructor = entry["instructor"]
        capacity_free = entry["capacity_free"]
        capacity_total = entry["capacity_total"]
    else:
        class_name = str(entry.get("nazev") or entry.get("name") or entry.get("predmet") or entry.get("kurz") or "Lekce")
        start_time = str(entry.get("cas") or entry.get("time") or entry.get("cas_od") or "") or None
        end_time = None
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
        "end_time": end_time,
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

    try:
        home = session.get(base_url, timeout=REQUEST_TIMEOUT)
        home.raise_for_status()
        id_sports = _discover_activity_sport_ids(home.text)
    except requests.RequestException as exc:
        log.warning("%s: nepodarilo se nacist hlavni stranku (%s), preskakuji", subdomain, exc)
        return lessons

    if not id_sports:
        log.warning("%s: na hlavni strance nenalezen zadny tab_type=\"activity\" (ROZVRH) s id_sport, preskakuji", subdomain)
        return lessons
    log.info("%s: nalezeny id_sport kandidati (ROZVRH taby) %s", subdomain, id_sports)

    time.sleep(REQUEST_DELAY_SECONDS)

    today = date.today()
    logged_sample = False
    for offset in range(DAYS_AHEAD):
        day = today + timedelta(days=offset)
        for id_sport in id_sports:
            try:
                resp = _fetch_day_raw(session, base_url, day, id_sport)
                raw = resp.text
            except requests.RequestException as exc:
                log.warning("%s %s (id_sport=%s): pozadavek selhal (%s)", subdomain, day, id_sport, exc)
                continue

            if not logged_sample:
                if raw.strip():
                    log.info(
                        "%s: ukazka syrove odpovedi status=%s content-type=%s delka=%d: %s",
                        subdomain, resp.status_code, resp.headers.get("Content-Type", ""), len(raw), raw[:1500],
                    )
                else:
                    log.warning(
                        "%s: PRAZDNA odpoved status=%s content-type=%s hlavicky=%s",
                        subdomain, resp.status_code, resp.headers.get("Content-Type", ""), dict(resp.headers),
                    )
                logged_sample = True

            entries: list[dict[str, Any]] = []
            try:
                entries = _parse_json_entries(raw)
            except (json.JSONDecodeError, TypeError):
                entries = _parse_html_entries(raw)

            if not entries:
                log.debug("%s %s (id_sport=%s): zadne rozpoznatelne lekce v odpovedi", subdomain, day, id_sport)

            for entry in entries:
                lessons.append(_normalize_entry(entry, studio, day))

            time.sleep(REQUEST_DELAY_SECONDS)

    log.info("%s: celkem nalezeno %d lekci", subdomain, len(lessons))
    return lessons
