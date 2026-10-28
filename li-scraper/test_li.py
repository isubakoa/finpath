"""
Tests for li_guest.py and scrape.py's run_li() / run_indeed_searches()
against fakes: no network. Card markup copied from LI's guest search
(2026-10-26). Run: python3 test_li.py
"""

import logging
import sys

import li_guest as lg
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
        f'<a class="base-card__full-link absolute" href="{lg.SITE}/jobs/view/x-{job_id}?position=1"></a>'
        f'<div class="base-search-card__info"><h3 class="base-search-card__title">\n  {title}\n</h3>'
        f'<h4 class="base-search-card__subtitle"><a href="{lg.SITE}/company/dept">{company}</a></h4>'
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
check(f"the real {len(scrape.SEARCH_TERMS)} terms become a few groups ({len(real)})", 2 <= len(real) <= 4)

print("\n-- parse_cards() --")
rows = lg.parse_cards(card(4321, "Associate Design Director") + card(99, "UX Lead", company="Acme", location="London, England, United Kingdom", posted="2026-10-25"))
check("two cards -> two rows", len(rows) == 2)
check("JobSpy-shaped row: url, company, title, location, date, description",
      rows[0] == {"job_url": lg.JOB_URL.format(id=4321), "company": "DEPT®", "title": "Associate Design Director",
                  "location": "Amsterdam, North Holland, Netherlands", "date_posted": "2026-10-26", "description": ""})
no_urn = card(555, "Design Lead").replace('data-entity-urn="urn:li:jobPosting:555"', "")
check("job id falls back to the link when the card has no urn", lg.parse_cards(no_urn)[0]["job_url"].endswith("/555"))
check("a page without job cards has no rows", lg.parse_cards(EMPTY_PAGE) == [])

print("\n-- search(): one load of the public search page --")
from urllib.parse import parse_qs, urlsplit


def query(url):
    return {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}


class Resp2(Resp):
    def __init__(self, status=200, text="", headers=None, url=""):
        super().__init__(status, text, headers)
        self.url = url


calls = []


def get_returning(resp):
    def get(url, headers=None, timeout=None):
        calls.append((url, headers))
        return resp
    return get


SIGN_IN = "<html><head><title>Sign Up | LI</title></head><body><form>join</form></body></html>"
rows, capped = lg.search(get_returning(Resp2(200, card(1, "Design Lead") + card(2, "UX Lead"))), '"design lead"', "Netherlands", 10800.4)
url, headers = calls[-1]
check("loads the search page: keywords, location, distance, window in seconds, newest first",
      url.startswith(lg.SEARCH_PAGE_URL + "?") and query(url) == {"keywords": '"design lead"', "location": "Netherlands", "distance": "50", "f_TPR": "r10800", "sortBy": "DD"})
check("every card on the page is a row; not capped", (len(rows), capped) == (2, False))
check("the first search is a typed-in navigation (no Referer)", "Referer" not in headers and headers["Sec-Fetch-Site"] == "none" and headers["Sec-Fetch-Mode"] == "navigate")
lg.search(get_returning(Resp2(200, card(1, "x"))), "k", "l", 3600, referer=lg.SEARCH_PAGE_URL + "?keywords=a")
check("later searches come from the previous search page (Referer, same-origin)",
      calls[-1][1]["Referer"] == lg.SEARCH_PAGE_URL + "?keywords=a" and calls[-1][1]["Sec-Fetch-Site"] == "same-origin")
full = "".join(card(i, f"Design Lead {i}") for i in range(1, lg.PAGE_MAX_CARDS + 1))
check(f"a full page ({lg.PAGE_MAX_CARDS} cards) is reported capped", lg.search(get_returning(Resp2(200, full)), "k", "l", 3600)[1] is True)
for status in (429, 999, 403):
    try:
        lg.search(get_returning(Resp2(status, "", {"Retry-After": "120"})), "k", "l", 3600)
        check(f"HTTP {status} raises Blocked", False)
    except lg.Blocked as b:
        check(f"HTTP {status} raises Blocked (Retry-After read: {b.wait})", b.status == status and b.wait == 120)
