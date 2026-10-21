"""
welcome-to-nl.nl/jobs — via its own backend, not scraped from the public
page itself. That page ships ZERO job listings in its static HTML — it's
a client-side search widget ("Showing 0 jobs" placeholders in the raw
markup) — confirmed 2026-10-20 by having Isu open DevTools -> Network ->
Fetch/XHR on the live page and read back the actual request it makes: a
POST straight to an Elastic App Search engine, at

    https://jobportal.ent.europe-west4.gcp.elastic-cloud.com/api/as/v1/engines/rvo/search

authenticated with a PUBLIC, read-only "search-" prefixed key (Elastic's
own naming convention for a key that's explicitly meant to be embedded in
client-side JS and exposed to anyone loading the page — not a credential
we're lifting; the same category as an Algolia public search-only key).
AUTH_HEADER below is that key, copied verbatim from the real request. If
it ever stops working (the site rotates it), re-capture it the same way:
load https://www.welcome-to-nl.nl/jobs/, DevTools -> Network -> Fetch/XHR,
reload the page, click the "search" request, and read its Authorization
request header.

The "rvo" engine itself is a broad, general-purpose Dutch jobs portal —
5,520 total results across every field as of this writing (verified via
the same DevTools session: a results[] array with real postings in every
industry, e.g. "Manager Finance Operations" and "Laser las operator" at
VDL Groep), NOT curated to design/UX at all. "rvo" most likely stands for
Rijksdienst voor Ondernemend Nederland (the Dutch government's enterprise
agency) — this reads like a shared portal backing several Netherlands
expat/talent programs, welcome-to-nl.nl being one of them. Eligibility
here is entirely scrape.py's own title-matching (is_role_relevant()/
open_market_gate(), exactly like every other source) — this module
deliberately does NOT try to use the engine's own `job_functions` facet to
narrow results server-side, because that facet is industry-sector-based
(real example value: "High-tech systems (nano- & microtech)"), not
role-based — there is nothing resembling a "Design"/"UX" category on it to
filter by.

Each result's own `url` field is the exact posting URL the employer
itself publishes to (e.g. werkenbijvdl.nl/vacature/...) — not a redirect
or tracking link — so these rows are just as stable, URL-identity-wise,
as a direct company-board scrape. No special-casing needed in
scrape.py's build_fresh_roles(), whose URL-keyed dedup already assumes
exactly this.

Plain requests/JSON, no browser needed — unlike Bayt (see
bayt_playwright.py), this engine's search API has no indication of
blocking non-browser clients; it's a public search endpoint by design.
"""
import sys
import time

import requests

SEARCH_URL = "https://jobportal.ent.europe-west4.gcp.elastic-cloud.com/api/as/v1/engines/rvo/search"
# 2026-10-20 — public, search-only App Search key; see module docstring.
AUTH_HEADER = "Bearer search-o21ix7ak2jiao92yvzceums2"
ORIGIN = "https://www.welcome-to-nl.nl"

PAGE_SIZE = 25
# 2026-10-20 — newest-first sort (see _search_page()'s payload) already
# surfaces exactly what a daily run cares about; no need to page through
# all ~300 pages per term for a 5,520-result general-purpose portal. Worth
# revisiting if a live run shows real relevant results getting missed
# because they're buried past page 2 for a given term — not expected, since
# a daily run only needs postings new since the last one, but not verified
# against real traffic volume yet.
MAX_PAGES_PER_TERM = 2
REQUEST_TIMEOUT_SECONDS = 20
PAUSE_BETWEEN_REQUESTS_SECONDS = 0.5

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)


def _search_page(term, page, debug=False):
    """One POST to the rvo engine for `term`, page `page` (1-based), sorted
    newest-first. Returns the raw `results` list, or [] on any failure —
    same per-call isolation as every other source in this project (one bad
    request for one term/page must never take the whole run down)."""
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
            if debug:
                print(f"[welcome-to-nl] {term!r} page {page}: HTTP {resp.status_code}: {resp.text[:200]!r}", file=sys.stderr)
            return []
        data = resp.json()
    except Exception as e:  # noqa: BLE001 — one bad call must not kill the run
        if debug:
            print(f"[welcome-to-nl] {term!r} page {page} failed: {type(e).__name__}: {e}", file=sys.stderr)
        return []
    return data.get("results") or []


def _raw(result, field):
    """Every field in an App Search result is wrapped as {"raw": ...} —
    this unwraps one, tolerating a missing/malformed field rather than
    raising (a dict.get chain, not result[field]["raw"])."""
    v = result.get(field)
    return v.get("raw") if isinstance(v, dict) else None


def _result_to_row(result):
    """Turns one raw rvo-engine result into a JobSpy-row-shaped dict — the
    exact fields scrape.py's build_fresh_roles() reads via row.get(...):
    job_url/company/title/location/date_posted/description. Returns None
    when title or url is missing (build_fresh_roles() would drop an empty
    job_url anyway; no reason to even hand it a half-built row)."""
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
        # "2026-10-19T18:17:53.000Z" -> "2026-10-19"; normalize_posted_date()
        # on scrape.py's side just re-trims this the same way, so handing it
        # an already-trimmed ISO date is harmless, not redundant-but-wrong.
        "date_posted": created_at[:10] if created_at else None,
        # Not returned by this search call (only title/company/location/
        # dates/etc. — no description field at all). Every downstream
        # consumer already tolerates an empty description (sponsorship_signal()
        # on "" -> [], exactly like a LinkedIn-only row today).
        "description": "",
    }


def scrape_welcome_to_nl(terms, debug=False):
    """Yields ("welcometonl", row) for every `terms` entry, newest
    MAX_PAGES_PER_TERM*PAGE_SIZE results per term — same per-term isolation
    and (source, row) yield shape as every other source in this project
    (run_searches()/scrape_bayt()), so scrape.py's build_fresh_roles()
    needs no changes at all to consume this."""
    for term in terms:
        if debug:
            print(f"[welcome-to-nl] searching: {term!r}", file=sys.stderr)
        for page in range(1, MAX_PAGES_PER_TERM + 1):
            results = _search_page(term, page, debug=debug)
            if not results:
                break  # no more results for this term (or the call failed) — stop paging it
            kept = 0
            for result in results:
                row = _result_to_row(result)
                if row is not None:
                    kept += 1
                    yield ("welcometonl", row)
            if debug:
                print(f"[welcome-to-nl] {term!r} page {page}: {kept}/{len(results)} rows", file=sys.stderr)
            time.sleep(PAUSE_BETWEEN_REQUESTS_SECONDS)
