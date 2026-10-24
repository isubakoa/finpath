"""
welcome-to-nl.nl jobs, via the site's own search backend (the public page
ships no listings in its HTML). The page POSTs to an Elastic App Search
engine ("rvo" -- a broad, general Dutch jobs portal, not design-specific):

    https://jobportal.ent.europe-west4.gcp.elastic-cloud.com/api/as/v1/engines/rvo/search

AUTH_HEADER is the site's public, read-only "search-" key -- Elastic's
convention for keys meant to be embedded in client JS. If it stops working,
re-capture it: open welcome-to-nl.nl/jobs, DevTools -> Network -> Fetch/XHR,
reload, and read the "search" request's Authorization header.

Relevance is left to scrape.py's title matching like every other source: the
engine's job_functions facet is industry-based, with no design/UX category.
Each result's `url` is the employer's own posting URL, so URL-based dedup
works as for a direct board. Plain JSON over HTTP, no browser needed.
"""
import sys
import time

import requests

SEARCH_URL = "https://jobportal.ent.europe-west4.gcp.elastic-cloud.com/api/as/v1/engines/rvo/search"
# Public, search-only App Search key -- see the module docstring.
AUTH_HEADER = "Bearer search-o21ix7ak2jiao92yvzceums2"
ORIGIN = "https://www.welcome-to-nl.nl"

PAGE_SIZE = 25
# Results are sorted newest first, and a scheduled run only needs what's new,
# so two pages per term is plenty for this general-purpose portal.
MAX_PAGES_PER_TERM = 2
REQUEST_TIMEOUT_SECONDS = 20
PAUSE_BETWEEN_REQUESTS_SECONDS = 0.5

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)


def _search_page(term, page, debug=False):
    """One POST for `term`, page `page` (1-based), newest first. Returns the raw
        `results` list, or [] on any failure so one call can't break the run.
    """
    body = {
        "query": term,
        "page": {"current": page, "size": PAGE_SIZE},
        "filters": {},
        "sort": [{"created_at": "desc"}],
    }
    headers = {
        "Authorization": AUTH_HEADER,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Origin": ORIGIN,
        "Referer": ORIGIN + "/jobs/",
        "User-Agent": USER_AGENT,
    }
    try:
        resp = requests.post(SEARCH_URL, json=body, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
        if resp.status_code >= 400:
            print(f"[welcome-to-nl] {term!r} page {page}: HTTP {resp.status_code}: {resp.text[:200]!r}", file=sys.stderr)
            return []
        data = resp.json()
    except Exception as e:  # noqa: BLE001 — one bad call must not kill the run
        print(f"[welcome-to-nl] {term!r} page {page} failed: {type(e).__name__}: {e}", file=sys.stderr)
        return []
    return data.get("results") or []


def _raw(result, field):
    """App Search wraps every field as {"raw": ...}; unwrap one, tolerating missing
        or malformed fields.
    """
    v = result.get(field)
    return v.get("raw") if isinstance(v, dict) else None


def _result_to_row(result):
    """One rvo result -> a JobSpy-shaped row. None when title or url is missing."""
    title = _raw(result, "title")
    url = _raw(result, "url")
    if not title or not url:
        return None
    locations = _raw(result, "locations") or []
    location = locations[0] if locations else ""
    created_at = _raw(result, "created_at") or ""
    return {
        "job_url": url,
        "company": _raw(result, "company_name") or "",
        "title": title,
        "location": location,
        # "2026-10-19T18:17:53.000Z" -> "2026-10-19"
        "date_posted": created_at[:10] if created_at else None,
        # This endpoint returns no description; downstream treats "" like LI rows.
        "description": "",
    }


def scrape_welcome_to_nl(terms, debug=False):
    """Yields ("welcometonl", row): newest MAX_PAGES_PER_TERM * PAGE_SIZE results
        per term, each term isolated from the others' failures.
    """
    for term in terms:
        if debug:
            print(f"[welcome-to-nl] searching: {term!r}", file=sys.stderr)
        for page in range(1, MAX_PAGES_PER_TERM + 1):
            results = _search_page(term, page, debug=debug)
            if not results:
                break  # No more results (or the call failed) -- stop paging this term.
            kept = 0
            for result in results:
                row = _result_to_row(result)
                if row is not None:
                    kept += 1
                    yield ("welcometonl", row)
            if debug:
                print(f"[welcome-to-nl] {term!r} page {page}: {kept}/{len(results)} rows", file=sys.stderr)
            time.sleep(PAUSE_BETWEEN_REQUESTS_SECONDS)
