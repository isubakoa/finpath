import time

import requests
from bs4 import BeautifulSoup

from common import Collector, make_row, place, request

BASE_URL = "https://www.makeitinthenorth.nl/jobs/"
MAX_PAGES = 40
PAUSE_SECONDS = 1.0


def _badge(card, icon):
    for badge in card.select(".badge"):
        i = badge.select_one("i")
        if i and icon in (i.get("class") or []):
            return badge.get_text(" ", strip=True)
    return ""


def _card_to_row(card):
    title = card.select_one("h3")
    link = card.select_one(".btn-wrapper a[href]")
    return make_row(link.get("href") if link else "", _badge(card, "fa-house"),
                    title.get_text(" ", strip=True) if title else "",
                    place(_badge(card, "fa-location-dot"), "Netherlands"))


def read(http=requests, sleep=time.sleep, terms=()):
    c = Collector("makeitinthenorth")

    def fetch(page):
        url = BASE_URL if page == 1 else f"{BASE_URL}page/{page}/"
        soup = BeautifulSoup(request(http, "get", url, expect="text"), "html.parser")
        cards = soup.select("article.card-vacancy-labels")
        if page == 1 and not cards:
            raise RuntimeError("no job list on the page (changed or blocked)")
        return [_card_to_row(card) for card in cards], None, bool(cards)

    c.run(fetch, sleep=sleep, pause=PAUSE_SECONDS, max_pages=MAX_PAGES)
    return c.rows, c.health()
