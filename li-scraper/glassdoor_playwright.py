"""
Glassdoor scraper via Playwright (real headless Chromium), replacing
JobSpy's Glassdoor integration — same story as bayt_playwright.py: JobSpy's
requests-based Glassdoor adapter gets a 400/403 ("location not parsed") on
every real request (see scrape.py's module docstring, "GLASSDOOR: NOW VIA
PLAYWRIGHT"), and the same maintainer guidance from a JobSpy GitHub issue
about this class of block (Google/ZipRecruiter/Glassdoor/Bayt) says it
needs a real JS-executing browser, not a header or proxy tweak.

Verified 2026-09-24, same process as bayt_playwright.py: loaded Glassdoor's
real site in a live browser and drove its own search form and internal
endpoints directly, rather than guessing. Unlike Google (see scrape.py's
"GOOGLE: RETIRED" section), Glassdoor does NOT bot-block a real browser —
a real Chromium request got a normal, fully-rendered results page on the
first try, no stealth tricks needed.

LOCATION RESOLUTION — the one genuinely fragile part, handled carefully.
Glassdoor's search URL needs a numeric location id plus a one-letter type
("N" = nation/country, "S" = state/region, "C" = city). Guessing these by
hand is dangerous: an earlier hand-guessed id, before this endpoint was
used, silently resolved to a COMPLETELY wrong place (a small town in
Vietnam; separately, Antarctica's South Georgia Islands) with a fully
valid-looking, normally-rendered results page — no error, no warning,
nothing to signal the location was wrong. To avoid that failure mode
entirely, every location is resolved LIVE via Glassdoor's own same-origin
autocomplete endpoint instead of any hardcoded id:

    GET /autocomplete/location?locationTypeFilters=CITY,STATE,COUNTRY&caller=jobs&term={location}

— called via `fetch()` from inside an already-loaded glassdoor.com page
(so it's same-origin, no separate HTTP client/cookies/headers to manage).
This returns several candidates; _resolve_location() below picks the one
whose `locationName` is an EXACT case-insensitive match for the query,
preferring type "N" over type "S" when both exist (Singapore and Hong Kong
each have both an N-type "the whole territory" entry and a C-type "just
the named city" entry sharing the identical name — N is what a bare
LOCATIONS country entry should mean; verified against real API responses
for all of GLASSDOOR_COUNTRY's current keys). If nothing matches exactly,
that location is skipped for this run (logged, not guessed) — a location
this file has never successfully resolved simply contributes zero rows
that run, rather than silently scraping the wrong place. A "C" (city) type
match is deliberately not used as a fallback of its own: none of
GLASSDOOR_COUNTRY's current keys need it (all resolve via N or S), and
there's no reason to add an unverified third case for zero real benefit.

SEARCH URL — verified as a plain query string, not Glassdoor's own
"SEO-friendly" URL scheme:

    https://www.glassdoor.com/Job/jobs.htm?sc.keyword={term}&locT={N|S}&locId={id}

Glassdoor's alternative URL form (e.g.
`/Job/singapore-product-manager-jobs-SRCH_IL.0,9_IN217_KO10,25.htm`) embeds
the search keyword as a character-offset range into the URL's own slug
text — self-referential and easy to get subtly wrong for a term with
unusual punctuation (e.g. "Senior UX/UI Designer"), which would silently
search for a truncated or shifted term with no error, the same class of
risk as a guessed location id. The plain query-string form above was
verified directly against exactly that term (real, on-topic "Senior UX/UI
Designer" results in Singapore came back) and is used exclusively here.

DOM shape (verified against real, live Glassdoor results pages 2026-09-24
— re-verify if Glassdoor redesigns):
  - Each result is an <li data-test="jobListing">.
  - Title + URL: li.querySelector('[data-test="job-title"]') — its own
    text is the title; `href` is already a complete, absolute job-listing
    URL (unlike Bayt, no origin-prepending needed).
  - Company: no data-test attribute exists for this field (checked). The
    only selector available is a CSS-module class,
    "EmployerProfile_compactEmployerName__<hash>" — the hash suffix is a
    build artifact that will change on a Glassdoor frontend redeploy, so
    this matches by SUBSTRING (className contains
    "EmployerProfile_compactEmployerName") rather than an exact class
    name — more redeploy-resistant than an exact match, though still
    worth re-verifying periodically since even the semantic prefix could
    change.
  - Location: li.querySelector('[data-test="emp-location"]') — the job's
    own, often more specific, location (e.g. "Bukit Merah Estate" for a
    Singapore search) — used as-is, same convention as Bayt's row shape.
  - Posted age: li.querySelector('[data-test="job-age"]') — relative text
    ONLY ("3d", "18d", "30d+"), not a precise timestamp the way Bayt's
    data-automation-jobactivedate attribute was — see
    _relative_age_to_iso() for how this becomes an approximate ISO date,
    day-level precision at best (Glassdoor's own "30d+" is already an
    approximation, not just this parser's).
  - Description snippet: li.querySelector('[data-test="descSnippet"]') —
    a real (if short) excerpt of the actual posting, enough for
    scrape.py's sponsorship_signal() keyword scan.

Only page 1 per (term, location) combo is fetched (Glassdoor's own
~30-per-page default) — no "next page"/"load more" control was found on
the results page during verification; same page-1-only scope decision as
bayt_playwright.py, for the same bounded-cost reasoning.
"""

