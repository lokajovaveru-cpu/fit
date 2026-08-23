"""DOCASNY diagnosticky skript - stahne a proscanuje JS bundle, ktery
sestavuje realne ajax volani, abychom meli presny zdroj pravdy misto
dalsiho hadani parametru. Smazat po dolazeni scraperu."""

from __future__ import annotations

import re

import requests

UA = "BrnoFitAgregator/1.0 (+https://github.com/lokajovaveru-cpu/fit; diagnostika)"


def dump():
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "cs,en;q=0.8"})

    base = "https://rehabfit.isportsystem.cz"
    js_url = base + "/cache/js/629b0d3dd4aaa87b72d043d2645b0679.js"
    r = s.get(js_url, timeout=15)
    print(f"=== JS bundle {js_url} -> status={r.status_code} len={len(r.text)} ===")
    body = r.text

    for needle in ["schema.php", "id_sport", "ajax.schema", ".post(", "type:\"POST\"", "type: 'POST'", "loadSchema", "cell_width", "lanes"]:
        idxs = [m.start() for m in re.finditer(re.escape(needle), body)]
        print(f"--- {needle!r}: {len(idxs)} occurrences at {idxs[:10]} ---")

    # print generous windows around every 'schema.php' occurrence - this is
    # the actual call construction we need to see
    for m in re.finditer(re.escape("schema.php"), body):
        start = max(0, m.start() - 600)
        end = min(len(body), m.end() + 600)
        print("=== context around schema.php ===")
        print(body[start:end])

    if "schema.php" not in body:
        print("=== schema.php NOT found in this bundle, dumping first 6000 chars for manual inspection ===")
        print(body[:6000])


if __name__ == "__main__":
    dump()
