"""Tests for hire_helsinki.py with a fake feed (no network). Run: python3 test_hire_helsinki.py"""
import sys

from hire_helsinki import PAGE_SIZE, scrape_hire_helsinki
from scrape import market_for_location, SEARCHED_MARKETS, CANONICAL_MARKETS

failures = 0


def check(name, got, want):
    global failures
    ok = got == want
    if not ok:
        failures += 1
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"\n   got:  {got!r}\n   want: {want!r}"))


class Resp:
    def __init__(self, status, payload=None, text=False):
        self.status_code, self._payload, self._text = status, payload, text

    def json(self):
        if self._text:
            raise ValueError("no json")
        return self._payload


def job(i, title="UX Designer", name="Nomentia", city="Espoo"):
    return {"title": title, "employer": {"name": name, "city": city, "imageUrl": ""},
            "expireDate": "2026-12-12T22:00:00.000Z",
            "externalUrl": f"https://tyomarkkinatori.fi/en/personal-customers/vacancies/{i}"}


def feed(pages):
    calls = []

    def get(url, params=None, headers=None, timeout=None):
        calls.append(dict(params))
        p = params["page"]
        return pages[p - 1] if p <= len(pages) else Resp(200, {"totalJobs": 0, "totalPages": len(pages), "jobs": []})
    return get, calls


print("-- reads every page, maps fields --")
p1 = Resp(200, {"totalJobs": 3, "totalPages": 2, "jobs": [job(1), job(2, "Brand Designer &amp; Illustrator", "Zero", "Helsinki")]})
p2 = Resp(200, {"totalJobs": 3, "totalPages": 2, "jobs": [job(3, "Product Manager", "Smartly", "")]})
get, calls = feed([p1, p2])
rows, health = scrape_hire_helsinki(get=get, sleep=lambda s: None)
check("2 pages requested", [c["page"] for c in calls], [1, 2])
check("page size and cities sent", (calls[0]["limit"], calls[0]["city"]), (PAGE_SIZE, "helsinki,espoo,vantaa"))
check("3 rows, tagged hirehelsinki", [s for s, _ in rows], ["hirehelsinki"] * 3)
r = rows[1][1]
check("title unescaped", r["title"], "Brand Designer & Illustrator")
check("company and location", (r["company"], r["location"]), ("Zero", "Helsinki, Finland"))
check("no city -> Finland", rows[2][1]["location"], "Finland")
check("no posting date", r["date_posted"], None)
check("health", health, {"rows": 3, "pages": 2, "total": 3, "error": None})

print("-- duplicates and bad jobs skipped --")
get, _ = feed([Resp(200, {"totalJobs": 3, "totalPages": 1, "jobs": [job(1), job(1), {"title": "", "externalUrl": "x"}]})])
rows, health = scrape_hire_helsinki(get=get, sleep=lambda s: None)
check("one row", len(rows), 1)

print("-- a blocked or failing page is reported, rows kept --")
get, _ = feed([Resp(200, {"totalJobs": 100, "totalPages": 2, "jobs": [job(1)]}), Resp(403)])
rows, health = scrape_hire_helsinki(get=get, sleep=lambda s: None)
check("first page's row kept", len(rows), 1)
check("error on page 2", health["error"], "page 2: HTTP 403")
get, _ = feed([Resp(200, text=True)])
rows, health = scrape_hire_helsinki(get=get, sleep=lambda s: None)
check("challenge page (not JSON) reported", (len(rows), health["error"]), (0, "page 1: not JSON (blocked or changed)"))

def boom(*a, **k):
    raise ConnectionError("down")
rows, health = scrape_hire_helsinki(get=boom, sleep=lambda s: None)
check("network failure reported", health["error"], "page 1: down")

print("-- markets: Finland accepted, not searched; Japan neither --")
check("Espoo -> Finland", market_for_location("Espoo, Finland"), "Finland")
check("Vantaa alone -> Finland", market_for_location("Vantaa"), "Finland")
check("Finland not searched", "Finland" in SEARCHED_MARKETS, False)
check("Finland accepted", "Finland" in CANONICAL_MARKETS, True)
check("Tokyo dropped", market_for_location("Tokyo, Japan"), None)

print(f"\n{'all passed' if not failures else str(failures) + ' FAILED'}")
sys.exit(1 if failures else 0)
