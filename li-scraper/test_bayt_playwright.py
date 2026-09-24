"""
Tests for the 2026-09-24 Bayt-via-Playwright replacement — see
bayt_playwright.py's module docstring for the full background, and
scrape.py's module docstring's "BAYT: NOW VIA PLAYWRIGHT" section for why
JobSpy's own Bayt integration was replaced rather than just retired (unlike
Glassdoor — see test_glassdoor_retired.py).

No real network/browser dependency needed for most of this: bayt_playwright's
DOM-extraction logic and date/URL helpers are pure functions, tested
directly. scrape_bayt_term()/scrape_bayt() are tested against a small fake
Playwright browser/page (fake_playwright below) that mimics just enough of
the real sync_playwright API surface (new_page/goto/wait_for_selector/
evaluate/close) to exercise the real code path, the same "insert a fake
module/object rather than touching the network" approach test_bayt_retired.py
and test_glassdoor_retired.py already use for jobspy. Run with
`python3 test_bayt_playwright.py` — no pytest/network/real browser required,
same as every other test file in this project.
"""

import inspect
import sys

import bayt_playwright as bp
import scrape

failures = 0


def check(label, ok):
    global failures
    failures += 0 if ok else 1
    print(f"  {'OK ' if ok else 'FAIL'}  {label}")


# ---------------------------------------------------------------------------
print("-- _term_to_url() --")
check("spaces become %20, not + or raw spaces",
      bp._term_to_url("Senior Product Manager") == "https://www.bayt.com/en/international/jobs/Senior%20Product%20Manager-jobs/")
check("a single-word term still gets the -jobs/ suffix",
      bp._term_to_url("Designer") == "https://www.bayt.com/en/international/jobs/Designer-jobs/")

# ---------------------------------------------------------------------------
print("\n-- _epoch_to_iso() --")
check("a real epoch string converts to YYYY-MM-DD",
      bp._epoch_to_iso("1790075285") == "2026-09-22")
check("None input returns None, doesn't raise",
      bp._epoch_to_iso(None) is None)
check("empty string returns None, doesn't raise",
      bp._epoch_to_iso("") is None)
check("garbage input returns None, doesn't raise",
      bp._epoch_to_iso("not-a-number") is None)

# ---------------------------------------------------------------------------
print("\n-- _cards_to_rows() --")
sample_cards = [
    {  # a normal card, everything present
        "title": "Product Manager",
        "href": "/en/uae/jobs/product-manager-5485024/",
        "company": "Al Futtaim Group",
        "location": "Dubai, UAE",
        "dateEpoch": "1790075285",
        "description": "Elevate your career as a Product Manager...",
    },
    {  # a "Confidential Company" card — no company link, just text (see
       # bayt_playwright.py's module docstring for why this happens)
        "title": "Product Manager",
        "href": "/en/saudi-arabia/jobs/product-manager-5483201/",
        "company": "Confidential Company",
        "location": "Riyadh, Saudi Arabia",
        "dateEpoch": "1789468899",
        "description": None,
    },
    {  # missing href — must be dropped, not passed through with a broken URL
        "title": "Some Role",
        "href": None,
        "company": "Some Co",
        "location": "Dubai, UAE",
        "dateEpoch": "1790075285",
        "description": None,
    },
    {  # missing title — must be dropped too
        "title": None,
        "href": "/en/uae/jobs/some-role-1234567/",
        "company": "Some Co",
        "location": "Dubai, UAE",
        "dateEpoch": "1790075285",
        "description": None,
    },
]
rows = bp._cards_to_rows(sample_cards)
check("2 of the 4 sample cards produce rows (missing href/title dropped)", len(rows) == 2)
check("job_url is BAYT_ORIGIN + href, absolute",
      rows[0]["job_url"] == "https://www.bayt.com/en/uae/jobs/product-manager-5485024/")
check("company passes through for a normal card",
      rows[0]["company"] == "Al Futtaim Group")
check("Confidential Company's bare text is used as the company name (not dropped, not null)",
      rows[1]["company"] == "Confidential Company")
check("date_posted is a clean ISO date, not a raw epoch",
      rows[0]["date_posted"] == "2026-09-22")
check("a missing/None description becomes '' , not None (build_fresh_roles() calls _clean_str on it either way, but this keeps the row shape consistent)",
      rows[1]["description"] == "")
