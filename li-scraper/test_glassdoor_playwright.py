"""
Tests for the 2026-09-24 Glassdoor-via-Playwright replacement — see
glassdoor_playwright.py's module docstring for the full background, and
scrape.py's module docstring's "GLASSDOOR: NOW VIA PLAYWRIGHT" section for
why JobSpy's Glassdoor integration was replaced (same 400/403 story as
Bayt) rather than retired as originally planned. Companion to
test_bayt_playwright.py — same testing philosophy: pure functions tested
directly, a small fake Playwright browser/page for the parts that touch a
"browser", no real network/browser dependency needed. Run with
`python3 test_glassdoor_playwright.py`.
"""

import inspect
import sys

import glassdoor_playwright as gp
import scrape

failures = 0


def check(label, ok):
    global failures
    failures += 0 if ok else 1
    print(f"  {'OK ' if ok else 'FAIL'}  {label}")


# ---------------------------------------------------------------------------
print("-- _relative_age_to_iso() --")
from datetime import datetime, timezone  # noqa: E402

FIXED_NOW = datetime(2026, 9, 24, 12, 0, 0, tzinfo=timezone.utc)

check("'3d' -> 3 days before FIXED_NOW",
      gp._relative_age_to_iso("3d", now=FIXED_NOW) == "2026-09-21")
check("'18d' -> 18 days before FIXED_NOW",
      gp._relative_age_to_iso("18d", now=FIXED_NOW) == "2026-09-06")
check("'30d+' -> the numeric part (30) is used, trailing '+' ignored",
      gp._relative_age_to_iso("30d+", now=FIXED_NOW) == "2026-08-25")
check("'5h' -> same day as FIXED_NOW (5 hours back, no date rollover at noon)",
      gp._relative_age_to_iso("5h", now=FIXED_NOW) == "2026-09-24")
check("'2mo' -> ~60 days before FIXED_NOW (approximate, Glassdoor's own unit is coarse)",
      gp._relative_age_to_iso("2mo", now=FIXED_NOW) == "2026-07-26")
check("'Just posted' -> today",
      gp._relative_age_to_iso("Just posted", now=FIXED_NOW) == "2026-09-24")
check("'today' -> today", gp._relative_age_to_iso("today", now=FIXED_NOW) == "2026-09-24")
check("None -> None", gp._relative_age_to_iso(None, now=FIXED_NOW) is None)
check("'' -> None", gp._relative_age_to_iso("", now=FIXED_NOW) is None)
check("garbage text -> None, doesn't raise",
      gp._relative_age_to_iso("posted whenever", now=FIXED_NOW) is None)

# ---------------------------------------------------------------------------
print("\n-- _build_search_url() --")
check("plain term builds the verified query-string form",
      gp._build_search_url("Product Manager", "N", 217)
      == "https://www.glassdoor.com/Job/jobs.htm?sc.keyword=Product%20Manager&locT=N&locId=217")
check("a term with a slash is URL-encoded, not left raw (verified against the real site with this exact term)",
      "%2F" in gp._build_search_url("Senior UX/UI Designer", "N", 217))
check("an S-type (state/region) location uses locT=S",
      "locT=S" in gp._build_search_url("Product Manager", "S", 5668))

# ---------------------------------------------------------------------------
print("\n-- _normalize_job_url() --")
check("a .sg TLD is normalized to .com",
      gp._normalize_job_url("https://www.glassdoor.sg/job-listing/x-JV_IC1.htm") == "https://www.glassdoor.com/job-listing/x-JV_IC1.htm")
check("already-.com is left unchanged",
      gp._normalize_job_url("https://www.glassdoor.com/job-listing/x-JV_IC1.htm") == "https://www.glassdoor.com/job-listing/x-JV_IC1.htm")

