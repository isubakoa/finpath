"""
Brainport Eindhoven's job portal (brainporteindhoven.com/int/work/jobs): ~2,300
English-language vacancies in the Eindhoven region, mostly engineering. The
page's own app fetches the list (with a key it keeps to itself), so this reader
opens the page in headless Chrome (browser.py), types each of QUERIES into its
search box and presses "Load more vacancies", keeping the answers the page gets:

    brainport-joblist.partout.dev/api/v1/vacancies?page=<n>&filter[searchTerm]=<q>&filter[language]=en...
    -> {"data": [...], "meta": {"current_page", "last_page", "total"}}   (15 a page)

Each vacancy has title, url (the employer's ad), job_date, organization.name
and location.name.
"""
import time
from urllib.parse import unquote_plus

from browser import PAGE_TIMEOUT_MS, run_in_browser
from common import Collector, iso_date, make_row, place

PORTAL_URL = "https://brainporteindhoven.com/int/work/jobs"
ANSWER_URL = "partout.dev/api/v1/vacancies"
SEARCH_BOX = 'input[placeholder^="Search a vacancy"]'
SEARCH_BUTTON = ".job-list__search-btn"
QUERIES = ("product", "designer", "user experience")  # the search ignores terms under 3 letters ("ux")
MAX_PAGES_PER_QUERY = 4
PAUSE_SECONDS = 1.0


def _vacancy_to_row(v):
    org = v.get("organization") if isinstance(v.get("organization"), dict) else {}
    loc = v.get("location") if isinstance(v.get("location"), dict) else {}
    return make_row(v.get("url"), org.get("name"), v.get("title"), place(loc.get("name"), "Netherlands"),
                    iso_date(v.get("job_date")))


def browser_pages(browser):
    """pages(query, page) -> the page's own answer for that query and page."""
    state = {"opened": False}

    def pages(query, page):
        if not state["opened"]:
            browser.page.goto(PORTAL_URL, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
            browser.page.wait_for_selector(SEARCH_BOX, timeout=PAGE_TIMEOUT_MS)
            state["opened"] = True

        def is_answer(resp):
            url = unquote_plus(resp.url)
            return f"[searchTerm]={query}" in url and f"page={page}&" in url

        def submit(p):
            p.fill(SEARCH_BOX, query)
            p.locator(SEARCH_BUTTON).first.dispatch_event("click")

        def load_more(p):
            p.locator("button", has_text="Load more vacancies").first.dispatch_event("click")

        bodies = browser.answers(submit if page == 1 else load_more, ANSWER_URL, accept=is_answer)
        if not bodies:
            raise RuntimeError("no readable search answer")
        return bodies[-1]
    return pages


def _read_with(pages, c, sleep):
    for query in QUERIES:
        def fetch(page, query=query):
            data = pages(query, page)
            vacancies = data.get("data") if isinstance(data, dict) else None
            if not isinstance(vacancies, list):
                raise RuntimeError("unexpected answer")
            meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
            last = meta.get("last_page") if isinstance(meta.get("last_page"), int) else 0
            return [_vacancy_to_row(v) for v in vacancies if isinstance(v, dict)], None, bool(vacancies) and page < last
        if not c.run(fetch, sleep=sleep, pause=PAUSE_SECONDS, max_pages=MAX_PAGES_PER_QUERY, label=f"{query!r} "):
            break


def read(http=None, sleep=time.sleep, terms=(), pages=None):
    c = Collector("brainport")
    if pages is not None:
        _read_with(pages, c, sleep)
    else:
        run_in_browser(c, lambda browser: _read_with(browser_pages(browser), c, sleep))
    return c.rows, c.health()
