"""
Welcome to NL (welcome-to-nl.nl/jobs), a general Dutch jobs portal for
internationals. The page ships no listings in its HTML; it POSTs to an Elastic
App Search engine ("rvo"):

    https://jobportal.ent.europe-west4.gcp.elastic-cloud.com/api/as/v1/engines/rvo/search

AUTH_HEADER is the site's public, read-only "search-" key, Elastic's convention
for keys meant to be embedded in client JS. If it stops working, re-capture it
from the "search" request in DevTools › Network on welcome-to-nl.nl/jobs.

Searched per title term, newest first, two pages each. Each result's url is the
employer's own posting.
"""
import time

import requests

from .common import Collector, iso_date, make_row, request

SEARCH_URL = "https://jobportal.ent.europe-west4.gcp.elastic-cloud.com/api/as/v1/engines/rvo/search"
AUTH_HEADER = "Bearer search-o21ix7ak2jiao92yvzceums2"  # public, search-only
ORIGIN = "https://www.welcome-to-nl.nl"
PAGE_SIZE = 25
MAX_PAGES_PER_TERM = 2  # newest first, so a scheduled run only needs what's new
PAUSE_SECONDS = 0.5


def _raw(result, field):
    """App Search wraps every field as {"raw": ...}."""
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