check("every row has exactly the fields build_fresh_roles() reads: job_url/company/title/location/date_posted/description",
      all(set(r.keys()) == {"job_url", "company", "title", "location", "date_posted", "description"} for r in rows))

# ---------------------------------------------------------------------------
print("\n-- scrape_bayt_term() / scrape_bayt() against a fake Playwright browser --")


class FakeResponse:
    def __init__(self, status):
        self.status = status


class FakePage:
    """Mimics just enough of Playwright's sync Page API for
    scrape_bayt_term() to run against — goto/wait_for_selector/evaluate/close.
    `plan` maps a term to what that term's fake page should do, so different
    tests can exercise the success path, an HTTP error, and a
    no-results/timeout case without needing three separate fake classes."""

    def __init__(self, term, plan):
        self.term = term
        self.behavior = plan.get(term, {"status": 200, "cards": []})
        self.closed = False

    def goto(self, url, timeout=None, wait_until=None):
        assert "bayt.com" in url
        status = self.behavior.get("status", 200)
        return FakeResponse(status)

    def wait_for_selector(self, selector, timeout=None):
        if self.behavior.get("no_results"):
            raise TimeoutError("no results in fake page")
        return None

    def evaluate(self, js):
        return self.behavior.get("cards", [])

    def close(self):
        self.closed = True


class FakeBrowser:
    def __init__(self, plan):
        self.plan = plan
        self.pages_opened = []

    def new_page(self, user_agent=None):
        assert user_agent  # scrape_bayt_term must always set a real UA, not JobSpy's default
        # FakePage is keyed by term, but new_page() doesn't know the term —
        # scrape_bayt_term() is what ties them together via closure below,
        # so this fake just hands back a page pre-loaded with whatever the
        # NEXT queued behavior is.
        page = FakePage(self._next_term, self.plan)
        self.pages_opened.append(page)
        return page


good_card = {
    "title": "Senior Product Manager",
    "href": "/en/uae/jobs/senior-product-manager-9999999/",
    "company": "Test Co",
    "location": "Dubai, UAE",
    "dateEpoch": "1790075285",
    "description": "A description",
}

plan = {
    "Product Manager": {"status": 200, "cards": [good_card]},
    "Blocked Term": {"status": 403, "cards": []},
    "No Results Term": {"status": 200, "no_results": True, "cards": []},
}
browser = FakeBrowser(plan)

for term in plan:
    browser._next_term = term
    rows_for_term = bp.scrape_bayt_term(browser, term, debug=False)
    if term == "Product Manager":
        check("a successful term returns the extracted row",
              len(rows_for_term) == 1 and rows_for_term[0]["title"] == "Senior Product Manager")
    elif term == "Blocked Term":
        check("an HTTP error status returns [] rather than raising",
              rows_for_term == [])
    elif term == "No Results Term":
        check("a wait_for_selector timeout (no results) returns [] rather than raising",
              rows_for_term == [])

check("every opened fake page was closed (page.close() in the finally: block)",
      all(p.closed for p in browser.pages_opened))

# ---------------------------------------------------------------------------
print("\n-- scrape.py wiring: run_bayt_playwright_searches() is what main() calls --")

main_source = inspect.getsource(scrape.main)
check("main() calls run_bayt_playwright_searches(), not the retired run_bayt_searches()",
      "run_bayt_playwright_searches(" in main_source)
check("main() no longer calls the retired run_bayt_searches( ) directly",
      "run_bayt_searches(debug=debug)" not in main_source.split("run_bayt_playwright_searches")[0]
      if "run_bayt_playwright_searches" in main_source else False)

wrapper_source = inspect.getsource(scrape.run_bayt_playwright_searches)
check("run_bayt_playwright_searches() delegates to bayt_playwright.scrape_bayt(), doesn't reimplement scraping itself",
      "scrape_bayt(" in wrapper_source and "from bayt_playwright import scrape_bayt" in wrapper_source)

# run_bayt_searches() itself must still exist, unbroken, just unused — same
# "kept as a rollback path" convention as test_bayt_retired.py already
# verified for the Glassdoor-style retirement.
check("the old JobSpy-based run_bayt_searches() is still defined (kept intact as a rollback path)",
      hasattr(scrape, "run_bayt_searches") and inspect.isgeneratorfunction(scrape.run_bayt_searches))

print(f"\n{'ALL PASSED' if failures == 0 else f'{failures} FAILURE(S)'}")
sys.exit(1 if failures else 0)
