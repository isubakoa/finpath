"""
Work in Austria (workinaustria.com), the national agency's board, ~1,050 jobs
(it also carries Come2Upper Austria's). The site reads a Solr search API:

    GET https://api.workinaustria.com/en/employees/jobs?tx_solr[action]=results
        &tx_solr[controller]=Search&tx_solr[cuid]=38222&type=7383
        &tx_solr[resultsPerPage]=100&tx_solr[page]=<n>
    -> {"searchResults": [...], "allResultCount": n}

Each result has title, businessCompanyName_textS, cities_stringM (or
businessCity_stringS), published_stringS, content (the description) and url
(a path on www.workinaustria.com).
"""
import time

import requests

from common import Collector, iso_date, make_row, place, request

SEARCH_URL = "https://api.workinaustria.com/en/employees/jobs"
SITE_URL = "https://www.workinaustria.com"
PAGE_SIZE = 100
MAX_PAGES = 30
PAUSE_SECONDS = 0.5


def _doc_to_row(doc):
    cities = [c for c in (doc.get("cities_stringM") or []) if isinstance(c, str)]
    path = doc.get("url") or ""
    content = doc.get("content")
    return make_row(SITE_URL + path if path.startswith("/") else path, doc.get("businessCompanyName_textS"),
                    doc.get("title"), place(cities[0] if cities else doc.get("businessCity_stringS"), "Austria"),
                    iso_date(doc.get("published_stringS")), content if isinstance(content, str) else "")


def read(http=requests, sleep=time.sleep, terms=()):
    c = Collector("workinaustria")

    def fetch(page):
        params = {"tx_solr[action]": "results", "tx_solr[controller]": "Search", "tx_solr[cuid]": "38222",
                  "type": "7383", "tx_solr[resultsPerPage]": PAGE_SIZE, "tx_solr[page]": page}
        data = request(http, "get", SEARCH_URL, params=params, headers={"Referer": SITE_URL + "/"})
        docs = data.get("searchResults") if isinstance(data, dict) else None
        if not isinstance(docs, list):
            raise RuntimeError("unexpected answer")
        total = data.get("allResultCount") if isinstance(data.get("allResultCount"), int) else None
        more = bool(docs) and (total is None or page * PAGE_SIZE < total)
        return [_doc_to_row(d) for d in docs if isinstance(d, dict)], total, more

    c.run(fetch, sleep=sleep, pause=PAUSE_SECONDS, max_pages=MAX_PAGES)
    return c.rows, c.health()
