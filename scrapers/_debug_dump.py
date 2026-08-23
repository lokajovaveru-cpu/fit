"""
DOCASNY diagnosticky skript - NENI soucast produkcni pipeline.
Pousti se rucne (docasne pres workflow) jen pro zjisteni skutecne struktury
iSportSystem stranek/ajax volani, aby se dalo doladit scrapers/isportsystem.py
podle overenych dat, ne odhadu. Po dolazeni scraperu se ma tento soubor smazat.
"""

from __future__ import annotations

import re

import requests

UA = "BrnoFitAgregator/1.0 (+https://github.com/lokajovaveru-cpu/fit; diagnostika)"


def dump():
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "cs,en;q=0.8"})

    base = "https://rehabfit.isportsystem.cz"
    print(f"=== HOMEPAGE {base}/ ===")
    home = s.get(base + "/", timeout=15)
    print(f"status={home.status_code} len={len(home.text)}")
    print("--- script src ---")
    for m in re.finditer(r"<script[^>]*\bsrc=[\"']([^\"']+)[\"']", home.text):
        print(m.group(1))
    print("--- iframe src ---")
    for m in re.finditer(r"<iframe[^>]*\bsrc=[\"']([^\"']+)[\"']", home.text):
        print(m.group(1))
    print("--- links/mentions containing 'infotab' (case-insensitive) ---")
    for m in re.finditer(r".{60}infotab.{60}", home.text, re.IGNORECASE):
        print(repr(m.group(0)))
    print("--- links/mentions containing 'schema' (case-insensitive) ---")
    for m in re.finditer(r".{60}schema.{60}", home.text, re.IGNORECASE):
        print(repr(m.group(0)))
    print("--- FULL HOMEPAGE HTML (first 8000 chars) ---")
    print(home.text[:8000])
    print("--- FULL HOMEPAGE HTML (chars 8000-16000) ---")
    print(home.text[8000:16000])

    ajax_url = base + "/ajax/ajax.schema.php"
    variants = [
        ("A current (id_sport=infoTab)", {"day": 24, "month": 8, "year": 2026, "id_sport": "infoTab", "id_infotab": "35", "event": "pageLoad"}),
        ("B numeric id_sport", {"day": 24, "month": 8, "year": 2026, "id_sport": "35", "event": "pageLoad"}),
        ("C no id_sport", {"day": 24, "month": 8, "year": 2026, "id_infotab": "35", "event": "pageLoad"}),
        ("D minimal", {"id_infotab": "35"}),
        ("E no params at all", {}),
    ]
    for label, params in variants:
        r = s.get(ajax_url, params=params, headers={"X-Requested-With": "XMLHttpRequest", "Referer": base + "/"}, timeout=15)
        print(f"=== AJAX variant {label} -> status={r.status_code} len={len(r.text)} body[:300]={r.text[:300]!r}")

    print("=== root page with ?id_infotab=35 (maybe tabs are full page loads, not ajax) ===")
    r = s.get(base + "/", params={"id_infotab": "35"}, timeout=15)
    print(f"status={r.status_code} len={len(r.text)}")
    # if this differs meaningfully in length from the plain homepage, the tab
    # content is server-rendered on full page load, not via the ajax script.


if __name__ == "__main__":
    dump()
