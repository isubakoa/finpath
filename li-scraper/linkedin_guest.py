"""
LinkedIn's public (logged-out) job search, read directly instead of through JobSpy.

Why (R&D 2026-10-26, after a run lost 48 of 114 LinkedIn searches to HTTP 429):
  - LinkedIn throttles bursts on this endpoint from any IP, home connections
    included (a residential browser got 429 after 3-4 quick requests), and is
    stricter still with cloud IPs such as GitHub's runners. Request volume and
    spacing are what decide whether a run gets through.
  - JobSpy 1.4.1 asks for 10 results per request, so each 20-result search was 2
    requests, and its 10-day window re-fetched known postings every time:
    ~230-460 LinkedIn requests per run.
  - This client cuts that to roughly one request per (keyword group, market):
      * keywords are combined with OR ('"product manager" OR "product owner"'),
        which the guest search honours, so the search terms become a few groups;
      * the time window (f_TPR, any number of seconds) covers only the time since
        that search last succeeded, plus a margin, so a page rarely fills up;
      * pages are spaced out, and a search reads at most MAX_PAGES_PER_SEARCH
        pages: blocks in the first runs (2026-10-26/27) hit while paging 3-7 pages
        deep, and JobSpy, which got ~58% of its searches through from the same
        runners, never read past page 2;
      * a block is backed off and the run carries on (scrape.py run_linkedin);
        searches not completed keep their old "covered until" time, so the next
        run widens their window and nothing is lost.
  Every request is logged into the snapshot (scrape.py), so blocking patterns can
  be read across many runs rather than guessed from one.

Human pace (2026-10-27, from the 06:46Z run's per-request log): a fresh address
gets a burst of ~5 requests 10-13 s apart, then 429s; once penalised, a retry 60 s
later fails but a single request after 2-4 min gets through, and the next one
12 s after it fails again. Some runner addresses arrive already penalised. So a
run now behaves like one person browsing (scrape.py's LinkedIn constants): a
minute or more between requests, ~30 requests at most, a 5-minute wait before a
single probe after a block. It also looks more like a browser:
  - the public search page is loaded first (warm_up), which sets LinkedIn's
    session cookies, and later requests carry it as the Referer, the way the
    page's own "see more jobs" calls do;
  - two clients are tried, one per run, chosen at random and recorded in the
    run's history (open_session): plain `requests`, and curl_cffi impersonating
    Chrome, whose TLS and HTTP/2 fingerprint matches a real browser rather than
    Python's. The history shows which gets through more often.

Endpoint: GET https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search
  keywords, location, distance (JobSpy's default, kept), f_TPR=r<seconds>,
  sortBy=DD, start (pages of 10).
  Returns an HTML fragment of <li> cards; an empty result is a near-empty page.
Card markup (verified 2026-10-26): div.base-search-card[data-entity-urn=
  "urn:li:jobPosting:<id>"], h3.base-search-card__title, h4.base-search-card__subtitle,
  span.job-search-card__location, time[datetime].
"""
import re
import sys

from bs4 import BeautifulSoup

SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
SEARCH_PAGE_URL = "https://www.linkedin.com/jobs/search"  # the public page that calls SEARCH_URL
JOB_URL = "https://www.linkedin.com/jobs/view/{id}"
PAGE_SIZE = 10
MAX_PAGES_PER_SEARCH = 3  # 30 postings, newest first; a busier window skips its oldest (logged)
DISTANCE_MILES = 50
MAX_PHRASES_PER_GROUP = 10
REQUEST_TIMEOUT_SECONDS = 20
BLOCK_STATUSES = (403, 429, 999)
VARIANTS = ("requests", "chrome")  # see open_session
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"
)
# Loading the search page (a navigation).
PAGE_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Upgrade-Insecure-Requests": "1",
}
# The page's own result calls (fetch from the page). Referer is added per search.
API_HEADERS = {
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}


def open_session(variant):
    """A session's get() for one client variant:
        "requests" - Python requests with a Chrome User-Agent;
        "chrome"   - curl_cffi impersonating Chrome (its User-Agent, header order,
                     TLS and HTTP/2 fingerprint; it sets the User-Agent itself).
        Both keep cookies across requests.
    """
    if variant == "chrome":
        from curl_cffi import requests as cffi_requests
        return cffi_requests.Session(impersonate="chrome").get
    import requests
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    return session.get


def search_page_params(keywords, location):
    return {"keywords": keywords, "location": location, "distance": DISTANCE_MILES}


def referer(keywords, location):
    """The search page URL a browser would be on for this search."""
    from urllib.parse import urlencode
    return SEARCH_PAGE_URL + "?" + urlencode(search_page_params(keywords, location))


