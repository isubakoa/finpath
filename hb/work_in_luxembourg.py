import time

import requests

from common import Collector, iso_date, make_row, request

SITE_URL = "https://jobs.workinluxembourg.com"
SEARCH_URL = SITE_URL + "/api/job-boards/offers"
BOARD_ID = "fb32de78-736f-4c94-8496-e78d0753d92a"
MAX_PAGES = 100
PAUSE_SECONDS = 0.3


def _offer_to_row(offer):
    titles = offer.get("titles") if isinstance(offer.get("titles"), dict) else {}
    return make_row(f"{SITE_URL}/offers/{offer['id']}" if offer.get("id") else "", offer.get("exhibitorName"),
                    titles.get("en") or titles.get("fr") or titles.get("de"), "Luxembourg",
                    iso_date(offer.get("publishedAt")))


def read(http=requests, sleep=time.sleep, terms=()):
    c = Collector("workinluxembourg")

    def fetch(page):
        data = request(http, "get", SEARCH_URL, params={"page": page - 1},
                       headers={"JobBoard-Id": BOARD_ID, "Accept-Language": "en", "Referer": SITE_URL + "/offers"})
        offers = data.get("content") if isinstance(data, dict) else None
        if not isinstance(offers, list):
            raise RuntimeError("unexpected answer")
        pages = data.get("totalPages") if isinstance(data.get("totalPages"), int) else None
        rows = [_offer_to_row(o) for o in offers if isinstance(o, dict) and not o.get("expired")]
        return rows, data.get("totalElements"), bool(offers) and (pages is None or page < pages)

    c.run(fetch, sleep=sleep, pause=PAUSE_SECONDS, max_pages=MAX_PAGES)
    return c.rows, c.health()
