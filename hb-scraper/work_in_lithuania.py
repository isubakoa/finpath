"""
Work in Lithuania (jobs.workinlithuania.com, Invest Lithuania): ~210 roles at
international companies, read in full:

    GET https://jobs.workinlithuania.com/api/job-offers?page=<n>
    -> {"data": [...], "meta": {"total", "last_page"}}   (12 a page)

Each offer has name (title), company.name, location ("Vilnius", "Kaunas,
Remote job") and slug (the ad on cvbankas.lt). The date is only relative
("Added 8 hours ago"), so ZenPath's first-seen date stands in.
"""
import time

import requests

from common import Collector, make_row, place, request

SEARCH_URL = "https://jobs.workinlithuania.com/api/job-offers"
MAX_PAGES = 40
PAUSE_SECONDS = 0.5


def _offer_to_row(offer):
    company = offer.get("company") if isinstance(offer.get("company"), dict) else {}
    city = str(offer.get("location") or "").split(",")[0].strip()
    return make_row(offer.get("slug"), company.get("name"), offer.get("name"),
                    place("" if city.lower() == "other" else city, "Lithuania"))


def read(http=requests, sleep=time.sleep, terms=()):
    c = Collector("workinlithuania")

    def fetch(page):
        data = request(http, "get", SEARCH_URL, params={"page": page},
                       headers={"Referer": "https://jobs.workinlithuania.com/"})
        offers = data.get("data") if isinstance(data, dict) else None
        if not isinstance(offers, list):
            raise RuntimeError("unexpected answer")
        meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
        last = meta.get("last_page") if isinstance(meta.get("last_page"), int) else None
        return [_offer_to_row(o) for o in offers if isinstance(o, dict)], meta.get("total"), bool(offers) and (last is None or page < last)

    c.run(fetch, sleep=sleep, pause=PAUSE_SECONDS, max_pages=MAX_PAGES)
    return c.rows, c.health()