# ---------------------------------------------------------------------------
print("\n-- _cards_to_rows() --")
sample_cards = [
    {
        "title": "Product Owner - Contract",
        "href": "https://www.glassdoor.sg/job-listing/product-owner-contract-JV_IC3235921.htm",
        "company": "NTT DATA Business Solutions Singapore",
        "location": "Singapore",
        "age": "3d",
        "description": "Good stakeholder-management and communication skills...",
    },
    {  # missing href — must be dropped
        "title": "Some Role",
        "href": None,
        "company": "Some Co",
        "location": "Singapore",
        "age": "1d",
        "description": None,
    },
    {  # missing title — must be dropped too
        "title": None,
        "href": "https://www.glassdoor.sg/job-listing/x-JV_IC1.htm",
        "company": "Some Co",
        "location": "Singapore",
        "age": "1d",
        "description": None,
    },
]
rows = gp._cards_to_rows(sample_cards)
check("1 of the 3 sample cards produces a row (the other 2 are missing href/title and are dropped)", len(rows) == 1)
check("job_url is normalized to .com", rows[0]["job_url"].startswith("https://www.glassdoor.com/"))
check("company passes through", rows[0]["company"] == "NTT DATA Business Solutions Singapore")
check("date_posted is computed from the relative age text, not the raw text itself",
      rows[0]["date_posted"] != "3d" and rows[0]["date_posted"] is not None)
check("every row has exactly the fields build_fresh_roles() reads: job_url/company/title/location/date_posted/description",
      all(set(r.keys()) == {"job_url", "company", "title", "location", "date_posted", "description"} for r in rows))

# ---------------------------------------------------------------------------
print("\n-- _resolve_location() against real, captured API response shapes --")

# Real response shapes captured 2026-09-24 from Glassdoor's own
# /autocomplete/location endpoint (see glassdoor_playwright.py's module
# docstring) — Singapore has BOTH an exact-name N-type (country) and an
# exact-name C-type (city) candidate; N must win. Kuala Lumpur only has an
# exact-name S-type (state/region) candidate.
SINGAPORE_CANDIDATES = [
    {"locationId": 3235921, "locationType": "C", "locationName": "Singapore", "countryId": 217},
    {"locationId": 5017206, "locationType": "C", "locationName": "Singapore River, Central", "countryId": 217},
    {"locationId": 217, "locationType": "N", "locationName": "Singapore", "countryId": 217},
]
KUALA_LUMPUR_CANDIDATES = [
    {"locationId": 5668, "locationType": "S", "locationName": "Kuala Lumpur", "countryId": 170},
    {"locationId": 2957417, "locationType": "C", "locationName": "Batu, Kuala Lumpur", "countryId": 170},
]
NO_MATCH_CANDIDATES = [
    {"locationId": 999, "locationType": "C", "locationName": "Somewhere Else Entirely", "countryId": 1},
]


class FakePageForResolve:
    def __init__(self, candidates):
        self.candidates = candidates
        self.evaluate_calls = 0

    def evaluate(self, js, arg=None):
        self.evaluate_calls += 1
        return self.candidates


sg_page = FakePageForResolve(SINGAPORE_CANDIDATES)
loc_type, loc_id = gp._resolve_location(sg_page, "Singapore", debug=False)
check("Singapore resolves to the N-type (country) candidate, not the C-type (city) one, even though C came first",
      (loc_type, loc_id) == ("N", 217))

kl_page = FakePageForResolve(KUALA_LUMPUR_CANDIDATES)
loc_type, loc_id = gp._resolve_location(kl_page, "Kuala Lumpur", debug=False)
check("Kuala Lumpur resolves to its S-type (state/region) candidate — verified against the real live site",
      (loc_type, loc_id) == ("S", 5668))

nomatch_page = FakePageForResolve(NO_MATCH_CANDIDATES)
loc_type, loc_id = gp._resolve_location(nomatch_page, "Nowhere", debug=False)
check("a location with no exact-name match returns (None, None) rather than guessing the closest candidate",
      (loc_type, loc_id) == (None, None))

raising_page = FakePageForResolve(None)


def _raise(*a, **k):
    raise RuntimeError("network error")


raising_page.evaluate = _raise
loc_type, loc_id = gp._resolve_location(raising_page, "Singapore", debug=False)
check("a resolution failure (exception) returns (None, None) rather than raising",
      (loc_type, loc_id) == (None, None))

