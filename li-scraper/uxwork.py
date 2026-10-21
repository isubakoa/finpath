"""
uxwork.nl/en/jobs — a Netherlands-specific UX/product-design job board.
Like welcome-to-nl.nl (see welcome_to_nl.py's module docstring), the
public page itself ships no listings in its static HTML (confirmed by
Isu: View Page Source showed no job titles) — it's a client-rendered
page that calls its own backend. Confirmed 2026-10-20 the same way as
welcome-to-nl.nl: DevTools -> Network -> Fetch/XHR on the live page shows
a plain GET to

    https://uxwork.nl/search.php?<filters>

returning a flat JSON array directly — no auth header, no wrapping
envelope, just title/company/location/url/date per posting. Simpler than
welcome-to-nl.nl in every way: no API key needed, and critically each
posting's own `url` is a STABLE PERMALINK ON UXWORK.NL ITSELF (e.g.
"https://uxwork.nl/en/job/senioruxuidesigner-learnwiseai_4034/"), not a
redirect or tracking link — the best-case URL-identity shape for
scrape.py's build_fresh_roles(), same as a direct ATS/company-board
scrape.

Unlike welcome-to-nl.nl's "rvo" engine (a broad, general-purpose portal
that needs our own title filtering), uxwork.nl is ALREADY a dedicated
UX/product-design board — the whole site's entire purpose. The query
string Isu captured from the live page (filt_set_exp=SR,LE&
filt_set_jobtype=Fulltime&filt_set_rolet=Banen&filt_set_distance=20&
filt_set_company=Alle&filt_set_lan=Engels&filt_set_dat=Alle&sort=datum_new&
page=jobsearch&lang=en) reflects whatever filter chips happened to be
active in his browser session (English/Senior/Lead/Full-time, per his
screenshot) — notably there's no filt_set_discipline-type param at all,
meaning the unfiltered default already spans every discipline (Product
Design, UX/UI Design, UX Research, Service Design, etc. all showed up
together in the same raw response Isu pasted back). DEFAULT_PARAMS below
deliberately drops the experience/jobtype restrictions he had active
(filt_set_exp, filt_set_jobtype) to search broadly, matching how every
other source in this project searches (not scoped to one seniority band
or employment type) — see scrape.py's run_uxwork_searches() docstring for
why this module takes no `terms` argument at all, unlike every other
source.

Still genuinely unverified (flagged here rather than guessed at — see
PAGE_SIZE_WARNING_THRESHOLD below): whether this one GET actually returns
every currently-open posting in a single response, or whether the site
silently caps/paginates it (the UI badge read "Jobs 259" when Isu
captured this; nothing in the captured request showed a page-number or
offset parameter, which is itself a hint this might be all-at-once, but
that's an inference, not a confirmed fact). First real run against this
should log how many rows came back and compare against what the site's
own "Jobs N" count says, so a silent cap is obvious immediately rather
than discovered as a mysteriously-small open-market Netherlands count
weeks later.
"""
import re
import sys
from datetime import datetime, timedelta, timezone

import requests

SEARCH_URL = "https://uxwork.nl/search.php"

# 2026-10-20 — deliberately broad: no filt_set_exp/filt_set_jobtype
# restriction (Isu's own live session had Senior/Lead/Full-time chips
# active when he captured this; those were HIS filter state, not a
# requirement of the endpoint — see module docstring). filt_set_lan=Engels
# (English-speaking roles only) is kept on purpose: this whole project is
# about English-speaking NL opportunities, matching uxwork.nl's own stated
# purpose and the other two NL-expat-focused sites evaluated alongside it.
DEFAULT_PARAMS = {
    "filt_set_exp": "Alle",
    "filt_set_jobtype": "Alle",
    "filt_set_rolet": "Banen",  # "Jobs" (Dutch) — as opposed to the site's separate Internships/Courses/Events sections
    "filt_set_distance": "20",
    "filt_set_company": "Alle",
    "filt_set_lan": "Engels",
    "filt_set_dat": "Alle",
    "sort": "datum_new",
    "page": "jobsearch",
    "lang": "en",
}

