"""
Skåne's STEM job portal (skane.com, International House Skåne): ~240 STEM jobs
in Malmö, Lund and around that don't require Swedish, taken from the Swedish
employment service. Plain server-rendered pages, 10 cards each:

    GET https://skane.com/live-work/international-house/stem-jobportal/
        ?q&sortOrder=relevance&location&pej_page=<n>

The search box filters in the browser only, so every page is read. A card
(.pej-job-card) has the title, city badge, employer, "Published: YYYY-MM-DD"
and an apply link to arbetsformedlingen.se.
"""
import re
import time

import requests
from bs4 import BeautifulSoup

from common import Collector, iso_date, make_row, place, request

PORTAL_URL = "https://skane.com/live-work/international-house/stem-jobportal/"
PAGE_SIZE = 10
MAX_PAGES = 60
PAUSE_SECONDS = 1.0


def _card_to_row(card):
    def text(sel):
        el = card.select_one(sel)
        return el.get_text(" ", strip=True) if el else ""
    link = card.select_one("a.pej-apply-button")
    published = re.search(r"Published:\s*(\d{4}-\d{2}-\d{2})", card.get_text(" ", strip=True))
    description = text(".pej-job-description")
    return make_row(link.get("href") if link else "", text(".pej-job-employer"), text(".pej-job-title"),
                    place(text(".pej-badge-location"), "Sweden"),
                    iso_date(published.group(1)) if published else None, description)


def read(http=requests, sleep=time.sleep, terms=()):
    c = Collector("skane")

    def fetch(page):
        page_html = request(http, "get", PORTAL_URL, expect="text",
                            params={"q": "", "sortOrder": "relevance", "location": "", "pej_page": page})
        soup = BeautifulSoup(page_html, "html.parser")
        cards = soup.select(".pej-job-card")
        listed = re.search(r"(\d+)\s+job ads are listed", soup.get_text(" ", strip=True))
        total = int(listed.group(1)) if listed else None
        if page == 1 and not cards and total is None:
            raise RuntimeError("no job list on the page (changed or blocked)")
        more = bool(cards) and (total is None or page * PAGE_SIZE < total)
        return [_card_to_row(card) for card in cards], total, more

    c.run(fetch, sleep=sleep, pause=PAUSE_SECONDS, max_pages=MAX_PAGES)
    return c.rows, c.health()
