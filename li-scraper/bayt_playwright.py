"""
Bayt via headless Chromium. JobSpy's requests-based Bayt adapter gets a 403
everywhere (GitHub runners and a home IP alike, user_agent overrides don't
help); a real browser loads the page fine with no stealth tricks.

DOM shape (verified 2026-09-24 -- re-verify if Bayt redesigns its results page):
  - Each result is <li data-js-job data-job-id="...">.
  - Title + URL: 'h2 a[data-js-aid="jobID"]' -- `title` attr is the clean
    title, `href` is site-relative and ends in -<id>/.
  - Company: 'h2 + div.job-company-location-wrapper' -- must be scoped to the
    div right after the h2: the same class is reused on the location row, and
    an unscoped selector grabs the location on some cards. "Confidential
    Company" cards have no <a>, so fall back to the div's own text.
  - Location: 'dt.jb-label-location' -- one or two <span>s, joined with ", ".
  - Posted date: '[data-automation-id="job-active-date"]' -- its
    data-automation-jobactivedate attribute is a Unix epoch in seconds.
  - Description: '.jb-descr' -- a short "Summary: ..." blurb from the results
    list (prefix stripped); enough for sponsorship_signal() without a
    detail-page visit per result.

Only page 1 per term (~30 results, comparable to other sources). It skews to
Middle-East roles, which is why Bayt is kept; later pages drift to unrelated
markets. `?page=N` works if deeper pages are ever wanted.
"""

import sys
from datetime import datetime, timezone

BAYT_SEARCH_URL = "https://www.bayt.com/en/international/jobs/{term}-jobs/"
BAYT_ORIGIN = "https://www.bayt.com"

# Bounded so a slow page can't hang a scheduled run; same as js-scraper's TIMEOUT_MS.
PAGE_TIMEOUT_MS = 30000

# A normal desktop Chrome UA, so requests look like a browser rather than a
# scraping library's default.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)


def _term_to_url(term):
    return BAYT_SEARCH_URL.format(term=term.replace(" ", "%20"))


def _epoch_to_iso(epoch_str):
    """Unix epoch seconds (string) -> 'YYYY-MM-DD', same shape as normalize_posted_date().
        None when unparseable -- a bad date shouldn't drop an otherwise-good row.
    """
    if not epoch_str:
        return None
    try:
        return datetime.fromtimestamp(int(epoch_str), tz=timezone.utc).date().isoformat()
    except (ValueError, OSError, OverflowError, TypeError):
        return None


# In-page extraction (selectors explained in the module docstring), one
# round-trip per term.
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
    """Raw card dicts -> JobSpy-shaped rows (job_url/company/title/location/
        date_posted/description). Cards missing a title or href are dropped.
    """
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
    """Page 1 of Bayt's results for `term`, in a fresh tab of an already-launched
        browser. Returns [] on any failure so one term can't break the run.
    """
    url = _term_to_url(term)
    page = browser.new_page(user_agent=USER_AGENT)
    try:
        response = page.goto(url, timeout=PAGE_TIMEOUT_MS, wait_until="domcontentloaded")
        if response is not None and response.status >= 400:
            print(f"[bayt] {term!r}: HTTP {response.status}", file=sys.stderr)
            return []
        try:
            page.wait_for_selector("li[data-js-job]", timeout=PAGE_TIMEOUT_MS)
        except Exception:
            # No results, or nothing rendered in time -- not a failure.
            if debug:
                print(f"[bayt] {term!r}: no results (or didn't render in time)", file=sys.stderr)
            return []
        raw_cards = page.evaluate(_EXTRACT_JS)
    except Exception as e:  # noqa: BLE001 — one term's failure must not kill the run
        print(f"[bayt] {term!r} failed: {type(e).__name__}: {e}", file=sys.stderr)
        return []
    finally:
        page.close()

    rows = _cards_to_rows(raw_cards)
    if debug:
        print(f"[bayt] {term!r}: {len(rows)} rows", file=sys.stderr)
    return rows


def scrape_bayt(terms, debug=False):
    """One headless Chromium, one fresh tab per term; yields ("bayt", row) like the
        other sources. Playwright is imported lazily so the tests and match.py
        import without it installed.
    """
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
