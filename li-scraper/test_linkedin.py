"""
Tests for linkedin_guest.py and scrape.py's run_linkedin() / run_indeed_searches()
against fakes: no network. Card markup copied from LinkedIn's guest search
(2026-10-26). Run: python3 test_linkedin.py
"""

import logging
import sys

import linkedin_guest as lg
import scrape

failures = 0


def check(label, ok):
    global failures
    failures += 0 if ok else 1
    print(f"  {'OK ' if ok else 'FAIL'}  {label}")


def card(job_id, title, company="DEPT®", location="Amsterdam, North Holland, Netherlands", posted="2026-10-26"):
    return (
        f'<li><div class="base-card relative w-full base-card--link base-search-card base-search-card--link job-search-card" '
        f'data-entity-urn="urn:li:jobPosting:{job_id}">'
        f'<a class="base-card__full-link absolute" href="https://nl.linkedin.com/jobs/view/x-{job_id}?position=1"></a>'
        f'<div class="base-search-card__info"><h3 class="base-search-card__title">\n  {title}\n</h3>'
        f'<h4 class="base-search-card__subtitle"><a href="https://nl.linkedin.com/company/dept">{company}</a></h4>'
        f'<div class="base-search-card__metadata"><span class="job-search-card__location">{location}</span>'
        f'<time class="job-search-card__listdate--new" datetime="{posted}">23 minutes ago</time></div></div></div></li>'
    )


EMPTY_PAGE = "<!DOCTYPE html>\n\n<!---->"


class Resp:
    def __init__(self, status=200, text="", headers=None):
        self.status_code = status
        self.text = text
        self.headers = headers or {}


print("-- keyword_groups() --")
groups = lg.keyword_groups(["Product Manager", "Senior Product Manager", "Design Lead", "Product Design Lead",
                            "UX Researcher", "Lead UX Researcher", "Head of Design", "design lead"])
check("a term containing another term is dropped; duplicates too",
      groups == ['"product manager" OR "design lead" OR "ux researcher" OR "head of design"'])
check("packed into groups of at most MAX_PHRASES_PER_GROUP",
      [g.count(" OR ") + 1 for g in lg.keyword_groups([f"term {i}" for i in range(23)])] == [10, 10, 3])
check("'Product Designer' isn't dropped for containing 'Product' alone (whole phrases only)",
      lg.keyword_groups(["Product", "Product Designer", "Productivity Lead"]) == ['"product" OR "productivity lead"'])
real = lg.keyword_groups(scrape.SEARCH_TERMS)
check(f"the real 38 terms become a few groups ({len(real)})", 2 <= len(real) <= 4)

print("\n-- parse_cards() --")
rows = lg.parse_cards(card(4321, "Associate Design Director") + card(99, "UX Lead", company="Acme", location="London, England, United Kingdom", posted="2026-10-25"))
check("two cards -> two rows", len(rows) == 2)
check("JobSpy-shaped row: url, company, title, location, date, description",
      rows[0] == {"job_url": "https://www.linkedin.com/jobs/view/4321", "company": "DEPT®", "title": "Associate Design Director",
                  "location": "Amsterdam, North Holland, Netherlands", "date_posted": "2026-10-26", "description": ""})
no_urn = card(555, "Design Lead").replace('data-entity-urn="urn:li:jobPosting:555"', "")
check("job id falls back to the link when the card has no urn", lg.parse_cards(no_urn)[0]["job_url"].endswith("/555"))
check("the empty-results page has no cards", lg.parse_cards(EMPTY_PAGE) == [])

print("\n-- fetch_page() --")
seen_params = []


def get_returning(resp):
    def get(url, params=None, headers=None, timeout=None):
        seen_params.append(params)
        return resp
    return get


lg.fetch_page(get_returning(Resp(200, card(1, "Design Lead"))), '"design lead"', "Netherlands", 10800.4, 20)
check("asks for the window in seconds, newest first, at the right offset",
      seen_params[-1] == {"keywords": '"design lead"', "location": "Netherlands", "f_TPR": "r10800", "sortBy": "DD", "start": 20})