import re
import sys
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

GLASSDOOR_ORIGIN = "https://www.glassdoor.com"
PAGE_TIMEOUT_MS = 30000

# Same real desktop Chrome UA used throughout this project's Playwright
# work (bayt_playwright.py, the diagnose_google_bayt.py diagnostic) —
# deliberately just an ordinary browser fingerprint, not JobSpy's default.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

# Only these two type codes are ever produced by _resolve_location() below
# (see the module docstring for why "C" is deliberately not supported).
_VALID_LOCATION_TYPES = ("N", "S")

_AGE_RE = re.compile(r"(\d+)\s*(h|d|mo)\b", re.IGNORECASE)

_RESOLVE_LOCATION_JS = """
async (term) => {
  const url = '/autocomplete/location?locationTypeFilters=CITY,STATE,COUNTRY&caller=jobs&term=' + encodeURIComponent(term);
  const res = await fetch(url, { headers: { Accept: 'application/json' } });
  if (!res.ok) return [];
  try {
    return await res.json();
  } catch (e) {
    return [];
  }
}
"""

_EXTRACT_JS = """
() => {
  const cards = Array.from(document.querySelectorAll('li[data-test="jobListing"]'));
  return cards.map(li => {
    const a = li.querySelector('[data-test="job-title"]');
    const companyEl = Array.from(li.querySelectorAll('*')).find(
      el => (el.className || '').toString().includes('EmployerProfile_compactEmployerName')
    );
    const locEl = li.querySelector('[data-test="emp-location"]');
    const ageEl = li.querySelector('[data-test="job-age"]');
    const descEl = li.querySelector('[data-test="descSnippet"]');
    return {
      title: a ? a.textContent.trim() : null,
      href: a ? a.getAttribute('href') : null,
      company: companyEl ? companyEl.textContent.trim() : null,
      location: locEl ? locEl.textContent.trim() : null,
      age: ageEl ? ageEl.textContent.trim() : null,
      description: descEl ? descEl.textContent.trim() : null,
    };
  });
}
"""


