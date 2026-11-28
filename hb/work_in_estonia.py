import time

import requests
from bs4 import BeautifulSoup

from common import Collector, make_row, place, request

AJAX_URL = "https://workinestonia.com/wp-admin/admin-ajax.php"
REFERER = "https://workinestonia.com/job/"
MAX_PAGES = 60
PAUSE_SECONDS = 0.5


def _text(card, cls):
    el = card.select_one("." + cls)
    return el.get_text(" ", strip=True) if el else ""


def _card_to_row(card):
    link = card.select_one("a.card-job__link")
    return make_row(link.get("href") if link else "", _text(card, "card-job__company"),
                    _text(card, "card-job__slide-title"), place(_text(card, "card-job__city"), "Estonia"))


def read(http=requests, sleep=time.sleep, terms=()):
    c = Collector("workinestonia")

    def fetch(page):
        data = request(http, "post", AJAX_URL, data={"action": "filter_job_offers", "paged": page, "search": "",
                                                    "categories": "placeholder", "locations": "placeholder"},
                       headers={"Referer": REFERER, "X-Requested-With": "XMLHttpRequest"})
        if not isinstance(data, dict) or data.get("status") != "success":
            raise RuntimeError("unexpected answer")
        cards = BeautifulSoup(data.get("html") or "", "html.parser").select(".card-job")
        return [_card_to_row(card) for card in cards], None, bool(cards)

    c.run(fetch, sleep=sleep, pause=PAUSE_SECONDS, max_pages=MAX_PAGES)
    return c.rows, c.health()