check("the empty page is an empty result, not a block", lg.fetch_page(get_returning(Resp(200, EMPTY_PAGE)), "k", "l", 3600, 0) == [])
for status in (429, 999, 403):
    try:
        lg.fetch_page(get_returning(Resp(status, "", {"Retry-After": "120"})), "k", "l", 3600, 0)
        check(f"HTTP {status} raises Blocked", False)
    except lg.Blocked as b:
        check(f"HTTP {status} raises Blocked (Retry-After read: {b.wait})", b.status == status and b.wait == 120)
try:
    lg.fetch_page(get_returning(Resp(200, "<html><body><h1>Sign in to view more jobs</h1><form>...</form></body></html>")), "k", "l", 3600, 0)
    check("a 200 page with markup but no cards (login wall) is a block", False)
except lg.Blocked:
    check("a 200 page with markup but no cards (login wall) is a block", True)

print("\n-- search() paging --")


def paged_get(total):
    calls = []

    def get(url, params=None, headers=None, timeout=None):
        calls.append(params["start"])
        start = params["start"]
        ids = range(start, min(start + lg.PAGE_SIZE, total))
        return Resp(200, "".join(card(i + 1, f"Design Lead {i}") for i in ids) or EMPTY_PAGE)
    return get, calls


get, calls = paged_get(23)
pauses = []
rows, n = lg.search(get, "k", "l", 3600, lambda: pauses.append(1))
check("23 postings -> 3 requests (10 + 10 + 3), all rows", (len(rows), n, calls) == (23, 3, [0, 10, 20]))
check("pauses between pages, not before the first", len(pauses) == 2)
get, calls = paged_get(10)
rows, n = lg.search(get, "k", "l", 3600, lambda: None)
check("exactly one full page -> one more request that comes back empty", (len(rows), n) == (10, 2))
get, calls = paged_get(500)
rows, n = lg.search(get, "k", "l", 3600, lambda: None, max_pages=3)
check("stops at the page cap", (len(rows), n) == (30, 3))

print("\n-- run_linkedin(): windows, coverage, blocks, budget --")
NOW = 1_800_000_000  # fixed clock
iso = scrape._iso_utc
searches = scrape.linkedin_searches()
keys = [scrape.linkedin_key(*s) for s in searches]


class FakeLinkedIn:
    """Answers every search with one posting; `plan` blocks the n-th request."""

    def __init__(self, block_at=()):
        self.requests = []
        self.block_at = set(block_at)

    def get(self, url, params=None, headers=None, timeout=None):
        self.requests.append(params)
        if len(self.requests) in self.block_at:
            return Resp(429, "")
        return Resp(200, card(len(self.requests), "Design Lead", location=params["location"]))


fake = FakeLinkedIn()
sleeps = []
rows, coverage, health = scrape.run_linkedin({}, get=fake.get, sleep=sleeps.append, now=lambda: NOW)
check(f"every market x keyword group searched once ({len(searches)} searches, one request each)",
      len(fake.requests) == len(searches) and health["done"] == len(searches))
check("no coverage yet -> the first-run window", all(p["f_TPR"] == f"r{scrape.LINKEDIN_FIRST_WINDOW_SECONDS}" for p in fake.requests))
check("each completed search is recorded with its start time", coverage == {k: iso(NOW) for k in keys})
check("rows are tagged li", len(rows) == len(searches) and all(s == "li" for s, _ in rows))
check("requests are spaced (one pause between searches)", len(sleeps) == len(searches) - 1
      and all(scrape.LINKEDIN_PAUSE_SECONDS[0] <= x <= scrape.LINKEDIN_PAUSE_SECONDS[1] for x in sleeps))
check("health: nothing blocked, all done, stalest 0h",
      (health["blocked"], health["stoppedEarly"], health["stalestHours"]) == (0, False, 0.0))

