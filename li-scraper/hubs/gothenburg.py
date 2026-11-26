"""
Careers in Gothenburg (careersingothenburg.com, Move to Gothenburg): ~500
English-only jobs in West Sweden. The page searches a Meilisearch index from
the browser, so this reader opens the page in headless Chrome (Playwright,
using the Chrome already on GitHub's runner) and keeps the page's own search
answer for each of QUERIES:

    https://careersingothenburg.com/?query=<q>&offset=<n>&filters={"english":true,...}
    -> the page's POST to search-movetogbg.tenfifty.io/indexes/jobs/search
       answers {"hits": [...], "estimatedTotalHits": n}, 20 hits a page

Each hit has title, employer_name, location.lvl1 ("Gothenburg Region >
Gothenburg"), published (Unix time), description and url (the employer's ad).

The site asks anonymous visitors to log in after many searches, so a run makes
only a handful (narrow QUERIES, at most MAX_PAGES_PER_QUERY each). If it ever
asks anyway, the search answer doesn't come, and the run reports it.
"""
import json
import time
from urllib.parse import quote

from .common import Collector, epoch_date, make_row, place

PORTAL_URL = "https://careersingothenburg.com/"
SEARCH_HOST = "tenfifty.io"
FILTERS = {"english": True, "employment_type": [], "working_hours_type": [],
           "location.lvl0": [], "location.lvl1": [], "published": "any"}
QUERIES = ("product manager", "product owner", "designer", "ux")
PAGE_SIZE = 20
MAX_PAGES_PER_QUERY = 3
PAUSE_SECONDS = 1.0
PAGE_TIMEOUT_MS = 30000


def page_url(query, offset):
    return (f"{PORTAL_URL}?query={quote(query)}&offset={offset}"
            f"&filters={quote(json.dumps(FILTERS, separators=(',', ':')))}")


class BrowserSearch:
    """search(query, offset) -> the page's own search answer, via headless Chrome."""

    def __enter__(self):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        try:
            self._browser = self._pw.chromium.launch(channel="chrome", headless=True)
        except Exception:
            self._pw.stop()
            raise
        self._page = self._browser.new_page()
        return self

    def __call__(self, query, offset):
        def is_answer(resp):
            post = resp.request.post_data or ""
            return SEARCH_HOST in resp.url and resp.request.method == "POST" and json.dumps(query) in post
        with self._page.expect_response(is_answer, timeout=PAGE_TIMEOUT_MS) as answer:
            self._page.goto(page_url(query, offset), wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
        resp = answer.value
        if resp.status != 200:
            raise RuntimeError(f"search answered HTTP {resp.status}")
        return resp.json()

    def __exit__(self, *exc):
        self._browser.close()
        self._pw.stop()


def _hit_to_row(hit):
    area = str(hit.get("location.lvl1") or hit.get("location.lvl0") or "")
    city = area.split(">")[-1].strip()
    description = hit.get("description")
    return make_row(hit.get("url") or hit.get("employer_application_url"), hit.get("employer_name"),
                    hit.get("title"), place("" if city.lower().endswith("region") else city, "Sweden"),
                    epoch_date(hit.get("published")), description if isinstance(description, str) else "")


def _read_with(search, c, sleep):
    for query in QUERIES:
        def fetch(page, query=query):
            data = search(query, (page - 1) * PAGE_SIZE)
            hits = data.get("hits") if isinstance(data, dict) else None
            if not isinstance(hits, list):
                raise RuntimeError("unexpected answer")
            total = data.get("estimatedTotalHits") if isinstance(data.get("estimatedTotalHits"), int) else 0
            return [_hit_to_row(h) for h in hits if isinstance(h, dict)], None, bool(hits) and page * PAGE_SIZE < total
        if not c.run(fetch, sleep=sleep, pause=PAUSE_SECONDS, max_pages=MAX_PAGES_PER_QUERY, label=f"{query!r} "):
            break  # each failed page costs a 30 s wait; the other queries would fail the same way


def read(http=None, sleep=time.sleep, terms=(), search=None):
    c = Collector("gothenburg")
    if search is not None:
        _read_with(search, c, sleep)
        return c.rows, c.health()
    try:
        with BrowserSearch() as browser_search:
            _read_with(browser_search, c, sleep)
    except Exception as e:  # noqa: BLE001 -- no browser, or it crashed: report, don't break the run
        c.fail(f"browser: {type(e).__name__}: {str(e).splitlines()[0][:160] if str(e) else ''}")
    return c.rows, c.health()
