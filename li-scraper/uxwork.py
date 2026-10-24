"""
uxwork.nl -- a Netherlands UX/product-design job board. The public page is
client-rendered; it calls

    https://uxwork.nl/search.php?<filters>

which returns a flat JSON array (no auth). Each posting's `url` is a stable
permalink on uxwork.nl itself. The board is design-only already, so one
broad call replaces the per-term searches other sources need (no `terms`
argument).

Unverified: whether that one call returns every open posting or is silently
capped (the site showed "Jobs 259" when captured; the request had no paging
parameter). In --debug runs, a response of PAGE_SIZE_WARNING_THRESHOLD rows
or fewer prints a warning.
"""
import re
import sys
from datetime import datetime, timedelta, timezone

import requests

SEARCH_URL = "https://uxwork.nl/search.php"

# Deliberately broad: no experience/job-type filters. English-language roles
# only (filt_set_lan=Engels), matching the rest of this project.
DEFAULT_PARAMS = {
    "filt_set_exp": "Alle",
    "filt_set_jobtype": "Alle",
    "filt_set_rolet": "Banen",  # "Banen" = jobs, as opposed to the site's internships/courses/events.
    "filt_set_distance": "20",
    "filt_set_company": "Alle",
    "filt_set_lan": "Engels",
    "filt_set_dat": "Alle",
    "sort": "datum_new",
    "page": "jobsearch",
    "lang": "en",
}

PAGE_SIZE_WARNING_THRESHOLD = 50  # See the module docstring's note on possible capping.
REQUEST_TIMEOUT_SECONDS = 20

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

_SVG_TAG_RE = re.compile(r"<svg\b.*?</svg>", re.IGNORECASE | re.DOTALL)
# The site's relative ages: "4d", "12h", "2w", "3mo", plus "today"/"new".
# Anything else -> None rather than a guess.
_RELATIVE_AGE_RE = re.compile(r"^\s*(\d+)\s*(mo|d|h|w)\s*$", re.IGNORECASE)


def _location_from_intro(intro):
    """`intro` is a location-pin SVG followed by the location text; return the text."""
    if not intro:
        return ""
    return _SVG_TAG_RE.sub("", intro).strip()


def _relative_age_to_iso(value):
    """Relative age ('4d', '12h', ...) -> 'YYYY-MM-DD', or None if unrecognised
        (an undated role just relies on first-seen time downstream).
    """
    if not value:
        return None
    s = str(value).strip().lower()
    if s in ("today", "new"):
        return datetime.now(timezone.utc).date().isoformat()
    if s == "yesterday":
        return (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat()
    m = _RELATIVE_AGE_RE.match(s)
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2)
    days = {"h": 0, "d": n, "w": n * 7, "mo": n * 30}.get(unit)
    if days is None:
        return None
    return (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()


def _is_sponsored(item):
    """Paid placements (courses, ads) are mixed into the results; they aren't jobs."""
    if item.get("promoted") or item.get("ad"):
        return True
    sec_text = str(item.get("sec_text") or "")
    return "sponsored" in sec_text.lower()


def _item_to_row(item):
    """One search.php item -> a JobSpy-shaped row. None for sponsored, closed,
        or title/url-less items.
    """
    if _is_sponsored(item) or item.get("closed"):
        return None
    title = item.get("titel")
    url = item.get("url")
    if not title or not url:
        return None
    return {
        "job_url": url,
        "company": item.get("bedrijfsnaam") or "",
        "title": title,
        "location": _location_from_intro(item.get("intro")),
        "date_posted": _relative_age_to_iso(item.get("new")),
        # search.php returns no description; downstream treats "" like LI rows.
        "description": "",
    }


def scrape_uxwork(debug=False):
    """Yields ("uxwork", row) for every current, non-sponsored posting from one
        GET to search.php.
    """
    headers = {
        "Accept": "application/json",
        "Referer": "https://uxwork.nl/en/jobs/",
        "User-Agent": USER_AGENT,
    }
    try:
        resp = requests.get(SEARCH_URL, params=DEFAULT_PARAMS, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
        if resp.status_code >= 400:
            print(f"[uxwork] HTTP {resp.status_code}: {resp.text[:200]!r}", file=sys.stderr)
            return
        items = resp.json()
    except Exception as e:  # noqa: BLE001 — one bad call must not kill the run
        print(f"[uxwork] request failed: {type(e).__name__}: {e}", file=sys.stderr)
        return
    if not isinstance(items, list):
        print(f"[uxwork] unexpected response shape: {type(items).__name__}", file=sys.stderr)
        return

    if debug and len(items) <= PAGE_SIZE_WARNING_THRESHOLD:
        print(
            f"[uxwork] only {len(items)} rows came back from one call — if the site's own "
            f"'Jobs N' badge reads meaningfully higher than this, search.php is paginating and "
            f"this module needs a real page/offset parameter added (see module docstring)",
            file=sys.stderr,
        )

    kept = 0
    for item in items:
        row = _item_to_row(item)
        if row is not None:
            kept += 1
            yield ("uxwork", row)
    if debug:
        print(f"[uxwork] {kept}/{len(items)} rows kept (sponsored/closed/malformed dropped)", file=sys.stderr)