# The page LI served for a Kuala Lumpur search with no matches (2026-10-27
# 22:34Z run): a 200 results page, title repeating the keywords, no cards.
KL = '"principal product designer" OR "staff product designer" OR "design technologist"'
NO_MATCH = ("<html><head><title>&quot;principal Product Designer&quot; OR &quot;staff Product Designer&quot; OR "
            "&quot;design Technologist&quot; Jobs in Kuala Lumpur</title></head><body><main>0 results</main></body></html>")
check("is_results_page: the search's own page (entities, LI's capitals) yes; a sign-in page no",
      lg.is_results_page(NO_MATCH, KL) and not lg.is_results_page(SIGN_IN, KL) and not lg.is_results_page(NO_MATCH, '"design lead"'))
calls.clear()
check("a results page with no cards is no new postings ([], not capped), not a block; one request",
      lg.search(get_returning(Resp2(200, NO_MATCH)), KL, "Kuala Lumpur, Malaysia", 3600) == ([], False) and len(calls) == 1)
for label, resp in [("a 200 page without job cards (sign-in wall, bot check) is a block", Resp2(200, SIGN_IN)),
                    ("a cardless page titled for another search is a block", Resp2(200, NO_MATCH.replace("principal", "chief"))),
                    ("a redirect to the sign-in wall is a block, even with cards", Resp2(200, card(1, "x"), url=lg.SITE + "/authwall?trk=x"))]:
    try:
        lg.search(get_returning(resp), KL, "Kuala Lumpur, Malaysia", 3600)
        check(label, False)
    except lg.Blocked:
        check(label, True)
try:
    lg.search(get_returning(Resp2(500, "")), "k", "l", 3600)
    check("another status is an error, not a block", False)
except lg.Blocked:
    check("another status is an error, not a block", False)
except RuntimeError:
    check("another status is an error, not a block", True)
check("page_title reads a block page's title", lg.page_title("<html><title>\n Too  Many </title>") == "Too Many")

print("\n-- run_li(): windows, coverage, blocks, budget --")
NOW = 1_800_000_000  # fixed clock
iso = scrape._iso_utc
searches = scrape.li_searches()
keys = [scrape.li_key(*s) for s in searches]
PAUSE, BACKOFF = scrape.LI_PAUSE_SECONDS, scrape.LI_BLOCK_BACKOFF_SECONDS
# Most cases check other behaviour than the budget, so they lift it; the budget
# case restores it.
BUDGET = scrape.LI_MAX_REQUESTS_PER_RUN
scrape.LI_MAX_REQUESTS_PER_RUN = 10 * len(searches)


class FakeLI:
    """Answers every search page with one posting; the n-th request in `block_at`
        gets a 429 block page, in `wall_at` a 200 sign-in page, in `empty_at` the
        search's own results page with no match.
    """

    def __init__(self, block_at=(), wall_at=(), empty_at=()):
        self.requests, self.headers = [], []
        self.block_at, self.wall_at, self.empty_at = set(block_at), set(wall_at), set(empty_at)

    def get(self, url, headers=None, timeout=None):
        params = query(url)
        self.requests.append(params)
        self.headers.append(headers)
        n = len(self.requests)
        if n in self.block_at:
            return Resp2(429, "<html><head><title>LI: Too Many Requests</title></head></html>")
        if n in self.wall_at:
            return Resp2(200, SIGN_IN)
        if n in self.empty_at:
            return Resp2(200, f"<html><head><title>{params['keywords']} Jobs in {params['location']}</title></head></html>")
        return Resp2(200, card(n, "Design Lead", location=params["location"]))


fake = FakeLI()
sleeps = []
rows, coverage, health, log = scrape.run_li({}, get=fake.get, sleep=sleeps.append, now=lambda: NOW)
check(f"every market x keyword group searched once ({len(searches)} searches, one request each)",
      len(fake.requests) == len(searches) and health["done"] == len(searches) and health["requests"] == len(searches))
