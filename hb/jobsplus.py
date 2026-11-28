"""
Jobsplus (jobsplus.gov.mt, Malta's employment agency), searched for QUERIES.
The vacancy page loads its list as an HTML fragment:

    https://jobsplus.gov.mt/vacancy?SearchText=<q>
    -> the page's GET /Umbraco/Surface/Vacancy/GetVacancyListData?...&searchText=<q>&pageNumber=<n>

Jobsplus refuses that list to GitHub's servers when asked directly (HTTP 403,
27 Nov), so this reader opens the vacancy page in headless Chrome (browser.py)
and keeps the fragments the page gets, pressing its "next" arrow for more pages.

Each <li id="<vacancy id>"> has the title (h3, in capitals), the place
("TAS-SLIEMA, MALTA") and a short description; the page for it is
/vacancy/vacancy-details?id=<id>. Jobsplus only shows the company to signed-in
users, so the employer is COMPANY_HIDDEN (Isu's choice: show the role anyway).
"""
import re
import time
from urllib.parse import quote, unquote_plus

from bs4 import BeautifulSoup

from browser import PAGE_TIMEOUT_MS, run_in_browser
from common import Collector, make_row, place, tidy_caps

SITE_URL = "https://jobsplus.gov.mt"
ANSWER_URL = "/Umbraco/Surface/Vacancy/GetVacancyListData"
COMPANY_HIDDEN = "Company shown after Jobsplus sign-in"
QUERIES = ("product", "designer", "ux", "design")
PAGE_SIZE = 10
MAX_PAGES_PER_QUERY = 5
PAUSE_SECONDS = 0.5


def _item_to_row(item):
    vacancy_id = item.get("id", "")
    title = item.select_one("h3")
    pin = item.select_one(".fa-map-pin")
    where = tidy_caps(pin.parent.get_text(" ", strip=True)) if pin and pin.parent else ""
    city = where.split(",")[0].strip()
    texts = [p.get_text(" ", strip=True) for p in item.select("p")]
    description = next((t for t in texts if "log in" not in t.lower()), "")
    return make_row(f"{SITE_URL}/vacancy/vacancy-details?id={vacancy_id}" if vacancy_id.isdigit() else "",
                    COMPANY_HIDDEN, tidy_caps(title.get_text(" ", strip=True)) if title else "",
                    place("" if city.lower() == "malta" else city, "Malta"), None, description)


def browser_fragments(browser):
    """fragment(query, page) -> the vacancy list HTML the page gets."""
    def fragment(query, page):
        def is_answer(resp):
            url = unquote_plus(resp.url)
            return f"searchText={query}&" in url and f"pageNumber={page}&" in url

        def open_or_next(p):
            if page == 1:
                p.goto(f"{SITE_URL}/vacancy?SearchText={quote(query)}", wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
            else:
                p.locator("a.pagination__numbers.next").first.dispatch_event("click")

        bodies = browser.answers(open_or_next, ANSWER_URL, accept=is_answer, as_text=True)
        if not bodies:
            raise RuntimeError("no readable vacancy list")
        return bodies[-1]
    return fragment


def _read_with(fragment, c, sleep):
    for query in QUERIES:
        def fetch(page, query=query):
            soup = BeautifulSoup(fragment(query, page), "html.parser")
            items = soup.select("ul.list-d > li[id]")
            count = re.search(r"(\d+)\s+Job\(s\)", soup.get_text(" ", strip=True))
            if page == 1 and not items and not count:
                raise RuntimeError("no vacancy list in the answer (changed or blocked)")
            total = int(count.group(1)) if count else None
            return [_item_to_row(i) for i in items], None, bool(items) and (total is None or page * PAGE_SIZE < total)
        if not c.run(fetch, sleep=sleep, pause=PAUSE_SECONDS, max_pages=MAX_PAGES_PER_QUERY, label=f"{query!r} "):
            break


def read(http=None, sleep=time.sleep, terms=(), fragment=None):
    c = Collector("jobsplus")
    if fragment is not None:
        _read_with(fragment, c, sleep)
    else:
        run_in_browser(c, lambda browser: _read_with(browser_fragments(browser), c, sleep))
    return c.rows, c.health()
