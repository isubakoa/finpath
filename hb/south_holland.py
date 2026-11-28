import time

import requests

from common import Collector, epoch_date, make_row, request

SEARCH_URL = "https://api.getro.com/api/v2/collections/1535/search/jobs"
BOARD_URL = "https://jobs.workinsouthholland.nl"
QUERIES = ("product", "designer", "design", "ux")
PAGE_SIZE = 20
MAX_PAGES_PER_QUERY = 15
PAUSE_SECONDS = 0.5


def _job_to_row(job):
    org = job.get("organization") if isinstance(job.get("organization"), dict) else {}
    locations = [l for l in (job.get("locations") or []) if isinstance(l, str)]
    url = job.get("url") or (f"{BOARD_URL}/companies/{org.get('slug')}/jobs/{job.get('slug')}"
                             if org.get("slug") and job.get("slug") else "")
    return make_row(url, org.get("name"), job.get("title"), locations[0] if locations else "Netherlands",
                    epoch_date(job.get("created_at")))


def read(http=requests, sleep=time.sleep, terms=()):
    c = Collector("southholland")
    for query in QUERIES:
        def fetch(page, query=query):
            data = request(http, "post", SEARCH_URL, json={"hitsPerPage": PAGE_SIZE, "page": page - 1,
                                                          "filters": "", "query": query},
                           headers={"Origin": BOARD_URL, "Referer": BOARD_URL + "/jobs"})
            res = data.get("results", data) if isinstance(data, dict) else None
            jobs = res.get("jobs") if isinstance(res, dict) else None
            if not isinstance(jobs, list):
                raise RuntimeError("unexpected answer")
            count = res.get("count") if isinstance(res.get("count"), int) else 0
            return [_job_to_row(j) for j in jobs if isinstance(j, dict)], None, bool(jobs) and page * PAGE_SIZE < count
        c.run(fetch, sleep=sleep, pause=PAUSE_SECONDS, max_pages=MAX_PAGES_PER_QUERY, label=f"{query!r} ")
        sleep(PAUSE_SECONDS)
    return c.rows, c.health()