check("no coverage yet -> the first-run window (12h)", all(p["f_TPR"] == f"r{12 * 3600}" for p in fake.requests))
check("each completed search is recorded with its start time", coverage == {k: iso(NOW) for k in keys})
check("rows are tagged li", len(rows) == len(searches) and all(s == "li" for s, _ in rows))
check("human pace: a pause between searches, each within LI_PAUSE_SECONDS (a minute or more)",
      len(sleeps) == len(searches) - 1 and all(PAUSE[0] <= x <= PAUSE[1] for x in sleeps) and PAUSE[0] >= 60)
check("health: nothing blocked, all done, stalest 0h, no first block, variant None (client injected)",
      (health["blocked"], health["stoppedEarly"], health["stalestHours"], health["firstBlockRequest"], health["variant"]) == (0, False, 0.0, None, None))
check("one log entry per request: time, market, group, window, status, cards, size",
      len(log) == len(searches) and set(log[0]) == {"s", "loc", "g", "windowH", "status", "cards", "bytes"}
      and (log[0]["status"], log[0]["cards"], log[0]["windowH"]) == (200, 1, 12.0))
check("the first search has no Referer; each later one carries the previous search's page",
      "Referer" not in fake.headers[0] and all(
          query(fake.headers[i]["Referer"]) == fake.requests[i - 1] for i in range(1, len(fake.requests))))

fake = FakeLI()
cov = {k: iso(NOW - 2 * 3600) for k in keys}
cov[keys[0]] = iso(NOW - 30 * 3600)
cov[keys[1]] = iso(NOW - 30 * 86400)
cov["Gone Market|\"old\""] = iso(NOW)
rows, coverage, health, log = scrape.run_li(cov, get=fake.get, sleep=lambda s: None, now=lambda: NOW)
windows = {(p["location"], p["keywords"]): p["f_TPR"] for p in fake.requests}
check("2h since the last success -> the minimum window (3h)", windows[searches[2]] == f"r{scrape.LI_MIN_WINDOW_SECONDS}")
check("30h since -> 31h (gap + 1h margin)", windows[searches[0]] == f"r{31 * 3600}")
check("30 days since -> capped at the maximum (7 days)", windows[searches[1]] == f"r{scrape.LI_MAX_WINDOW_SECONDS}")
check("the stalest searches go first", (fake.requests[0]["location"], fake.requests[0]["keywords"]) == searches[1])
check("searches no longer configured are dropped from coverage", "Gone Market|\"old\"" not in coverage)

fake = FakeLI(block_at={3})
sleeps = []
rows, coverage, health, log = scrape.run_li({}, get=fake.get, sleep=sleeps.append, now=lambda: NOW)
check(f"one block: wait out the penalty ({BACKOFF[0]}s), retry that search once, carry on (all searches done)",
      health["done"] == len(searches) and health["blocked"] == 1 and sleeps.count(BACKOFF[0]) == 1 and not health["stoppedEarly"]
      and fake.requests[2] == fake.requests[3])
check("...the first block is recorded (request 3) with the block page's title",
      health["firstBlockRequest"] == 3 and log[2]["status"] == 429 and log[2]["blocked"] and log[2]["title"] == "LI: Too Many Requests")

fake = FakeLI(wall_at={2})
rows, coverage, health, log = scrape.run_li({}, get=fake.get, sleep=lambda s: None, now=lambda: NOW)
check("a sign-in page counts as a block (logged with its title), retried like one",
      health["blocked"] == 1 and health["done"] == len(searches) and log[1]["blocked"] and log[1]["title"] == "Sign Up | LI")

fake = FakeLI(empty_at={2, 3, 4})
sleeps = []
rows, coverage, health, log = scrape.run_li({}, get=fake.get, sleep=sleeps.append, now=lambda: NOW)
check("searches with no match: done, 0 cards, no block, no retry, no penalty wait (the 2026-10-27 22:34Z case)",
      health["done"] == len(searches) and health["blocked"] == 0 and not health["stoppedEarly"]
      and len(fake.requests) == len(searches) and max(sleeps) <= PAUSE[1] and len(rows) == len(searches) - 3
      and [log[i]["cards"] for i in (1, 2, 3)] == [0, 0, 0] and coverage == {k: iso(NOW) for k in keys})

