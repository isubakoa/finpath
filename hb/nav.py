"""
NAV arbeidsplassen (Norway's Labour and Welfare Administration), ads whose
working language is English (~2,600), searched for QUERIES. Server-rendered
pages of 25:

    GET https://arbeidsplassen.nav.no/stillinger?v=6&workLanguage=Engelsk&q=<q>&from=<n>

Each result is an <article>: date ("21. november 2026"), title link
(/stillinger/stilling/<id>), then "Arbeidsgiver" <employer> and "Sted" <place>.
The page says how many matched ("61 treff").
"""
import re
import time

import requests
from bs4 import BeautifulSoup

from common import Collector, make_row, place, request

SITE_URL = "https://arbeidsplassen.nav.no"
SEARCH_URL = SITE_URL + "/stillinger"
QUERIES = ("product manager", "product owner", "product designer", "ux", "designer", "design lead")
PAGE_SIZE = 25
MAX_PAGES_PER_QUERY = 4
PAUSE_SECONDS = 1.0
MONTHS = {m: i + 1 for i, m in enumerate(["januar", "februar", "mars", "april", "mai", "juni", "juli",
                                          "august", "september", "oktober", "november", "desember"])}


def norwegian_date(text):
    """'21. november 2026' -> '2026-11-21', else None."""
    m = re.match(r"\s*(\d{1,2})\.\s*([a-zæøå]+)\s+(\d{4})", text or "", re.IGNORECASE)
    if not m or m.group(2).lower() not in MONTHS:
        return None
    return f"{m.group(3)}-{MONTHS[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"


def _after(parts, label):
    return parts[parts.index(label) + 1] if label in parts and parts.index(label) + 1 < len(parts) else ""


def _article_to_row(article):
    link = article.select_one("h2 a[href]")
    parts = [p.get_text(" ", strip=True) for p in article.select("p, span") if p.get_text(strip=True)]
    href = link.get("href", "") if link else ""
    return make_row(SITE_URL + href if href.startswith("/") else href, _after(parts, "Arbeidsgiver"),
                    link.get_text(" ", strip=True) if link else "", place(_after(parts, "Sted"), "Norway"),
                    norwegian_date(parts[0]) if parts else None)


def read(http=requests, sleep=time.sleep, terms=()):
    c = Collector("nav")
    for query in QUERIES:
        def fetch(page, query=query):
            page_html = request(http, "get", SEARCH_URL, expect="text",
                                params={"v": 6, "workLanguage": "Engelsk", "q": query, "from": (page - 1) * PAGE_SIZE})
            soup = BeautifulSoup(page_html, "html.parser")
            articles = soup.select("article")
            found = re.search(r"([\d\s ]+)\s+treff", soup.get_text(" ", strip=True))
            total = int(re.sub(r"\D", "", found.group(1))) if found and re.sub(r"\D", "", found.group(1)) else None
            if page == 1 and not articles and total is None:
                raise RuntimeError("no result list on the page (changed or blocked)")
            return [_article_to_row(a) for a in articles], None, bool(articles) and (total is None or page * PAGE_SIZE < total)
        c.run(fetch, sleep=sleep, pause=PAUSE_SECONDS, max_pages=MAX_PAGES_PER_QUERY, label=f"{query!r} ")
        sleep(PAUSE_SECONDS)
    return c.rows, c.health()