PAGE_SIZE_WARNING_THRESHOLD = 50  # see module docstring's unverified-pagination note
REQUEST_TIMEOUT_SECONDS = 20

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

_SVG_TAG_RE = re.compile(r"<svg\b.*?</svg>", re.IGNORECASE | re.DOTALL)
# "4d", "12h", "2w", "3mo" — the site's own relative-age shorthand (see the
# "new" field in a real captured response). Deliberately conservative: only
# handles the unit letters actually observed (d/h/w/mo) plus the two literal
# words seen in similar Dutch job-board UIs ("today"/"new"); anything else
# falls through to None rather than guessing, exactly like a JobSpy row with
# an unparseable date already does (see scrape.py's normalize_posted_date()).
_RELATIVE_AGE_RE = re.compile(r"^\s*(\d+)\s*(mo|d|h|w)\s*$", re.IGNORECASE)


def _location_from_intro(intro):
    """The site's `intro` field is a location-pin SVG followed by the
    location text itself (e.g. '<svg ...>...</svg> Amsterdam') — confirmed
    against a real captured response. Strips the SVG markup and returns
    whatever text is left, trimmed."""
    if not intro:
        return ""
    return _SVG_TAG_RE.sub("", intro).strip()


def _relative_age_to_iso(value):
    """Best-effort parse of the site's own relative-age shorthand ('4d',
    '12h', ...) down to an ISO 'YYYY-MM-DD' date, or None when it doesn't
    match a known shape — see _RELATIVE_AGE_RE's own comment. None is a
    completely normal, already-handled outcome everywhere downstream (a
    role with no confirmed postedDate just relies on firstSeenAt/the 24h
    window instead, same as a LinkedIn-only row with no date today)."""
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
    """uxwork.nl's search.php mixes paid placements into the same array as
    real postings (confirmed: a captured response included an "Intro to
    Vibe Coding" course ad from an unrelated company, marked this way) —
    these aren't jobs at all and must never reach build_fresh_roles()."""
    if item.get("promoted") or item.get("ad"):
        return True
    sec_text = str(item.get("sec_text") or "")
    return "sponsored" in sec_text.lower()


def _item_to_row(item):
    """Turns one raw uxwork.nl search.php item into a JobSpy-row-shaped
    dict — job_url/company/title/location/date_posted/description, the
    exact fields scrape.py's build_fresh_roles() reads. Returns None for a
    sponsored placement (see _is_sponsored()), a closed listing, or one
    missing a title/url (build_fresh_roles() would drop an empty job_url
    anyway; no reason to hand it a half-built row)."""
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
        # search.php returns no description field at all (title/company/
        # intro/sec_text/url/logo/promoted/closed/new/ad only) — every
        # downstream consumer already tolerates an empty one.
        "description": "",
    }


def scrape_uxwork(debug=False):
    """Yields ("uxwork", row) for every current, non-sponsored posting
    returned by one GET to search.php (see module docstring for the open
    question of whether that's genuinely everything or silently capped).
    No `terms` argument, unlike every other source — see module docstring
    for why DEFAULT_PARAMS already searches broadly across every design/UX
    discipline in one shot, so there's no per-term loop here at all. Same
    (source, row) yield shape as every other source
    (run_searches()/scrape_bayt()/scrape_welcome_to_nl()), so scrape.py's
    build_fresh_roles() needs no changes to consume this."""
    headers = {
        "Accept": "application/json",
        "Referer": "https://uxwork.nl/en/jobs/",
        "User-Agent": USER_AGENT,
    }
    try:
        resp = requests.get(SEARCH_URL, params=DEFAULT_PARAMS, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
        if resp.status_code >= 400:
            if debug:
                print(f"[uxwork] HTTP {resp.status_code}: {resp.text[:200]!r}", file=sys.stderr)
            return
        items = resp.json()
    except Exception as e:  # noqa: BLE001 — one bad call must not kill the run
        if debug:
            print(f"[uxwork] request failed: {type(e).__name__}: {e}", file=sys.stderr)
        return
    if not isinstance(items, list):
        if debug:
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