fake = FakeLI(block_at={3, 4})
sleeps = []
cov = {k: iso(NOW - 2 * 3600) for k in keys}
rows, coverage, health, log = scrape.run_li(cov, get=fake.get, sleep=sleeps.append, now=lambda: NOW)
check("blocked again on the retry: wait again, skip that search, carry on with the rest",
      sleeps.count(BACKOFF[-1]) == 2 and health["done"] == len(searches) - 1 and not health["stoppedEarly"])
check("...the skipped search keeps its old coverage time", sum(1 for v in coverage.values() if v == iso(NOW - 2 * 3600)) == 1)

fake = FakeLI(block_at=set(range(3, 200)))
sleeps = []
rows, coverage, health, log = scrape.run_li(cov, get=fake.get, sleep=sleeps.append, now=lambda: NOW)
check(f"{scrape.LI_MAX_BLOCKS_IN_A_ROW} blocks in a row: LI stops for this run",
      health["stoppedEarly"] and health["blocked"] == scrape.LI_MAX_BLOCKS_IN_A_ROW and len(fake.requests) == 2 + scrape.LI_MAX_BLOCKS_IN_A_ROW)
check("...a penalty wait after each block but the last", [x for x in sleeps if x > PAUSE[1]] == [BACKOFF[-1]] * (scrape.LI_MAX_BLOCKS_IN_A_ROW - 1))
check("...the 2 searches done keep the new time, the rest their old one",
      sum(1 for v in coverage.values() if v == iso(NOW)) == 2 and sum(1 for v in coverage.values() if v == iso(NOW - 2 * 3600)) == len(keys) - 2)
check("...health reports it", (health["done"], health["stalestHours"], health["firstBlockRequest"]) == (2, 2.0, 3))

fake = FakeLI(block_at={1, 2, 3})
rows, coverage, health, log = scrape.run_li({}, get=fake.get, sleep=lambda s: None, now=lambda: NOW)
check("an address penalised from the start costs 3 requests, then LI stops for the run",
      len(fake.requests) == 3 and health["stoppedEarly"] and health["done"] == 0)


class RetryAfter(FakeLI):
    def get(self, url, headers=None, timeout=None):
        self.requests.append(query(url))
        if len(self.requests) == 1:
            return Resp2(429, "", {"Retry-After": "999"})
        return Resp2(200, card(len(self.requests), "Design Lead"))
fake = RetryAfter()
sleeps = []
scrape.run_li({}, get=fake.get, sleep=sleeps.append, now=lambda: NOW)
check("a Retry-After is honoured, capped at LI_MAX_BLOCK_WAIT_SECONDS", scrape.LI_MAX_BLOCK_WAIT_SECONDS in sleeps)

scrape.LI_MAX_REQUESTS_PER_RUN = 5
fake = FakeLI()
rows, coverage, health, log = scrape.run_li({}, get=fake.get, sleep=lambda s: None, now=lambda: NOW)
check("the request budget ends the run's LI part; the rest wait (never covered -> stalestHours None)",
      len(fake.requests) == 5 and health["done"] == 5 and health["stalestHours"] is None and not health["stoppedEarly"])
scrape.LI_MAX_REQUESTS_PER_RUN = BUDGET
check(f"the real budget ({BUDGET}) covers every search ({len(searches)}) with room for retries",
      BUDGET >= len(searches))
check("...and at the human pace fits well inside the 2h cadence (< 60 min of pauses)",
      BUDGET * PAUSE[1] < 60 * 60)

print("\n-- open_session(): both client variants build --")
for variant in lg.VARIANTS:
    try:
        get = lg.open_session(variant)
        check(f"{variant!r} gives a get()", callable(get))
    except ImportError as e:
        check(f"{variant!r} gives a get() ({e})", False)

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
