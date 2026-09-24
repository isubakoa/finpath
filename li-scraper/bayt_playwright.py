"""
Bayt scraper via Playwright (real headless Chromium), replacing JobSpy's
Bayt integration — see run_bayt_searches()'s retirement note in scrape.py
for the full story of why: JobSpy's requests-based Bayt adapter gets an
outright 403 on every request, confirmed BOTH from GitHub Actions' runners
AND from a real home/office IP (via diagnose_google_bayt.py) — so this
isn't an IP-reputation block, and a `user_agent` override doesn't fix it
either (also tested, also failed). JobSpy's own maintainers, in a GitHub
issue about the closely analogous Google/ZipRecruiter/Glassdoor case, say
sites in this class need "a JS-executing fetch (Playwright etc.)", not a
header or proxy tweak — this module is exactly that.

Verified 2026-09-24 by loading Bayt's real search-results page in a live
browser and inspecting the actual DOM directly (not guessed, not copied
from JobSpy's source — that file was never reachable, see the diagnostic
writeup). A real headless-Chromium-class request got a normal 200 with
real results on the first try, no stealth plugins or extra tricks needed —
consistent with the theory that Bayt's block is about non-JS/requests-
shaped traffic specifically, not IP reputation: the requests-based
baseline failed even from a residential IP, but a real browser succeeded
even from an unrelated one. That said, this has NOT yet been proven from
inside a real GitHub Actions runner specifically — GH Actions' shared IP
ranges are a somewhat more commonly-blocked source than most, so the first
few scheduled/workflow_dispatch runs are worth watching before fully
trusting this at the normal hourly cadence (see scrape.py's call site).

DOM shape (verified against a real, live Bayt search page 2026-09-24 —
re-verify this if Bayt redesigns their results page; nothing below is
guessed):
  - Each result is an <li data-js-job data-job-id="...">.
  - Title + URL: li.querySelector('h2 a[data-js-aid="jobID"]') — the link's
    `title` attribute is the clean title text (matches the link's own
    visible text), `href` is a site-relative job-detail URL ending in
    `-<numeric id>/`.
  - Company: li.querySelector('h2 + div.job-company-location-wrapper') —
    MUST be scoped this way, as the element immediately following the h2,
    not just '.job-company-location-wrapper a' — that class name is reused
    on the location <dt> a few lines further down the same card, so an
    unscoped selector silently grabs the LOCATION link instead of the
    company on a real fraction of cards (confirmed by testing — not a
    hypothetical). If that div contains an <a>, its text is the company
    name; a "Confidential Company" listing has no link at all, just a bare
    text node reading "Confidential Company" — fall back to the div's own
    text in that case.
  - Location: li.querySelector('dt.jb-label-location') — one or two <span>
    children (city, then country), joined with ", ".
  - Posted date: li.querySelector('[data-automation-id="job-active-date"]')
    — its `data-automation-jobactivedate` attribute is a real Unix epoch in
    seconds, far more reliable than parsing the adjacent human text ("2
    days ago", "30+ days ago").
  - Description: li.querySelector('.jb-descr') — a short "Summary: ..."
    blurb Bayt already renders right in the results list (no need to visit
    each job's own detail page for this), stripped of the literal
    "Summary:" prefix. This is enough for scrape.py's sponsorship_signal()
    keyword scan; it's not the full job description a detail-page visit
    would give, but a second page load per result is a much heavier cost
    for a marginal, not-yet-justified benefit — revisit only if
    sponsorship-signal coverage on Bayt roles turns out to matter in
    practice.

Only page 1 per term is fetched (Bayt's own fixed page size, ~30 results)
— roughly the same order of magnitude as RESULTS_WANTED_PER_SEARCH used
for every other site. Bayt also exposes plain `?page=N` pagination (no
AJAX-only mechanism — confirmed by navigating there directly), so deeper
pages are a small, contained future change if page 1 ever proves
insufficient; not implemented here; page 1 deliberately also skews toward
Middle-East results specifically (Bayt's own "Jobs in the Middle East"
default framing), which happens to line up well with the reason Bayt is
being kept in the first place — page 2+ started surfacing unrelated
results (e.g. India) in testing, for reasons not otherwise clear from
this file.
"""

import sys
from datetime import datetime, timezone

BAYT_SEARCH_URL = "https://www.bayt.com/en/international/jobs/{term}-jobs/"
BAYT_ORIGIN = "https://www.bayt.com"

# Generous but bounded — a slow/heavy Bayt page load shouldn't be allowed to
# hang a scheduled run indefinitely; matches js-scraper/scrape.js's own
# TIMEOUT_MS for the same reason (a real, tested value from this repo, not
# an arbitrary pick).
PAGE_TIMEOUT_MS = 30000

# A real, current desktop Chrome UA — same string used in this project's
# diagnose_google_bayt.py diagnostic (kept in sync deliberately; both exist
# to look like an ordinary browser, not a scraping library's default).
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)


def _term_to_url(term):
    return BAYT_SEARCH_URL.format(term=term.replace(" ", "%20"))


