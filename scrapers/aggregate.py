"""
Orchestrator: precte scrapers/studios.json, pro kazde studio zavola
prislusny scraper podle 'platform' a vysledek ulozi do docs/data/lessons.json,
odkud jej cte staticky frontend.

Pousteno lokalne:  python scrapers/aggregate.py
Pousteno v CI:      viz .github/workflows/scrape.yml
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import isportsystem

REPO_ROOT = Path(__file__).resolve().parent.parent
STUDIOS_FILE = REPO_ROOT / "scrapers" / "studios.json"
OUTPUT_FILE = REPO_ROOT / "docs" / "data" / "lessons.json"

SCRAPERS = {
    "isportsystem": isportsystem.scrape,
}


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log = logging.getLogger("aggregate")

    studios = json.loads(STUDIOS_FILE.read_text(encoding="utf-8"))["studios"]

    all_lessons = []
    studio_summaries = []
    had_error = False

    for studio in studios:
        scraper = SCRAPERS.get(studio["platform"])
        if scraper is None:
            log.warning("Studio %s: neznama platforma '%s', preskakuji", studio["id"], studio["platform"])
            continue

        log.info("Zpracovavam studio %s (%s)...", studio["name"], studio["platform"])
        try:
            lessons = scraper(studio)
        except Exception:  # noqa: BLE001 - jedno padle studio nesmi shodit cely beh
            log.exception("Studio %s: scraper selhal s neocekavanou vyjimkou", studio["id"])
            had_error = True
            lessons = []

        all_lessons.extend(lessons)
        studio_summaries.append(
            {
                "id": studio["id"],
                "name": studio["name"],
                "city": studio["city"],
                "address": studio.get("address"),
                "website": studio.get("website"),
                "lessons_found": len(lessons),
            }
        )

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "studios": studio_summaries,
        "lessons": all_lessons,
    }

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    log.info(
        "Hotovo: %d lekci z %d studii zapsano do %s",
        len(all_lessons),
        len(studio_summaries),
        OUTPUT_FILE,
    )

    # Nenulovy exit kod jen pri neocekavane vyjimce ve scraperu - chybejici
    # lekce (0 nalezenych) samy o sobe beh nepadaji, aby jedno docasne
    # nedostupne studio nezablokovalo aktualizaci dat od ostatnich.
    return 1 if had_error else 0


if __name__ == "__main__":
    sys.exit(main())
