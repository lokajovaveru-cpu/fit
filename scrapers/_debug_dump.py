"""DOCASNY diagnosticky skript - ted uz vime, ze POST funguje a vraci
realny rozvrh. Potrebujeme videt skutecnou HTML strukturu JEDNE karty
lekce (ne jen zplostely text), abychom napsali presny parser podle
tagu/trid misto hrubeho fallbacku. Smazat po dolazeni parseru."""

from __future__ import annotations

import re

import requests
from bs4 import BeautifulSoup

UA = "BrnoFitAgregator/1.0 (+https://github.com/lokajovaveru-cpu/fit; diagnostika)"


def dump():
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "cs,en;q=0.8"})

    base = "https://rehabfit.isportsystem.cz"
    s.get(base + "/", timeout=15)  # warm up cookies like the real scraper does

    form_data = {
        "id_sport": "5",
        "day": 25,
        "month": 8,
        "year": 2026,
        "event": "init",
        "timetableWidth": 900,
        "arLabelId": "",
        "noticeCheckRequested": 0,
        "noticeCheck": 0,
        "idNoticeCheck": "",
    }
    r = s.post(
        base + "/ajax/ajax.schema.php",
        data=form_data,
        headers={"X-Requested-With": "XMLHttpRequest", "Referer": base + "/"},
        timeout=15,
    )
    raw = r.text
    print(f"=== status={r.status_code} len={len(raw)} ===")

    soup = BeautifulSoup(raw, "html.parser")

    # find the first element whose OWN text (not descendants) looks like a time
    time_re = re.compile(r"\d{1,2}:\d{2}")
    idx = time_re.search(raw)
    if idx:
        start = max(0, idx.start() - 300)
        print("=== raw HTML around first time match (readable via BeautifulSoup) ===")
        fragment = BeautifulSoup(raw[start:start + 4000], "html.parser")
        print(fragment.prettify()[:6000])
    else:
        print("no time pattern found in raw response at all")

    print("=== all distinct class= values seen anywhere in the document (deduped) ===")
    classes = set()
    for el in soup.find_all(class_=True):
        classes.update(el.get("class"))
    print(sorted(classes))