fake = FakeLinkedIn()
cov = {k: iso(NOW - 2 * 3600) for k in keys}
cov[keys[0]] = iso(NOW - 30 * 3600)
cov[keys[1]] = iso(NOW - 30 * 86400)
cov["Gone Market|\"old\""] = iso(NOW)
rows, coverage, health = scrape.run_linkedin(cov, get=fake.get, sleep=lambda s: None, now=lambda: NOW)
windows = {(p["location"], p["keywords"]): p["f_TPR"] for p in fake.requests}
check("2h since the last success -> the minimum window (3h)", windows[searches[2]] == f"r{scrape.LINKEDIN_MIN_WINDOW_SECONDS}")
check("30h since -> 31h (gap + 1h margin)", windows[searches[0]] == f"r{31 * 3600}")
check("30 days since -> capped at the maximum (7 days)", windows[searches[1]] == f"r{scrape.LINKEDIN_MAX_WINDOW_SECONDS}")
check("the stalest searches go first", (fake.requests[0]["location"], fake.requests[0]["keywords"]) == searches[1])
check("searches no longer configured are dropped from coverage", "Gone Market|\"old\"" not in coverage)

fake = FakeLinkedIn(block_at={3})
sleeps = []
rows, coverage, health = scrape.run_linkedin({}, get=fake.get, sleep=sleeps.append, now=lambda: NOW)
check("one block: wait, retry that search, carry on (all searches done)", health["done"] == len(searches) and health["blocked"] == 1)
check("...the wait is LINKEDIN_BLOCK_WAIT_SECONDS when LinkedIn gives no Retry-After", scrape.LINKEDIN_BLOCK_WAIT_SECONDS in sleeps)

fake = FakeLinkedIn(block_at={3, 4})
cov = {k: iso(NOW - 2 * 3600) for k in keys}
rows, coverage, health = scrape.run_linkedin(cov, get=fake.get, sleep=lambda s: None, now=lambda: NOW)
check("blocked again on the retry: LinkedIn stops for this run", health["stoppedEarly"] and len(fake.requests) == 4)
check("...the two searches done keep the new time, the rest keep their old one",
      sum(1 for v in coverage.values() if v == iso(NOW)) == 2 and sum(1 for v in coverage.values() if v == iso(NOW - 2 * 3600)) == len(keys) - 2)
check("...health reports it", (health["done"], health["blocked"], health["stalestHours"]) == (2, 2, 2.0))

saved = scrape.LINKEDIN_MAX_REQUESTS_PER_RUN
scrape.LINKEDIN_MAX_REQUESTS_PER_RUN = 5
fake = FakeLinkedIn()
rows, coverage, health = scrape.run_linkedin({}, get=fake.get, sleep=lambda s: None, now=lambda: NOW)
scrape.LINKEDIN_MAX_REQUESTS_PER_RUN = saved
check("the request budget ends the run's LinkedIn part; the rest wait (never covered -> stalestHours None)",
      len(fake.requests) == 5 and health["done"] == 5 and health["stalestHours"] is None and not health["stoppedEarly"])

print("\n-- run_indeed_searches(): failures counted from JobSpy's error log --")


class Frame:
    def __init__(self, rows):
        self.rows = rows

    def __len__(self):
        return len(self.rows)

    def to_dict(self, orient=None):
        return self.rows


def fake_jobspy(site_name, search_term, location, **kw):
    if search_term == "Blocked":
        logging.getLogger("jobspy.indeed").error("response status code 403 (blocked: use a proxy)")
        return Frame([])
    if search_term == "Crash":
        raise RuntimeError("boom")
    return Frame([{"title": search_term}])


combos = [("Design Lead", "Netherlands"), ("Blocked", "Netherlands"), ("Crash", "Netherlands"), ("UX Lead", "Netherlands")]
pauses = []
rows, health = scrape.run_indeed_searches(combos, scrape_jobs=fake_jobspy, sleep=pauses.append)
check("rows from the good searches, tagged indeed", rows == [("indeed", {"title": "Design Lead"}), ("indeed", {"title": "UX Lead"})])
check("health counts the logged block and the exception as failed", health == {"searches": 4, "failed": 2, "rows": 2})
check("paced between searches", len(pauses) == 3)
check("the log counter is removed afterwards",
      not any(isinstance(h, scrape.ErrorLogCount) for h in logging.getLogger("jobspy.indeed").handlers))

print(f"\n{'ALL PASSED' if failures == 0 else f'{failures} FAILURE(S)'}")
sys.exit(1 if failures else 0)
