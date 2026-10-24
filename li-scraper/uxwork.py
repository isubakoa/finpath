"""
uxwork.nl -- a Netherlands UX/product-design job board. The page is client-rendered
from https://uxwork.nl/search.php?<filters>, which returns a flat JSON array (no
auth) of about 21 items per page; `page` is the page number. Past the last page the
site repeats earlier results instead of returning [], so paging stops at the first
page that adds no new url. Each posting's `url` is a stable permalink on uxwork.nl.
The board is design-only already, so no per-term searches are needed.

Fixed 2026-10-24: the old request sent page=jobsearch plus "Alle" filter values,
which made search.php return [] -- uxwork contributed zero rows from day one.
"""
import re
import sys
from datetime import datetime, timedelta, timezone

import requests

SEARCH_URL = "https://uxwork.nl/search.php"

# English-language roles only (filt_set_lan=Engels, ~90 of ~240), matching the rest of
# this project. "Banen" = jobs, as opposed to internships/courses/events. Other
# filters are left unset: sending their "Alle" (all) values empties the response.
DEFAULT_PARAMS = {
    "filt_set_rolet": "Banen",
    "filt_set_lan": "Engels",
    "sort": "datum_new",
    "lang": "en",
}
MAX_PAGES = 40  # ~21 per page; a safety cap, the no-new-urls check normally ends first.

REQUEST_TIMEOUT_SECONDS = 20

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

_SVG_TAG_RE = re.compile(r"<svg\b.*?</svg>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
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
    # The "new" field is either a relative age or an HTML badge reading "New".
    s = _TAG_RE.sub("", str(value)).strip().lower()
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
    """Yields ("uxwork", row) for every current, non-sponsored posting, paging
        search.php until a page adds no new url.
    """
    headers = {
        "Accept": "application/json",
        "Referer": "https://uxwork.nl/en/jobs/",
        "User-Agent": USER_AGENT,
    }
    seen_urls = set()
    kept = 0
    for page in range(1, MAX_PAGES + 1):
        try:
            resp = requests.get(SEARCH_URL, params={**DEFAULT_PARAMS, "page": str(page)},
                                headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
            if resp.status_code >= 400:
                print(f"[uxwork] page {page}: HTTP {resp.status_code}: {resp.text[:200]!r}", file=sys.stderr)
                break
            items = resp.json()
        except Exception as e:  # noqa: BLE001 — one bad call must not kill the run
            print(f"[uxwork] page {page}: request failed: {type(e).__name__}: {e}", file=sys.stderr)
            break
        if not isinstance(items, list):
            print(f"[uxwork] page {page}: unexpected response shape: {type(items).__name__}", file=sys.stderr)
            break
        added = 0
        for item in items:
            row = _item_to_row(item)
            if row is None or row["job_url"] in seen_urls:
                continue
            seen_urls.add(row["job_url"])
            added += 1
            yield ("uxwork", row)
        kept += added
        if not added:
            break
    if kept == 0:
        print("[uxwork] 0 rows -- search.php may have changed (see uxwork.py docstring)", file=sys.stderr)
    elif debug:
        print(f"[uxwork] {kept} rows from {page} page(s)", file=sys.stderr)