# ---------------------------------------------------------------------------
print("\n-- scrape_glassdoor_combo() / scrape_glassdoor() against a fake Playwright browser --")


class FakeResponse:
    def __init__(self, status):
        self.status = status


class FakePage:
    def __init__(self, behavior):
        self.behavior = behavior
        self.closed = False

    def goto(self, url, timeout=None, wait_until=None):
        assert "glassdoor.com" in url
        return FakeResponse(self.behavior.get("status", 200))

    def wait_for_selector(self, selector, timeout=None):
        if self.behavior.get("no_results"):
            raise TimeoutError("no results in fake page")
        return None

    def evaluate(self, js, arg=None):
        return self.behavior.get("cards", [])

    def close(self):
        self.closed = True


class FakeBrowserForCombo:
    """Used only for scrape_glassdoor_combo() — a single combo's behavior."""
    def __init__(self, behavior):
        self.behavior = behavior
        self.pages = []

    def new_page(self, user_agent=None):
        assert user_agent
        page = FakePage(self.behavior)
        self.pages.append(page)
        return page


good_card = {
    "title": "Senior Product Manager",
    "href": "https://www.glassdoor.sg/job-listing/x-JV_IC217.htm",
    "company": "Test Co",
    "location": "Singapore",
    "age": "2d",
    "description": "A description",
}

success_browser = FakeBrowserForCombo({"status": 200, "cards": [good_card]})
rows = gp.scrape_glassdoor_combo(success_browser, "Product Manager", "N", 217, debug=False)
check("a successful combo returns the extracted row", len(rows) == 1 and rows[0]["title"] == "Senior Product Manager")
check("the page was closed after use", success_browser.pages[0].closed)

blocked_browser = FakeBrowserForCombo({"status": 403, "cards": []})
rows = gp.scrape_glassdoor_combo(blocked_browser, "Product Manager", "N", 217, debug=False)
check("an HTTP error status returns [] rather than raising", rows == [])

empty_browser = FakeBrowserForCombo({"status": 200, "no_results": True, "cards": []})
rows = gp.scrape_glassdoor_combo(empty_browser, "Product Manager", "N", 217, debug=False)
check("a wait_for_selector timeout (no results) returns [] rather than raising", rows == [])

# ---------------------------------------------------------------------------
print("\n-- scrape.py wiring --")

main_source = inspect.getsource(scrape.main)
check("main() calls run_glassdoor_playwright_searches(), not the retired run_glassdoor_searches()",
      "run_glassdoor_playwright_searches(" in main_source)
check("main() does not call the retired run_glassdoor_searches() at all",
      "run_glassdoor_searches(" not in main_source)
check("main() does not call the retired run_google_searches() at all",
      "run_google_searches(" not in main_source)

wrapper_source = inspect.getsource(scrape.run_glassdoor_playwright_searches)
check("run_glassdoor_playwright_searches() filters by GLASSDOOR_COUNTRY itself before delegating",
      "GLASSDOOR_COUNTRY" in wrapper_source and "scrape_glassdoor(" in wrapper_source)

check("the old JobSpy-based run_glassdoor_searches() is still defined (kept intact as a rollback path)",
      hasattr(scrape, "run_glassdoor_searches") and inspect.isgeneratorfunction(scrape.run_glassdoor_searches))
check("the old JobSpy-based run_google_searches() is still defined (kept intact as a reference/rollback path)",
      hasattr(scrape, "run_google_searches") and inspect.isgeneratorfunction(scrape.run_google_searches))

run_searches_source = inspect.getsource(scrape.run_searches)
check("run_searches() (LI+Indeed) no longer makes a glassdoor scrape_jobs call",
      'site_name=["glassdoor"]' not in run_searches_source)
check("run_searches() (LI+Indeed) no longer makes a google scrape_jobs call",
      'site_name=["google"]' not in run_searches_source)

print(f"\n{'ALL PASSED' if failures == 0 else f'{failures} FAILURE(S)'}")
sys.exit(1 if failures else 0)
