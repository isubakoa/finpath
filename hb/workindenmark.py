"""
Workindenmark (workindenmark.jobnet.dk/find-job), the Danish employment
service's board for English-language jobs, ~2,400. The page reads:

    GET https://workindenmark.jobnet.dk/bff/FindJob/Search?resultsPerPage=100
        &pageNumber=<n>&orderType=PublicationDate&kmRadius=50&searchString=
    header x-csrf: 1   (the site's anti-forgery marker; without it: 401)
    -> {"jobAds": [...], "totalJobAdCount": n}

Each ad has title, hiringOrgName, municipality, publicationDate, description
and jobAdUrl (the employer's own ad). About half are Jobnet's own ads with no
jobAdUrl; those link to Jobnet's page for the ad.
"""
import time

import requests

from common import Collector, iso_date, make_row, place, request

SEARCH_URL = "https://workindenmark.jobnet.dk/bff/FindJob/Search"
SITE_URL = "https://workindenmark.jobnet.dk"
PAGE_SIZE = 100
MAX_PAGES = 40
PAUSE_SECONDS = 0.5


def _ad_to_row(ad):
    url = ad.get("jobAdUrl") or (f"{SITE_URL}/find-job/{ad['jobAdId']}" if ad.get("jobAdId") else "")
    description = ad.get("description")
    return make_row(url, ad.get("hiringOrgName"), ad.get("title"), place(ad.get("municipality"), "Denmark"),
                    iso_date(ad.get("publicationDate")), description if isinstance(description, str) else "")


def read(http=requests, sleep=time.sleep, terms=()):
    c = Collector("workindenmark")

    def fetch(page):
        params = {"resultsPerPage": PAGE_SIZE, "pageNumber": page, "orderType": "PublicationDate",
                  "kmRadius": 50, "searchString": ""}
        data = request(http, "get", SEARCH_URL, params=params,
                       headers={"x-csrf": "1", "Referer": SITE_URL + "/find-job"})
        ads = data.get("jobAds") if isinstance(data, dict) else None
        if not isinstance(ads, list):
            raise RuntimeError("unexpected answer")
        total = data.get("totalJobAdCount") if isinstance(data.get("totalJobAdCount"), int) else None
        more = bool(ads) and (total is None or page * PAGE_SIZE < total)
        return [_ad_to_row(a) for a in ads if isinstance(a, dict)], total, more

    c.run(fetch, sleep=sleep, pause=PAUSE_SECONDS, max_pages=MAX_PAGES)
    return c.rows, c.health()
