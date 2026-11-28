import re
import time
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

from common import Collector, make_row, request

SITE_URL = "https://talent.berlin"
QUERIES = ("product manager", "product owner", "product designer", "ux designer", "design lead", "head of design")
MAX_PAGES_PER_QUERY = 5
PAUSE_SECONDS = 0.5


def _us_date(text):
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", text or "")
    return f"{m.group(3)}-{m.group(1)}-{m.group(2)}" if m else None


def _card_to_row(card):
    link = card.select_one("a[href]")
    title, company, date = card.select_one("h3"), card.select_one(".c-joblist__company"), card.select_one(".c-joblist__date")
    href = link.get("href", "") if link else ""
    return make_row(SITE_URL + href if href.startswith("/") else href,
                    company.get_text(" ", strip=True) if company else "", title.get_text(" ", strip=True) if title else "",
                    "Berlin, Germany", _us_date(date.get_text() if date else ""))


def read(http=requests, sleep=time.sleep, terms=()):
    c = Collector("talentberlin")
    for query in QUERIES:
        def fetch(page, query=query):
            url = f"{SITE_URL}/jobs/search-results/ajax-search/page/{page}/ajax-jobs.json?q={quote(query)}"
            data = request(http, "get", url, headers={"Referer": SITE_URL + "/jobs/search-results"})
            if not isinstance(data, dict) or "template" not in data:
                raise RuntimeError("unexpected answer")
            cards = BeautifulSoup(data.get("template") or "", "html.parser").select(".c-joblist__item")
            return [_card_to_row(card) for card in cards], None, bool(cards) and bool(data.get("nextSearchPageCount"))
        c.run(fetch, sleep=sleep, pause=PAUSE_SECONDS, max_pages=MAX_PAGES_PER_QUERY, label=f"{query!r} ")
        sleep(PAUSE_SECONDS)
    return c.rows, c.health()
