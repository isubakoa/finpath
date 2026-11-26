"""
Shared plumbing for the Talent Hubs readers: HTTP calls that fail loudly, a
row builder in the JobSpy shape scrape.py expects, and Collector, which pages
through a portal, drops duplicate links and records the first error.

A reader never raises: a refused or failed page ends that reader's run, keeps
the rows already read, and is reported in its health dict (Settings › Job sites).
"""
import html
import re
import sys
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

REQUEST_TIMEOUT_SECONDS = 25
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)


def request(http, method, url, *, expect="json", headers=None, **kwargs):
    """One call through `http` (the requests module, or a test fake with
        get/post). Returns parsed JSON or text. Raises RuntimeError with a short
        reason on an HTTP error or an answer that isn't the expected kind (a
        bot-wall page instead of JSON).
    """
    all_headers = {"User-Agent": USER_AGENT, "Accept": "application/json" if expect == "json" else "text/html"}
    all_headers.update(headers or {})
    resp = getattr(http, method)(url, headers=all_headers, timeout=REQUEST_TIMEOUT_SECONDS, **kwargs)
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}")
    if expect == "text":
        return resp.text
    try:
        return resp.json()
    except ValueError:
        raise RuntimeError("not JSON (blocked or changed)") from None


def clean(value):
    """Plain, unescaped, single-spaced text from a feed field."""
    if value is None:
        return ""
    return " ".join(html.unescape(str(value)).split())


def place(city, country):
    """"City, Country", or just the country when there's no city (or the city
        field repeats the country).
    """
    city = clean(city).strip(" ,\u3164")  # U+3164: a blank-looking filler seen on Work in Estonia
    if not city or city.lower() == country.lower() or not any(ch.isalpha() for ch in city):
        return country
    return f"{city}, {country}"


def strip_tracking(url):
    """The link without utm_* parameters, so the same ad found twice matches."""
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not k.lower().startswith("utm_")]
    return urlunsplit(parts._replace(query=urlencode(query)))


def epoch_date(value):
    """'YYYY-MM-DD' from a Unix timestamp, or None."""
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def iso_date(value):
    """'YYYY-MM-DD' from an ISO-ish date string, or None."""
    s = clean(value)
    return s[:10] if len(s) >= 10 and s[4] == "-" and s[7] == "-" else None


def make_row(url, company, title, location, date_posted=None, description=""):
    """A JobSpy-shaped row, or None without a title or an http(s) link. The
        description (HTML or text) only feeds scrape.py's sponsorship phrases.
    """
    url, title = clean(url), clean(title)
    if not title or not url.startswith("http"):
        return None
    return {
        "job_url": strip_tracking(url),
        "company": clean(company),
        "title": title,
        "location": location,
        "date_posted": date_posted,
        "description": clean(re.sub(r"<[^>]+>", " ", description or "")),
    }


class Collector:
    """Rows from one portal, deduplicated by link, plus its health report."""

    def __init__(self, hub_id):
        self.hub_id = hub_id
        self.rows, self._seen = [], set()
        self.pages, self.total, self.error = 0, None, None

    def add(self, row):
        if row and row["job_url"] not in self._seen:
            self._seen.add(row["job_url"])
            self.rows.append(row)

    def run(self, fetch, *, sleep, pause, max_pages, start=1, label=""):
        """Calls fetch(page) for page = start, start+1, ... until it returns
            more=False or max_pages is reached. fetch returns (rows, total, more);
            `total` (the portal's own count) is kept from the first unlabelled
            call. The first exception stops this run and is recorded. Returns
            False when it stopped on an error.
        """
        for page in range(start, start + max_pages):
            try:
                rows, total, more = fetch(page)
            except Exception as e:  # noqa: BLE001 -- one bad call must not kill the run
                self.fail(f"{label}page {page - start + 1}: {e}")
                return False
            self.pages += 1
            if not label and self.total is None and isinstance(total, int):
                self.total = total
            for row in rows:
                self.add(row)
            if not more:
                break
            sleep(pause)
        return True

    def fail(self, message):
        if self.error is None:
            self.error = message
        print(f"[{self.hub_id}] {message}", file=sys.stderr)

    def health(self):
        return {"rows": len(self.rows), "pages": self.pages, "total": self.total, "error": self.error}
