"""
Jobsplus (jobsplus.gov.mt, Malta's employment agency), searched for QUERIES.
The vacancy list loads as an HTML fragment:

    GET https://jobsplus.gov.mt/Umbraco/Surface/Vacancy/GetVacancyListData
        ?industry=0&jobType=0&vacancyRef=&searchText=<q>&pageNumber=<n>

Each <li id="<vacancy id>"> has the title (h3, in capitals), the place
("TAS-SLIEMA, MALTA") and a short description; the page for it is
/vacancy/vacancy-details?id=<id>. Jobsplus only shows the company to signed-in
users, so the employer is COMPANY_HIDDEN (Isu's choice: show the role anyway).
"""
import re
import time

import requests
from bs4 import BeautifulSoup

from common import Collector, make_row, place, request, tidy_caps

SITE_URL = "https://jobsplus.gov.mt"
LIST_URL = SITE_URL + "/Umbraco/Surface/Vacancy/GetVacancyListData"
COMPANY_HIDDEN = "Company shown after Jobsplus sign-in"
QUERIES = ("product", "designer", "ux", "design")
PAGE_SIZE = 10
MAX_PAGES_PER_QUERY = 5
PAUSE_SECONDS = 0.5


def _item_to_row(item):
    vacancy_id = item.get("id", "")
    title = item.select_one("h3")
    pin = item.select_one(".fa-map-pin")
    where = tidy_caps(pin.parent.get_text(" ", strip=True)) if pin and pin.parent else ""
    city = where.split(",")[0].strip()
    texts = [p.get_text(" ", strip=True) for p in item.select("p")]
    description = next((t for t in texts if "log in" not in t.lower()), "")
    return make_row(f"{SITE_URL}/vacancy/vacancy-details?id={vacancy_id}" if vacancy_id.isdigit() else "",
                    COMPANY_HIDDEN, tidy_caps(title.get_text(" ", strip=True)) if title else "",
                    place("" if city.lower() == "malta" else city, "Malta"), None, description)


def read(http=requests, sleep=time.sleep, terms=()):
    c = Collector("jobsplus")
    for query in QUERIES:
        def fetch(page, query=query):
            fragment = request(http, "get", LIST_URL, expect="text",
                               params={"industry": 0, "jobType": 0, "vacancyRef": "", "searchText": query,
                                       "pageNumber": page},
                               headers={"Referer": SITE_URL + "/vacancy", "X-Requested-With": "XMLHttpRequest"})
            soup = BeautifulSoup(fragment, "html.parser")
            items = soup.select("ul.list-d > li[id]")
            count = re.search(r"(\d+)\s+Job\(s\)", soup.get_text(" ", strip=True))
            if page == 1 and not items and not count:
                raise RuntimeError("no vacancy list in the answer (changed or blocked)")
            total = int(count.group(1)) if count else None
            return [_item_to_row(i) for i in items], None, bool(items) and (total is None or page * PAGE_SIZE < total)
        c.run(fetch, sleep=sleep, pause=PAUSE_SECONDS, max_pages=MAX_PAGES_PER_QUERY, label=f"{query!r} ")
        sleep(PAUSE_SECONDS)
    return c.rows, c.health()
