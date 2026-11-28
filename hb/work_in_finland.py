"""
Work in Finland (workinfinland.com, Business Finland): English-language jobs
across Finland. The same feed Hire Helsinki reads for the Helsinki region,
here for the whole country:

    GET https://www.workinfinland.com/api/jobs/?limit=100&page=<n>

~1,170 jobs, 100 a page. Each has title, employer {name, city}, expireDate and
externalUrl; no posting date, so ProPath's first-seen date stands in. A role
both list is kept once (Hire Helsinki's comes first in registry.HUBS).
"""
import time

import requests

from common import Collector, make_row, place, request

FEED_URL = "https://www.workinfinland.com/api/jobs/"
REFERER = "https://www.workinfinland.com/"
PAGE_SIZE = 100
MAX_PAGES = 30
PAUSE_SECONDS = 1.0


def _job_to_row(job):
    employer = job.get("employer") if isinstance(job.get("employer"), dict) else {}
    return make_row(job.get("externalUrl"), employer.get("name"), job.get("title"),
                    place(employer.get("city"), "Finland"))


def read(http=requests, sleep=time.sleep, terms=()):
    c = Collector("workinfinland")

    def fetch(page):
        data = request(http, "get", FEED_URL, params={"limit": PAGE_SIZE, "page": page}, headers={"Referer": REFERER})
        jobs = data.get("jobs") if isinstance(data, dict) else None
        if not isinstance(jobs, list):
            raise RuntimeError("unexpected answer")
        pages = data.get("totalPages") if isinstance(data.get("totalPages"), int) else None
        rows = [_job_to_row(j) for j in jobs if isinstance(j, dict)]
        return rows, data.get("totalJobs"), bool(jobs) and (pages is None or page < pages)

    c.run(fetch, sleep=sleep, pause=PAUSE_SECONDS, max_pages=MAX_PAGES)
    return c.rows, c.health()
