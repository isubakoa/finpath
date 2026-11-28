import time

import requests

from common import Collector, is_english, iso_date, make_row, place, request

SEARCH_URL = "https://jobsearch.api.jobtechdev.se/search"
QUERIES = ("product manager", "product owner", "product lead", "product designer", "ux", "service designer",
           "design lead", "head of design", "designer")
PAGE_SIZE = 100
MAX_PAGES_PER_QUERY = 3
PAUSE_SECONDS = 0.5


def _hit_to_row(hit):
    description = (hit.get("description") or {}).get("text") if isinstance(hit.get("description"), dict) else ""
    if not is_english(description or ""):
        return None
    address = hit.get("workplace_address") if isinstance(hit.get("workplace_address"), dict) else {}
    employer = hit.get("employer") if isinstance(hit.get("employer"), dict) else {}
    return make_row(hit.get("webpage_url"), employer.get("name"), hit.get("headline"),
                    place(address.get("city") or address.get("municipality"), "Sweden"),
                    iso_date(hit.get("publication_date")), description)


def read(http=requests, sleep=time.sleep, terms=()):
    c = Collector("arbetsformedlingen")
    for query in QUERIES:
        def fetch(page, query=query):
            data = request(http, "get", SEARCH_URL, params={"q": query, "limit": PAGE_SIZE,
                                                           "offset": (page - 1) * PAGE_SIZE})
            hits = data.get("hits") if isinstance(data, dict) else None
            if not isinstance(hits, list):
                raise RuntimeError("unexpected answer")
            total = (data.get("total") or {}).get("value") if isinstance(data.get("total"), dict) else 0
            rows = [_hit_to_row(h) for h in hits if isinstance(h, dict)]
            return rows, None, bool(hits) and page * PAGE_SIZE < (total or 0)
        c.run(fetch, sleep=sleep, pause=PAUSE_SECONDS, max_pages=MAX_PAGES_PER_QUERY, label=f"{query!r} ")
        sleep(PAUSE_SECONDS)
    return c.rows, c.health()