def _relative_age_to_iso(age_text, now=None):
    """Converts Glassdoor's relative posted-age text ("3d", "18d", "30d+",
    presumably "Xh" for same-day postings) to an approximate ISO date —
    day-level precision at best. "Just posted"/"today"/anything with no
    parseable number is treated as today. Returns None for genuinely
    unparseable input rather than guessing — same fail-safe-not-
    fail-silent approach used throughout this file."""
    if now is None:
        now = datetime.now(timezone.utc)
    if not age_text:
        return None
    text = age_text.strip().lower()
    if not text:
        return None
    if "just" in text or text in ("today", "new"):
        return now.date().isoformat()
    m = _AGE_RE.search(text)
    if not m:
        return None
    amount, unit = int(m.group(1)), m.group(2)
    if unit == "h":
        delta = timedelta(hours=amount)
    elif unit == "d":
        delta = timedelta(days=amount)
    elif unit == "mo":
        delta = timedelta(days=amount * 30)  # approximate — Glassdoor's own unit is already coarse
    else:
        return None
    return (now - delta).date().isoformat()


def _normalize_job_url(href):
    """Glassdoor auto-redirects to a regional TLD based on apparent
    geography (glassdoor.sg, glassdoor.co.uk, ...) — normalizes whatever
    TLD a given run happened to load under back to glassdoor.com, so every
    stored job_url looks consistent regardless of which locale actually
    served the request."""
    return re.sub(r"^https://www\.glassdoor\.[a-z.]+/", GLASSDOOR_ORIGIN + "/", href)


def _resolve_location(page, location_name, debug=False):
    """Calls Glassdoor's own /autocomplete/location endpoint (same-origin
    fetch from inside `page`) to resolve `location_name` to a real
    (location_type, location_id) pair — see the module docstring for the
    exact-match-only, N-preferred-over-S selection rule and why. Returns
    (None, None) if nothing matches exactly."""
    try:
        candidates = page.evaluate(_RESOLVE_LOCATION_JS, location_name)
    except Exception as e:  # noqa: BLE001 — one bad lookup must not kill the whole run
        if debug:
            print(f"[glassdoor] location lookup failed for {location_name!r}: {type(e).__name__}: {e}", file=sys.stderr)
        return None, None

    exact = [
        c for c in (candidates or [])
        if (c.get("locationName") or "").strip().lower() == location_name.strip().lower()
    ]
    for preferred_type in _VALID_LOCATION_TYPES:  # ("N", "S") — N first
        for c in exact:
            if c.get("locationType") == preferred_type:
                loc_id = c.get("locationId") or c.get("id")
                if loc_id:
                    return preferred_type, loc_id
    if debug:
        print(f"[glassdoor] no exact N/S location match for {location_name!r} — skipping this run", file=sys.stderr)
    return None, None


def _build_search_url(term, loc_type, loc_id):
    # safe="" — quote()'s default leaves "/" unescaped (its default `safe`
    # is "/"), but a term like "Senior UX/UI Designer" needs that slash
    # percent-encoded too (verified directly against the real site: a
    # browser's encodeURIComponent() escapes it to %2F, and that's the
    # exact request that returned correct results in testing). Caught by
    # test_glassdoor_playwright.py before this ever shipped — an
    # unescaped "/" would have silently changed what the URL's path
    # segments mean, not just how the keyword displays.
    return f"{GLASSDOOR_ORIGIN}/Job/jobs.htm?sc.keyword={quote(term, safe='')}&locT={loc_type}&locId={loc_id}"


def _cards_to_rows(raw_cards):
    """Turns the raw extracted card dicts into JobSpy-row-shaped dicts —
    the exact fields scrape.py's build_fresh_roles() reads via row.get(...):
    job_url/company/title/location/date_posted/description. A card missing
    a title or href is dropped outright."""
    rows = []
    for card in raw_cards:
        if not card.get("href") or not card.get("title"):
            continue
        rows.append({
            "job_url": _normalize_job_url(card["href"]),
            "company": card.get("company") or "",
            "title": card["title"],
            "location": card.get("location") or "",
            "date_posted": _relative_age_to_iso(card.get("age")),
            "description": card.get("description") or "",
        })
    return rows