def warm_up(get, keywords, location):
    """Loads the public search page once, as a visitor would before the page asks
        for more results, so the session holds LinkedIn's cookies. Returns the HTTP
        status (0 when the request failed); a failure doesn't stop the run.
    """
    try:
        resp = get(SEARCH_PAGE_URL, params=search_page_params(keywords, location),
                   headers=PAGE_HEADERS, timeout=REQUEST_TIMEOUT_SECONDS)
    except Exception as e:  # noqa: BLE001 — the searches can still be tried without it
        print(f"[linkedin] warm-up failed: {type(e).__name__}: {e}", file=sys.stderr)
        return 0
    return resp.status_code


def page_title(html):
    """<title> of a page, for logging what a block page says (≤80 chars)."""
    m = re.search(r"<title[^>]*>(.*?)</title>", html or "", flags=re.S | re.I)
    return re.sub(r"\s+", " ", m.group(1)).strip()[:80] if m else ""


def keyword_groups(terms, max_phrases=MAX_PHRASES_PER_GROUP):
    """The search terms as a few OR queries. A term containing another term as
        whole words is dropped ("Senior Product Manager" is found by "Product
        Manager"), then the rest are packed in order into groups.
    """
    phrases = []
    lowered = [t.strip().lower() for t in terms if t.strip()]
    for t in lowered:
        if t in phrases:
            continue
        if any(o != t and re.search(r"(^|\s)" + re.escape(o) + r"($|\s)", t) for o in lowered):
            continue
        phrases.append(t)
    groups = [phrases[i:i + max_phrases] for i in range(0, len(phrases), max_phrases)]
    return [" OR ".join(f'"{p}"' for p in g) for g in groups]


def parse_cards(html):
    """Job cards in one result page -> JobSpy-shaped rows (what build_fresh_roles reads)."""
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for card in soup.select(".base-search-card"):
        urn = card.get("data-entity-urn") or ""
        job_id = urn.rsplit(":", 1)[-1] if urn else ""
        if not job_id.isdigit():
            link = card.select_one("a.base-card__full-link")
            m = re.search(r"-(\d+)(?:\?|$)", link.get("href", "")) if link else None
            job_id = m.group(1) if m else ""
        title = card.select_one(".base-search-card__title")
        company = card.select_one(".base-search-card__subtitle")
        location = card.select_one(".job-search-card__location")
        posted = card.select_one("time")
        if not job_id or not title:
            continue
        rows.append({
            "job_url": JOB_URL.format(id=job_id),
            "company": company.get_text(" ", strip=True) if company else "",
            "title": title.get_text(" ", strip=True),
            "location": location.get_text(" ", strip=True) if location else "",
            "date_posted": posted.get("datetime") if posted else None,
            "description": "",
        })
    return rows


def _looks_empty(html):
    """LinkedIn's "no results" answer: a page with no markup worth the name."""
    return len(re.sub(r"<!--.*?-->|<!DOCTYPE[^>]*>|\s", "", html or "", flags=re.S)) < 40


class Blocked(Exception):
    """LinkedIn refused a request (rate limit or bot check). `wait` is its
        Retry-After in seconds, when it gave one.
    """

    def __init__(self, status, wait=None):
        super().__init__(f"HTTP {status}")
        self.status = status
        self.wait = wait


def fetch_page(get, keywords, location, window_seconds, start):
    """One result page -> rows. Raises Blocked when LinkedIn refuses."""
    params = {
        "keywords": keywords,
        "location": location,
        "distance": DISTANCE_MILES,
        "f_TPR": f"r{int(window_seconds)}",
        "sortBy": "DD",
        "start": start,
    }
    headers = dict(API_HEADERS, Referer=referer(keywords, location))
    resp = get(SEARCH_URL, params=params, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
    if resp.status_code in BLOCK_STATUSES:
        retry_after = resp.headers.get("Retry-After", "")
        raise Blocked(resp.status_code, int(retry_after) if retry_after.isdigit() else None)
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}")
    rows = parse_cards(resp.text)
    if not rows and not _looks_empty(resp.text):
        # A 200 with markup but no job cards: a challenge or login wall.
        raise Blocked(resp.status_code)
    return rows


def search(get, keywords, location, window_seconds, pause, max_pages=MAX_PAGES_PER_SEARCH):
    """Every posting for one (keywords, location) within the window, page by page,
        pause() between pages. Returns (rows, requests_made, capped). Past
        max_pages the oldest postings in the window are skipped (capped=True,
        logged) rather than retried forever. Blocked propagates to the caller, with
        the rows so far on the exception (`rows`, `requests`).
    """
    rows, seen, requests_made = [], set(), 0
    for page in range(max_pages):
        if page:
            pause()
        try:
            page_rows = fetch_page(get, keywords, location, window_seconds, page * PAGE_SIZE)
        except Blocked as b:
            b.rows, b.requests = rows, requests_made + 1
            raise
        requests_made += 1
        new = [r for r in page_rows if r["job_url"] not in seen]
        seen.update(r["job_url"] for r in new)
        rows.extend(new)
        if len(page_rows) < PAGE_SIZE or not new:
            return rows, requests_made, False
    print(f"[linkedin] {location!r}: page cap ({max_pages}) reached; older postings in the window skipped", file=sys.stderr)
    return rows, requests_made, True
