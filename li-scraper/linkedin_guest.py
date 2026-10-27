"""
LinkedIn's public (logged-out) job search, read directly instead of through JobSpy.

How LinkedIn treats GitHub's runners (R&D 2026-10-26/27, from per-request logs):
  - its results feed (jobs-guest/.../seeMoreJobPostings, 10 cards a request, what
    JobSpy and this client used to call) allows a fresh address ~5 requests 10-13 s
    apart, then 429s; once penalised, single requests minutes apart mostly fail
    too, and some runner addresses arrive already penalised;
  - in the 2026-10-27 12:4xZ run, the public search page (/jobs/search) answered
    200 while the feed refused the same address a minute later, and again after 5
    minutes: the two are limited separately;
  - the search page is server-rendered with every matching card, up to ~60
    (checked 2026-10-27: 55 of 55 in one page, no extra calls). With no match it
    fills in with unrelated recent jobs in that market, so a page without job
    cards is a sign-in wall or bot check, never "no results".
So each search is ONE request for the public search page, read like a person
browsing (scrape.py's LinkedIn constants: a minute or more between searches, a
capped number per run, a 5-minute wait before one retry after a block):
  - keywords are combined with OR ('"product manager" OR "product owner"'), so the
    search terms become a few groups (keyword_groups);
  - the time window (f_TPR, any number of seconds) covers only the time since that
    search last succeeded, plus a margin, so a page rarely fills up; a full page is
    reported as capped (its oldest postings in the window may be missing);
  - searches not completed keep their old "covered until" time, so the next run
    widens their window and nothing is lost;
  - after the first search, each request carries the previous search page as its
    Referer, as a visitor changing the search would;
  - two clients are tried, one per run, chosen at random and recorded in the run's
    history (open_session): plain `requests`, and curl_cffi impersonating Chrome,
    whose TLS and HTTP/2 fingerprint matches a real browser rather than Python's.
Every request is logged into the snapshot (scrape.py), so blocking patterns can be
read across many runs rather than guessed from one.

Page: GET https://www.linkedin.com/jobs/search
  keywords, location, distance (JobSpy's default, kept), f_TPR=r<seconds>, sortBy=DD.
Card markup (verified 2026-10-26/27): div.base-search-card[data-entity-urn=
  "urn:li:jobPosting:<id>"], h3.base-search-card__title, h4.base-search-card__subtitle,
  span.job-search-card__location, time[datetime].
"""
import re
import sys

from bs4 import BeautifulSoup

SEARCH_PAGE_URL = "https://www.linkedin.com/jobs/search"
JOB_URL = "https://www.linkedin.com/jobs/view/{id}"
PAGE_MAX_CARDS = 60  # the page's own limit (55 of 55 seen in one page); a full page is "capped"
DISTANCE_MILES = 50
MAX_PHRASES_PER_GROUP = 10
REQUEST_TIMEOUT_SECONDS = 30
BLOCK_STATUSES = (403, 429, 999)
VARIANTS = ("requests", "chrome")  # see open_session
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"
)
# Loading a search page (a navigation). The first one is typed in (no Referer);
# later ones come from the previous search page (search() adds Referer).
PAGE_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
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


class Blocked(Exception):
    """LinkedIn refused a request (rate limit or bot check). `wait` is its
        Retry-After in seconds, when it gave one.
    """

    def __init__(self, status, wait=None):
        super().__init__(f"HTTP {status}")
        self.status = status
        self.wait = wait


def search_url(keywords, location, window_seconds):
    """The public search page for one search: newest first, posted within the window."""
    from urllib.parse import urlencode
    return SEARCH_PAGE_URL + "?" + urlencode({
        "keywords": keywords,
        "location": location,
        "distance": DISTANCE_MILES,
        "f_TPR": f"r{int(window_seconds)}",
        "sortBy": "DD",
    })


def search(get, keywords, location, window_seconds, referer=None):
    """Every posting for one (keywords, location) within the window, from one load
        of the public search page. Returns (rows, capped): capped when the page is
        full, so older postings in the window may be missing (logged). Raises
        Blocked when LinkedIn refuses: a block status, a redirect to its sign-in
        wall, or a page without job cards.
    """
    headers = dict(PAGE_HEADERS)
    if referer:
        headers.update({"Referer": referer, "Sec-Fetch-Site": "same-origin"})
    resp = get(search_url(keywords, location, window_seconds), headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
    if resp.status_code in BLOCK_STATUSES:
        retry_after = (resp.headers.get("Retry-After") or "").strip()
        raise Blocked(resp.status_code, int(retry_after) if retry_after.isdigit() else None)
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}")
    rows = parse_cards(resp.text) if "authwall" not in str(getattr(resp, "url", "")) else []
    if not rows:
        raise Blocked(resp.status_code)
    capped = len(rows) >= PAGE_MAX_CARDS
    if capped:
        print(f"[linkedin] {location!r}: page full ({len(rows)}); older postings in the window may be missing", file=sys.stderr)
    return rows, capped