def _epoch_to_iso(epoch_str):
    """Bayt's data-automation-jobactivedate is a Unix epoch in seconds (as a
    string). Converts to the same 'YYYY-MM-DD' shape scrape.py's
    normalize_posted_date() produces for every other site, so build_fresh_roles()
    treats a Bayt row's date_posted identically to any other source's —
    no special-casing needed downstream. Returns None on anything
    unparseable rather than raising; a missing/bad date shouldn't drop an
    otherwise-good row."""
    if not epoch_str:
        return None
    try:
        return datetime.fromtimestamp(int(epoch_str), tz=timezone.utc).date().isoformat()
    except (ValueError, OSError, OverflowError, TypeError):
        return None


# The in-page extraction script — see the module docstring for why each
# selector is scoped the way it is. Kept as a single JS string (rather than
# several separate page.eval calls) so it runs as one round-trip into the
# page per term.
_EXTRACT_JS = """
() => {
  const cards = Array.from(document.querySelectorAll('li[data-js-job]'));
  return cards.map(li => {
    const a = li.querySelector('h2 a[data-js-aid="jobID"]');
    const companyWrap = li.querySelector('h2 + div.job-company-location-wrapper');
    const companyA = companyWrap ? companyWrap.querySelector('a') : null;
    const locDt = li.querySelector('dt.jb-label-location');
    const locSpans = locDt ? Array.from(locDt.querySelectorAll('span')).map(s => s.textContent.trim()) : [];
    const dateSpan = li.querySelector('[data-automation-id="job-active-date"]');
    const descrEl = li.querySelector('.jb-descr');
    return {
      title: a ? a.getAttribute('title') : null,
      href: a ? a.getAttribute('href') : null,
      company: companyA ? companyA.textContent.trim() : (companyWrap ? companyWrap.textContent.trim() : null),
      location: locSpans.join(', '),
      dateEpoch: dateSpan ? dateSpan.getAttribute('data-automation-jobactivedate') : null,
      description: descrEl ? descrEl.textContent.replace(/^\\s*Summary:\\s*/, '').trim() : null,
    };
  });
}
"""


def _cards_to_rows(raw_cards):
    """Turns the raw extracted card dicts into JobSpy-row-shaped dicts —
    the exact fields scrape.py's build_fresh_roles() reads via row.get(...):
    job_url/company/title/location/date_posted/description. A card missing
    a title or href is dropped outright (build_fresh_roles() would drop it
    anyway on an empty job_url, but there's no reason to even hand it a
    half-built row)."""
    rows = []
    for card in raw_cards:
        if not card.get("href") or not card.get("title"):
            continue
        rows.append({
            "job_url": BAYT_ORIGIN + card["href"],
            "company": card.get("company") or "",
            "title": card["title"],
            "location": card.get("location") or "",
            "date_posted": _epoch_to_iso(card.get("dateEpoch")),
            "description": card.get("description") or "",
        })
    return rows


def scrape_bayt_term(browser, term, debug=False):
    """Loads page 1 of Bayt's search results for `term` in a fresh page/tab
    on the given (already-launched) Playwright browser, and returns a list
    of JobSpy-row-shaped dicts. Returns [] on any failure — a bad HTTP
    status, no results, a timeout, anything else — rather than raising, so
    one term's failure can never take the whole Bayt run down (the same
    per-term isolation every other site already has in scrape.py's
    run_searches())."""
    url = _term_to_url(term)
    page = browser.new_page(user_agent=USER_AGENT)
    try:
        response = page.goto(url, timeout=PAGE_TIMEOUT_MS, wait_until="domcontentloaded")
        if response is not None and response.status >= 400:
            if debug:
                print(f"[bayt] {term!r}: HTTP {response.status}", file=sys.stderr)
            return []
        try:
            page.wait_for_selector("li[data-js-job]", timeout=PAGE_TIMEOUT_MS)
        except Exception:
            # No results for this term, or nothing rendered in time — either
            # way there's nothing to extract; not itself an error worth
            # logging as a failure the way an HTTP error or exception is.
            if debug:
                print(f"[bayt] {term!r}: no results (or didn't render in time)", file=sys.stderr)
            return []
        raw_cards = page.evaluate(_EXTRACT_JS)
    except Exception as e:  # noqa: BLE001 — one term's failure must not kill the run
        if debug:
            print(f"[bayt] {term!r} failed: {type(e).__name__}: {e}", file=sys.stderr)
        return []
    finally:
        page.close()

    rows = _cards_to_rows(raw_cards)
    if debug:
        print(f"[bayt] {term!r}: {len(rows)} rows", file=sys.stderr)
    return rows


def scrape_bayt(terms, debug=False):
    """Launches one headless Chromium browser and scrapes page 1 of every
    term in `terms` against it — a fresh page/tab per term, same browser
    process reused throughout (mirrors js-scraper/scrape.js's main(), which
    launches Chromium once and opens one page per company). Yields
    ("bayt", row) tuples — exactly the shape run_searches()/the retired
    run_bayt_searches() already yield, so scrape.py's build_fresh_roles()
    needs no changes at all to consume this.

    Imports playwright lazily (only inside this function, not at module
    import time) — same reasoning as scrape.py's own lazy `from jobspy
    import scrape_jobs` inside run_searches()/run_bayt_searches(): so
    match.py/test_match.py/test_rotation.py, and this module's own unit
    tests, stay importable without the playwright package (or its browser
    binary) installed at all."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            for term in terms:
                if debug:
                    print(f"[bayt] searching: {term!r}", file=sys.stderr)
                for row in scrape_bayt_term(browser, term, debug=debug):
                    yield ("bayt", row)
        finally:
            browser.close()