def scrape_glassdoor_combo(browser, term, loc_type, loc_id, debug=False):
    """Loads page 1 of Glassdoor's search results for one (term, location)
    combo — location already resolved to (loc_type, loc_id) by the caller
    — in a fresh page/tab on the given (already-launched) Playwright
    browser, and returns a list of JobSpy-row-shaped dicts. Returns [] on
    any failure — a bad HTTP status, no results, a timeout, anything else
    — rather than raising, so one combo's failure can never take the whole
    Glassdoor run down (the same per-combo isolation every other site
    already has in scrape.py's run_searches())."""
    url = _build_search_url(term, loc_type, loc_id)
    page = browser.new_page(user_agent=USER_AGENT)
    try:
        response = page.goto(url, timeout=PAGE_TIMEOUT_MS, wait_until="domcontentloaded")
        if response is not None and response.status >= 400:
            if debug:
                print(f"[glassdoor] {term!r}: HTTP {response.status}", file=sys.stderr)
            return []
        try:
            page.wait_for_selector('li[data-test="jobListing"]', timeout=PAGE_TIMEOUT_MS)
        except Exception:
            if debug:
                print(f"[glassdoor] {term!r}: no results (or didn't render in time)", file=sys.stderr)
            return []
        raw_cards = page.evaluate(_EXTRACT_JS)
    except Exception as e:  # noqa: BLE001 — one combo's failure must not kill the run
        if debug:
            print(f"[glassdoor] {term!r} failed: {type(e).__name__}: {e}", file=sys.stderr)
        return []
    finally:
        page.close()

    rows = _cards_to_rows(raw_cards)
    if debug:
        print(f"[glassdoor] {term!r}: {len(rows)} rows", file=sys.stderr)
    return rows


def scrape_glassdoor(combos, debug=False):
    """Launches one headless Chromium browser and scrapes page 1 of every
    (term, location) combo in `combos`. `combos` is expected to already be
    filtered to Glassdoor-eligible locations by the caller (scrape.py's
    run_glassdoor_playwright_searches() does this against its own
    GLASSDOOR_COUNTRY dict before calling here) — this module deliberately
    knows nothing about scrape.py or GLASSDOOR_COUNTRY, so it has no
    dependency on scrape.py and stays independently testable, the same
    clean separation bayt_playwright.py has. Each distinct location among
    `combos` is resolved to a real Glassdoor location id/type ONCE up front
    and cached (there are far fewer distinct locations than there are
    combos referencing them), using one throwaway page navigated to
    Glassdoor's homepage first (needed so the same-origin
    /autocomplete/location fetch has something to be same-origin WITH).
    Yields ("glassdoor", row) tuples — exactly the shape run_searches()
    already yields, so scrape.py's build_fresh_roles() needs no changes to
    consume this.

    Imports playwright lazily (only inside this function) — same reasoning
    as bayt_playwright.py's scrape_bayt(): so match.py/test_match.py/
    test_rotation.py, and this module's own unit tests, stay importable
    without the playwright package installed at all."""
    from playwright.sync_api import sync_playwright

    eligible_combos = list(combos)
    if not eligible_combos:
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            location_cache = {}
            resolver_page = browser.new_page(user_agent=USER_AGENT)
            try:
                resolver_page.goto(f"{GLASSDOOR_ORIGIN}/", timeout=PAGE_TIMEOUT_MS, wait_until="domcontentloaded")
                for _, location in eligible_combos:
                    if location in location_cache:
                        continue
                    location_cache[location] = _resolve_location(resolver_page, location, debug=debug)
            finally:
                resolver_page.close()

            for term, location in eligible_combos:
                loc_type, loc_id = location_cache.get(location, (None, None))
                if not loc_type or not loc_id:
                    continue  # unresolved location — already logged by _resolve_location()
                if debug:
                    print(f"[glassdoor] searching: {term!r} @ {location!r}", file=sys.stderr)
                for row in scrape_glassdoor_combo(browser, term, loc_type, loc_id, debug=debug):
                    yield ("glassdoor", row)
        finally:
            browser.close()
