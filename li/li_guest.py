import html as html_lib
import re
import sys

from bs4 import BeautifulSoup

SITE = "https://www.linkedin.com"
SEARCH_PAGE_URL = SITE + "/jobs/search"
JOB_URL = SITE + "/jobs/view/{id}"
PAGE_MAX_CARDS = 60
DISTANCE_MILES = 50
MAX_PHRASES_PER_GROUP = 10
REQUEST_TIMEOUT_SECONDS = 30
BLOCK_STATUSES = (403, 429, 999)
VARIANTS = ("requests", "chrome")
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"
)
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
    if variant == "chrome":
        from curl_cffi import requests as cffi_requests
        return cffi_requests.Session(impersonate="chrome").get
    import requests
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    return session.get


def page_title(html):
    m = re.search(r"<title[^>]*>(.*?)</title>", html or "", flags=re.S | re.I)
    return re.sub(r"\s+", " ", m.group(1)).strip()[:80] if m else ""


def is_results_page(html, keywords):
    m = re.search(r"<title[^>]*>(.*?)</title>", html or "", flags=re.S | re.I)
    title = re.sub(r"\s+", " ", html_lib.unescape(m.group(1))).lower() if m else ""
    first = keywords.split(" OR ")[0].strip().strip('"').lower()
    return bool(first) and first in title


def keyword_groups(terms, max_phrases=MAX_PHRASES_PER_GROUP):
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

    def __init__(self, status, wait=None):
        super().__init__(f"HTTP {status}")
        self.status = status
        self.wait = wait


def search_url(keywords, location, window_seconds):
    from urllib.parse import urlencode
    return SEARCH_PAGE_URL + "?" + urlencode({
        "keywords": keywords,
        "location": location,
        "distance": DISTANCE_MILES,
        "f_TPR": f"r{int(window_seconds)}",
        "sortBy": "DD",
    })


def search(get, keywords, location, window_seconds, referer=None):
    headers = dict(PAGE_HEADERS)
    if referer:
        headers.update({"Referer": referer, "Sec-Fetch-Site": "same-origin"})
    resp = get(search_url(keywords, location, window_seconds), headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)
    if resp.status_code in BLOCK_STATUSES:
        retry_after = (resp.headers.get("Retry-After") or "").strip()
        raise Blocked(resp.status_code, int(retry_after) if retry_after.isdigit() else None)
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}")
    if "authwall" in str(getattr(resp, "url", "")):
        raise Blocked(resp.status_code)
    rows = parse_cards(resp.text)
    if not rows:
        if is_results_page(resp.text, keywords):
            return [], False
        raise Blocked(resp.status_code)
    capped = len(rows) >= PAGE_MAX_CARDS
    if capped:
        print(f"[li] {location!r}: page full ({len(rows)}); older postings in the window may be missing", file=sys.stderr)
    return rows, capped
