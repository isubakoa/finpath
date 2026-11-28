import time

import requests

from common import Collector, iso_date, make_row, request

SEARCH_URL = "https://jobs.make-it-in-munich.com/jobs"
QUERIES = ("Product Manager", "Product Owner", "Product Designer", "UX", "Design Lead", "Head of Design")
PAGE_SIZE = 100
MAX_PAGES_PER_QUERY = 3
PAUSE_SECONDS = 0.5


def _job_to_row(job):
    postal = str(job.get("postal_code") or "")
    location = "Munich, Germany" if postal[:2] in ("80", "81") else "Bavaria, Germany"
    return make_row(job.get("url"), job.get("company_name"), job.get("job_title"), location,
                    iso_date(job.get("created_at")))


def read(http=requests, sleep=time.sleep, terms=()):
    c = Collector("makeitinmunich")
    for query in QUERIES:
        def fetch(page, query=query):
            data = request(http, "get", SEARCH_URL, params={"job_title": query, "limit": PAGE_SIZE, "page": page},
                           headers={"Origin": "https://www.make-it-in-munich.com",
                                    "Referer": "https://www.make-it-in-munich.com/"})
            jobs = data.get("jobs") if isinstance(data, dict) else None
            if not isinstance(jobs, list):
                raise RuntimeError("unexpected answer")
            pages = data.get("total_pages") if isinstance(data.get("total_pages"), int) else None
            return [_job_to_row(j) for j in jobs if isinstance(j, dict)], None, bool(jobs) and (pages is None or page < pages)
        c.run(fetch, sleep=sleep, pause=PAUSE_SECONDS, max_pages=MAX_PAGES_PER_QUERY, label=f"{query!r} ")
        sleep(PAUSE_SECONDS)
    return c.rows, c.health()
