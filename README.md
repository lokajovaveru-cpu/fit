# Brno Fit Rozvrh

Přehled aktuálně volných fitness lekcí (jóga, pilates, jumping, funkční
trénink...) napříč fitness studii v Brně na jednom místě — bez nutnosti
proklikávat rozvrh každého studia zvlášť.

Studia nemají společné API, takže se data berou přímo z jejich veřejných
rezervačních systémů (scraping). Výsledek je vidět na statickém webu v
`docs/`, který se dá zdarma hostovat přes GitHub Pages.

## Jak to funguje

```
scrapers/studios.json      konfigurace studií (podle čeho se pozná, jak scrapovat)
scrapers/isportsystem.py   scraper pro studia na platformě iSportSystem
scrapers/aggregate.py      spustí scraper pro každé nakonfigurované studio
        ↓ zapíše
docs/data/lessons.json     sesbíraná data
        ↓ načte
docs/index.html + app.js   statický web s filtry (typ lekce, studio, den, volná místa)
```

`.github/workflows/scrape.yml` spouští `aggregate.py` automaticky (každé 2
hodiny, i ručně přes "Run workflow") a výsledek commitne zpět do repa. Jakmile
je na výchozí větvi zapnuté GitHub Pages (Settings → Pages → Deploy from a
branch → `main` / `docs`), web se aktualizuje automaticky s daty.

## Aktuální stav pokrytí

V první verzi je pokrytá jedna sdílená rezervační platforma — **iSportSystem**
— na které běží víc brněnských studií najednou, takže stačí jedna integrace:

- REHABFIT
- Pilates Place
- Y Studio
- Yoga Place
- Jóga v Brně

Ověřeno živě přes GitHub Actions (viz historie commitů „Aktualizace rozvrhu
lekcí"): scraper reálně stahuje a parsuje rozvrh, aktuálně např. 1135 lekcí
napříč 4 z 5 studií za 7 dní dopředu (páté, Jóga v Brně, mělo v momentě
testování prázdný rozvrh — buď mezi lekcemi, nebo publikuje rozvrh jinak;
stojí za občasnou kontrolu). Známé drobné nepřesnosti parsování (týkají se
řádově jednotek procent lekcí):

- Jméno instruktora se odhaduje jako poslední dvě slova textu lekce (běžný
  vzor „Jméno Příjmení"). Pokud studio uvádí instruktora jen křestním jménem
  (děje se u Y Studia), jméno zůstane součástí `class_name` místo
  `instructor` — lekce se tím neztratí, jen je popisek méně čistý.
- Ojediněle se do jména instruktora dostane doplňkový štítek z webu (např.
  „Pozdě" u lekcí s pozdní uzávěrkou přihlášek) místo skutečného příjmení.

Studia s vlastním rezervačním systémem (např. Miss Fit, MyFit, BIG ONE
FITNESS, AZ Fitness...) zatím pokrytá nejsou — pro každé bude potřeba
samostatný scraper modul (viz „Přidání dalšího studia" níže).

## Lokální spuštění

```bash
pip install -r scrapers/requirements.txt
python scrapers/aggregate.py          # zapíše docs/data/lessons.json

cd docs && python3 -m http.server 8000  # web běží na http://localhost:8000
```

(Web si data načítá přes `fetch`, takže nejde jen otevřít `index.html` v
prohlížeči přes `file://` — je potřeba lokální server.)

## Přidání dalšího studia

**Na iSportSystem:** stačí přidat záznam do `scrapers/studios.json` se
správnou subdoménou (`https://<subdoména>.isportsystem.cz/`).

**Na jiné platformě:** vytvořit nový modul v `scrapers/` se stejným rozhraním
jako `isportsystem.py` (funkce `scrape(studio) -> list[dict]`), zaregistrovat
ho v `SCRAPERS` v `aggregate.py` a přidat studio do `studios.json` s
odpovídající hodnotou `platform`.

## Etika a šetrnost ke scrapovaným webům

Protože je cílem web časem sdílet dál, scraper se snaží chovat slušně:

- posílá popisné `User-Agent` (ne masku prohlížeče),
- před stahováním kontroluje `robots.txt`,
- mezi požadavky čeká, neposílá je nárazově,
- běží jen jednou za 2 hodiny, ne v reálném čase na každé načtení stránky,
- na webu je jasně uvedeno, že rezervace probíhá vždy přímo u studia (přes
  odkaz „Rezervovat"), tenhle web žádné rezervace nezpracovává.

Pokud by některé studio o zařazení nestálo, je namístě ho ze
`scrapers/studios.json` odebrat.
