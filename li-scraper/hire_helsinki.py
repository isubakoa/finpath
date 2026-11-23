"""
Hire Helsinki (myhelsinki.fi/hire-helsinki) jobs, via the feed its "Search all
open jobs in Helsinki" block reads (checked 2026-11-23):

    https://www.myhelsinki.fi/wp-json/mhb/v1/workinfinland/jobs
        ?limit=<=50&page=<n>&city=helsinki,espoo,vantaa   (also category=, query=)

Work in Finland's English-language jobs in the Helsinki region (648 on
2026-11-23, 13 pages of 50). Each job has title, employer {name, city},
expireDate and externalUrl (mostly tyomarkkinatori.fi, else the employer's own
board). There's no posting date, so ZenPath's first-seen date stands in.

The whole feed is read every run and relevance is left to scrape.py's title
matching like every other source. Finland is accepted for these postings but
not searched on LI or Indeed (scrape.py EXTRA_MARKETS). The site is behind
Cloudflare; a refused or failed page is reported in the health dict (shown in
Settings › Job sites) and never breaks the run.
"""
import html
import sys
import time

import requests

FEED_URL = "https://www.myhelsinki.fi/wp-json/mhb/v1/workinfinland/jobs"
REFERER = "https://www.myhelsinki.fi/hire-helsinki/"
CITIES = "helsinki,espoo,vantaa"
PAGE_SIZE = 50  # the feed's maximum
MAX_PAGES = 30  # safety cap (~1,500 jobs)
REQUEST_TIMEOUT_SECONDS = 20
PAUSE_BETWEEN_REQUESTS_SECONDS = 1.0

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)


def _get_page(page, get):
    """One page of the feed as parsed JSON. Raises on HTTP errors or a non-JSON
        answer (e.g. a Cloudflare challenge page).
    """
    resp = get(
        FEED_URL,
        params={"limit": PAGE_SIZE, "page": page, "city": CITIES},
        headers={"Accept": "application/json", "Referer": REFERER, "User-Agent": USER_AGENT},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}")
    try:
        return resp.json()
    except ValueError:
        raise RuntimeError("not JSON (blocked or changed)") from None


def _job_to_row(job):
    """One feed job -> a JobSpy-shaped row, or None without a title or link."""
    title = html.unescape(str(job.get("title") or "")).strip()
    url = str(job.get("externalUrl") or "").strip()
    if not title or not url.startswith("http"):
        return None
    employer = job.get("employer") if isinstance(job.get("employer"), dict) else {}
    city = str(employer.get("city") or "").strip()
    return {
        "job_url": url,
        "company": html.unescape(str(employer.get("name") or "")).strip(),
        "title": title,
        "location": f"{city}, Finland" if city else "Finland",
        "date_posted": None,
        "description": "",
    }


def scrape_hire_helsinki(debug=False, get=None, sleep=time.sleep):
    """Returns (rows as ("hirehelsinki", row), health). health: {"rows", "pages",
        "total", "error"}; error is None when every page was read.
    """
    get = get or requests.get
    rows, seen, pages, total, error = [], set(), 0, None, None
    page = 1
    while page <= MAX_PAGES:
        try:
            data = _get_page(page, get)
        except Exception as e:  # noqa: BLE001 -- one bad call must not kill the run
            error = f"page {page}: {e}"
            print(f"[hire-helsinki] {error}", file=sys.stderr)
            break
        pages += 1
        jobs = data.get("jobs") if isinstance(data, dict) else None
        if not isinstance(jobs, list):
            error = f"page {page}: unexpected answer"
            break
        if total is None and isinstance(data.get("totalJobs"), int):
            total = data["totalJobs"]
        for job in jobs:
            row = _job_to_row(job) if isinstance(job, dict) else None
            if row and row["job_url"] not in seen:
                seen.add(row["job_url"])
                rows.append(("hirehelsinki", row))
        total_pages = data.get("totalPages") if isinstance(data.get("totalPages"), int) else None
        if not jobs or (total_pages is not None and page >= total_pages):
            break
        page += 1
        sleep(PAUSE_BETWEEN_REQUESTS_SECONDS)
    if debug:
        print(f"[hire-helsinki] {len(rows)} jobs from {pages} page(s), feed total {total}", file=sys.stderr)
    return rows, {"rows": len(rows), "pages": pages, "total": total, "error": error}
