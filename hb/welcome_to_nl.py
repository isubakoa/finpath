import time

import requests

from common import Collector, iso_date, make_row, request

SEARCH_URL = "https://jobportal.ent.europe-west4.gcp.elastic-cloud.com/api/as/v1/engines/rvo/search"
AUTH_HEADER = "Bearer search-o21ix7ak2jiao92yvzceums2"
ORIGIN = "https://www.welcome-to-nl.nl"
PAGE_SIZE = 25
MAX_PAGES_PER_TERM = 2
PAUSE_SECONDS = 0.5


def _raw(result, field):
    v = result.get(field)
    return v.get("raw") if isinstance(v, dict) else None


def _result_to_row(result):
    locations = _raw(result, "locations") or []
    return make_row(_raw(result, "url"), _raw(result, "company_name"), _raw(result, "title"),
                    locations[0] if locations else "", iso_date(_raw(result, "created_at")))


def read(http=requests, sleep=time.sleep, terms=()):
    c = Collector("welcometonl")
    headers = {"Authorization": AUTH_HEADER, "Content-Type": "application/json",
               "Origin": ORIGIN, "Referer": ORIGIN + "/jobs/"}
    for term in terms:
        def fetch(page, term=term):
            body = {"query": term, "page": {"current": page, "size": PAGE_SIZE}, "filters": {},
                    "sort": [{"created_at": "desc"}]}
            data = request(http, "post", SEARCH_URL, json=body, headers=headers)
            results = data.get("results") if isinstance(data, dict) else None
            if not isinstance(results, list):
                raise RuntimeError("unexpected answer")
            return [_result_to_row(r) for r in results if isinstance(r, dict)], None, len(results) == PAGE_SIZE
        c.run(fetch, sleep=sleep, pause=PAUSE_SECONDS, max_pages=MAX_PAGES_PER_TERM, label=f"{term!r} ")
        sleep(PAUSE_SECONDS)
    return c.rows, c.health()
