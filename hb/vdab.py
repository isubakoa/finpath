import time
from urllib.parse import quote

from browser import PAGE_TIMEOUT_MS, run_in_browser
from common import Collector, iso_date, make_row, place, tidy_caps

SITE_URL = "https://www.vdab.be"
ANSWER_URL = "/vindeenjob/v4/vacatureLight/zoek"
QUERIES = ("product designer", "ux designer", "product manager", "product owner", "service designer")
MAX_PAGES_PER_QUERY = 3
PAUSE_SECONDS = 1.0


def page_url(query, page):
    return f"{SITE_URL}/vindeenjob/vacatures?trefwoord={quote(query)}&sort=standaard&sinds=9000&p={page}"


def _result_to_row(r):
    vid = (r.get("id") or {}).get("id") if isinstance(r.get("id"), dict) else None
    function = r.get("vacaturefunctie") if isinstance(r.get("vacaturefunctie"), dict) else {}
    return make_row(f"{SITE_URL}/vindeenjob/vacatures/{vid}" if vid else "", r.get("vacatureBedrijfsnaam"),
                    function.get("naam"), place(tidy_caps(r.get("tewerkstellingsLocatieRegioOfAdres")), "Belgium"),
                    iso_date(r.get("eerstePublicatieDatum")))


def browser_search(browser):
    def search(query, page):
        bodies = browser.answers(
            lambda p: p.goto(page_url(query, page), wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS),
            ANSWER_URL, accept=lambda r: r.request.method == "POST")
        results = [b for b in bodies if isinstance(b, dict) and isinstance(b.get("resultaten"), list)]
        if not results:
            raise RuntimeError("no readable search answer")
        return results[-1]
    return search


def _read_with(search, c, sleep):
    for query in QUERIES:
        def fetch(page, query=query):
            data = search(query, page)
            results = data.get("resultaten") if isinstance(data, dict) else None
            if not isinstance(results, list):
                raise RuntimeError("unexpected answer")
            size = data.get("paginaGrootte") if isinstance(data.get("paginaGrootte"), int) else 15
            return [_result_to_row(r) for r in results if isinstance(r, dict)], None, len(results) >= size
        if not c.run(fetch, sleep=sleep, pause=PAUSE_SECONDS, max_pages=MAX_PAGES_PER_QUERY, label=f"{query!r} "):
            break


def read(http=None, sleep=time.sleep, terms=(), search=None):
    c = Collector("vdab")
    if search is not None:
        _read_with(search, c, sleep)
    else:
        run_in_browser(c, lambda browser: _read_with(browser_search(browser), c, sleep))
    return c.rows, c.health()
