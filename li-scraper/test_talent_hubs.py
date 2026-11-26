"""Tests for the Talent Hubs readers (hubs/) with fake portals, no network.
Run: python3 test_talent_hubs.py"""
import json
import os
import sys
import tempfile

from hubs import HUB_IDS, HUBS, hubs_off, run_talent_hubs
from hubs import common, gothenburg, hire_helsinki, skane, south_holland, welcome_to_nl, work_in_austria, \
    work_in_estonia, workindenmark
from scrape import CANONICAL_MARKETS, SEARCHED_MARKETS, SOURCE_PRECEDENCE, market_for_location

failures = 0
NO_SLEEP = lambda s: None  # noqa: E731


def check(name, got, want):
    global failures
    ok = got == want
    if not ok:
        failures += 1
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"\n   got:  {got!r}\n   want: {want!r}"))


class Resp:
    def __init__(self, status=200, payload=None, text=None):
        self.status_code, self._payload, self.text = status, payload, text if text is not None else ""

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class FakeHttp:
    """get/post that answer from answer(method, url, kwargs) and record calls."""

    def __init__(self, answer):
        self.answer, self.calls = answer, []

    def _call(self, method, url, **kw):
        self.calls.append((method, url, kw))
        return self.answer(method, url, kw)

    def get(self, url, **kw):
        return self._call("get", url, **kw)

    def post(self, url, **kw):
        return self._call("post", url, **kw)


print("-- common --")
check("place: city + country", common.place("Tallinn", "Estonia"), "Tallinn, Estonia")
check("place: city repeats the country", common.place("Estonia", "Estonia"), "Estonia")
check("place: blank filler", common.place("ㅤ", "Estonia"), "Estonia")
check("strip utm", common.strip_tracking("https://cv.ee/vacancy/1?utm_source=x&id=2&utm_medium=y"),
      "https://cv.ee/vacancy/1?id=2")
check("epoch date", common.epoch_date(1795132800), "2026-11-20")
check("iso date", common.iso_date("2026-11-26T00:00:00+01:00"), "2026-11-26")
check("row needs a title and link", (common.make_row("x", "A", "T", "L"), common.make_row("https://a", "A", "", "L")),
      (None, None))
check("description loses HTML", common.make_row("https://a", "A", "T", "L", None, "<p>Visa&nbsp;sponsorship</p>")["description"],
      "Visa sponsorship")

print("-- Hire Helsinki --")


def helsinki_answer(pages):
    def answer(method, url, kw):
        p = kw["params"]["page"]
        return pages[p - 1] if p <= len(pages) else Resp(200, {"totalJobs": 0, "totalPages": len(pages), "jobs": []})
    return answer


def hh_job(i, title="UX Designer", name="Nomentia", city="Espoo"):
    return {"title": title, "employer": {"name": name, "city": city},
            "externalUrl": f"https://tyomarkkinatori.fi/en/vacancies/{i}"}


http = FakeHttp(helsinki_answer([
    Resp(200, {"totalJobs": 3, "totalPages": 2, "jobs": [hh_job(1), hh_job(2, "Brand Designer &amp; Illustrator", "Zero", "Helsinki")]}),
    Resp(200, {"totalJobs": 3, "totalPages": 2, "jobs": [hh_job(3, "Product Manager", "Smartly", "")]})]))
rows, health = hire_helsinki.read(http=http, sleep=NO_SLEEP)
check("2 pages, cities sent", ([c[2]["params"]["page"] for c in http.calls], http.calls[0][2]["params"]["city"]),
      ([1, 2], "helsinki,espoo,vantaa"))
check("title unescaped, location", (rows[1]["title"], rows[1]["location"]), ("Brand Designer & Illustrator", "Helsinki, Finland"))
check("no city -> Finland", rows[2]["location"], "Finland")
check("health", health, {"rows": 3, "pages": 2, "total": 3, "error": None})
http = FakeHttp(helsinki_answer([Resp(200, {"totalJobs": 100, "totalPages": 2, "jobs": [hh_job(1)]}), Resp(403)]))
rows, health = hire_helsinki.read(http=http, sleep=NO_SLEEP)
check("refused page 2: row kept, error", (len(rows), health["error"]), (1, "page 2: HTTP 403"))
rows, health = hire_helsinki.read(http=FakeHttp(lambda m, u, k: Resp(200, text="<html>Just a moment</html>")), sleep=NO_SLEEP)
check("challenge page reported", health["error"], "page 1: not JSON (blocked or changed)")


def boom(*a, **k):
    raise ConnectionError("down")


rows, health = hire_helsinki.read(http=FakeHttp(boom), sleep=NO_SLEEP)
check("network failure reported", health["error"], "page 1: down")

print("-- Welcome to NL --")
wn_result = {"title": {"raw": "Senior UX Designer"}, "url": {"raw": "https://emp.test/1"},
             "company_name": {"raw": "Adyen"}, "locations": {"raw": ["Amsterdam"]},
             "created_at": {"raw": "2026-11-20T10:00:00.000Z"}}
http = FakeHttp(lambda m, u, k: Resp(200, {"results": [wn_result]}))
rows, health = welcome_to_nl.read(http=http, sleep=NO_SLEEP, terms=["UX Designer", "Product Manager"])
check("one call per term (short page ends it)", len(http.calls), 2)
check("auth header and query", (http.calls[0][2]["headers"]["Authorization"].startswith("Bearer search-"),
                                http.calls[1][2]["json"]["query"]), (True, "Product Manager"))
check("row", (rows[0]["company"], rows[0]["location"], rows[0]["date_posted"]), ("Adyen", "Amsterdam", "2026-11-20"))
check("duplicate across terms dropped", health["rows"], 1)
http = FakeHttp(lambda m, u, k: Resp(500) if k["json"]["query"] == "A" else Resp(200, {"results": [wn_result]}))
rows, health = welcome_to_nl.read(http=http, sleep=NO_SLEEP, terms=["A", "B"])
check("a failed term doesn't stop the others", (len(rows), health["error"]), (1, "'A' page 1: HTTP 500"))

print("-- Work in South Holland (Getro) --")


def getro_answer(method, url, kw):
    body = kw["json"]
    if body["query"] != "designer":
        return Resp(200, {"results": {"jobs": [], "count": 0}})
    jobs = [{"title": f"Product Designer {body['page']}-{i}", "organization": {"name": "Mendix", "slug": "mendix"},
             "locations": ["Rotterdam, Netherlands"], "created_at": 1795132800, "slug": f"{body['page']}{i}-x",
             "url": None if i == 0 else f"https://careers.mendix.test/{body['page']}-{i}"} for i in range(20)]
    return Resp(200, {"results": {"jobs": jobs if body["page"] < 2 else jobs[:5], "count": 45}})


http = FakeHttp(getro_answer)
rows, health = south_holland.read(http=http, sleep=NO_SLEEP)
designer_calls = [c for c in http.calls if c[2]["json"]["query"] == "designer"]
check("pages 0-2 for 45 hits", [c[2]["json"]["page"] for c in designer_calls], [0, 1, 2])
check("every query searched", [c[2]["json"]["query"] for c in http.calls if c[2]["json"]["page"] == 0], list(south_holland.QUERIES))
check("rows, location, date", (len(rows), rows[1]["location"], rows[1]["date_posted"]), (45, "Rotterdam, Netherlands", "2026-11-20"))
check("no employer url -> board link", rows[0]["job_url"], "https://jobs.workinsouthholland.nl/companies/mendix/jobs/00-x")

print("-- Work in Estonia --")


def estonia_answer(method, url, kw):
    page = kw["data"]["paged"]
    if page > 2:
        return Resp(200, {"status": "success", "html": '<div class="filtered-jobs__empty">No jobs</div>'})
    cards = "".join(
        f'<div class="card-job"><a class="card-job__link" href="https://cv.ee/vacancy/{page}{i}?utm_source=workinestonia"></a>'
        f'<div class="card-job__city">{"Tallinn" if i else "Estonia"}</div><div class="card-job__slide-title">Product Designer {page}{i}</div>'
        f'<div class="card-job__company">Bolt</div></div>' for i in range(12))
    return Resp(200, {"status": "success", "html": cards})


http = FakeHttp(estonia_answer)
rows, health = work_in_estonia.read(http=http, sleep=NO_SLEEP)
check("POST action, pages until empty", ([c[2]["data"]["action"] for c in http.calls][0], len(http.calls)), ("filter_job_offers", 3))
check("rows, utm stripped, city", (len(rows), rows[1]["job_url"], rows[1]["location"], rows[0]["location"]),
      (24, "https://cv.ee/vacancy/11", "Tallinn, Estonia", "Estonia"))
rows, health = work_in_estonia.read(http=FakeHttp(lambda m, u, k: Resp(200, {"status": "error"})), sleep=NO_SLEEP)
check("unexpected answer reported", health["error"], "page 1: unexpected answer")

print("-- Work in Austria --")


def austria_answer(method, url, kw):
    page = kw["params"]["tx_solr[page]"]
    docs = [{"title": f"Senior UX/UI Specialist {page}-{i}", "businessCompanyName_textS": "Dynatrace",
             "cities_stringM": ["Linz"] if i else None, "businessCity_stringS": "Wien", "published_stringS": "2026-11-26",
             "content": "We offer relocation support", "url": f"/en/employees/jobs/jobdetail/{page}{i}/x"} for i in range(100)]
    return Resp(200, {"searchResults": docs if page < 2 else docs[:50], "allResultCount": 150})


http = FakeHttp(austria_answer)
rows, health = work_in_austria.read(http=http, sleep=NO_SLEEP)
check("2 pages for 150", [c[2]["params"]["tx_solr[page]"] for c in http.calls], [1, 2])
check("row", (rows[1]["job_url"], rows[1]["location"], rows[0]["location"], rows[1]["date_posted"], rows[1]["description"]),
      ("https://www.workinaustria.com/en/employees/jobs/jobdetail/11/x", "Linz, Austria", "Wien, Austria", "2026-11-26",
       "We offer relocation support"))
check("health total", (health["rows"], health["total"]), (150, 150))

print("-- Workindenmark --")


def denmark_answer(method, url, kw):
    page = kw["params"]["pageNumber"]
    ads = [{"title": f"Founding Product Designer {page}-{i}", "hiringOrgName": "Milestone Systems",
            "municipality": "Gentofte" if i else None, "jobAdId": f"id-{page}-{i}",
            "jobAdUrl": None if i == 0 else f"https://emp.test/{page}-{i}", "publicationDate": "2026-11-26T00:00:00+01:00",
            "description": "<p>Visa sponsorship available</p>"} for i in range(100)]
    return Resp(200, {"jobAds": ads if page == 1 else ads[:30], "totalJobAdCount": 130})


http = FakeHttp(denmark_answer)
rows, health = workindenmark.read(http=http, sleep=NO_SLEEP)
check("x-csrf header sent", http.calls[0][2]["headers"]["x-csrf"], "1")
check("pages", [c[2]["params"]["pageNumber"] for c in http.calls], [1, 2])
check("Jobnet ad without a link -> Jobnet page", rows[0]["job_url"], "https://workindenmark.jobnet.dk/find-job/id-1-0")
check("row", (rows[1]["location"], rows[0]["location"], rows[1]["date_posted"], rows[1]["description"]),
      ("Gentofte, Denmark", "Denmark", "2026-11-26", "Visa sponsorship available"))
rows, health = workindenmark.read(http=FakeHttp(lambda m, u, k: Resp(401)), sleep=NO_SLEEP)
check("401 reported", health["error"], "page 1: HTTP 401")

print("-- Skåne STEM jobs --")


def skane_card(n):
    return (f'<div class="pej-job-card"><h3 class="pej-job-title">UI/UX Designer {n}</h3>'
            f'<span class="pej-badge pej-badge-location"><svg></svg> Lund </span>'
            f'<div class="pej-job-employer">Axis AB</div><div class="pej-job-description">About us...</div>'
            f'<div class="pej-job-meta"><span>Published: 2026-11-23</span><span>Last application date: 2026-12-23</span></div>'
            f'<a href="https://arbetsformedlingen.se/platsbanken/annonser/{n}" class="pej-apply-button">APPLY TO JOB</a></div>')


def skane_answer(method, url, kw):
    page = kw["params"]["pej_page"]
    cards = "".join(skane_card(page * 100 + i) for i in range(10 if page < 3 else 3))
    return Resp(200, text=f"<p>23 job ads are listed</p>{cards}")


http = FakeHttp(skane_answer)
rows, health = skane.read(http=http, sleep=NO_SLEEP)
check("3 pages for 23", [c[2]["params"]["pej_page"] for c in http.calls], [1, 2, 3])
check("row", (rows[0]["title"], rows[0]["company"], rows[0]["location"], rows[0]["date_posted"], rows[0]["job_url"]),
      ("UI/UX Designer 100", "Axis AB", "Lund, Sweden", "2026-11-23", "https://arbetsformedlingen.se/platsbanken/annonser/100"))
check("health", (health["rows"], health["total"]), (23, 23))
rows, health = skane.read(http=FakeHttp(lambda m, u, k: Resp(200, text="<html>Page not found</html>")), sleep=NO_SLEEP)
check("page without a job list reported", health["error"], "page 1: no job list on the page (changed or blocked)")

print("-- Careers in Gothenburg --")
searches = []


def fake_search(query, offset):
    searches.append((query, offset))
    if query != "designer":
        return {"hits": [], "estimatedTotalHits": 0}
    hits = [{"title": f"Service Designer {offset + i}", "employer_name": "Volvo Cars",
             "location.lvl1": "Gothenburg Region > Gothenburg" if i else "Gothenburg Region", "published": 1795132800,
             "description": "", "url": f"https://jobs.volvo.test/{offset + i}"} for i in range(20 if offset == 0 else 5)]
    return {"hits": hits, "estimatedTotalHits": 25}


rows, health = gothenburg.read(sleep=NO_SLEEP, search=fake_search)
check("designer paged by offset", [o for q, o in searches if q == "designer"], [0, 20])
check("each query searched", [q for q, o in searches if o == 0], list(gothenburg.QUERIES))
check("row", (len(rows), rows[1]["location"], rows[0]["location"], rows[1]["date_posted"]),
      (25, "Gothenburg, Sweden", "Sweden", "2026-11-20"))
check("page url carries the English-only filter", "%22english%22%3Atrue" in gothenburg.page_url("ux", 20)
      and "offset=20" in gothenburg.page_url("ux", 20), True)


def no_answer(query, offset):
    raise TimeoutError("Timeout 30000ms exceeded")


rows, health = gothenburg.read(sleep=NO_SLEEP, search=no_answer)
check("missing search answer reported", health["error"], "'product manager' page 1: Timeout 30000ms exceeded")

print("-- registry, switches, markets --")
check("ids", HUB_IDS, ["welcometonl", "southholland", "hirehelsinki", "workinestonia", "workinaustria",
                       "workindenmark", "skane", "gothenburg"])
check("every hub's country is a market", all(h["country"] in CANONICAL_MARKETS for h in HUBS), True)
check("hub-only countries aren't searched", [c for c in ("Finland", "Estonia", "Austria", "Denmark", "Sweden")
                                             if c in SEARCHED_MARKETS], [])
check("hubs rank after LI/Indeed", all(SOURCE_PRECEDENCE[h] > SOURCE_PRECEDENCE["indeed"] for h in HUB_IDS), True)
for raw, want in [("Tallinn, Estonia", "Estonia"), ("Linz, Austria", "Austria"), ("Gentofte, Denmark", "Denmark"),
                  ("Lund, Sweden", "Sweden"), ("Melbourne, Australia", "Australia")]:
    check(f"market {raw}", market_for_location(raw), want)

with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
    json.dump({"paused": False, "hubsOff": ["skane", "nonsense"]}, f)
check("hubsOff read, unknown ids ignored", hubs_off(f.name), {"skane"})
os.unlink(f.name)
check("no control file -> none off", hubs_off(""), set())
check("unreadable control file -> none off", hubs_off("/nonexistent/x.json"), set())

calls = []
fake_hubs = [
    {"id": "a", "name": "A", "country": "Estonia", "url": "https://a.test", "read":
        lambda terms: (calls.append("a") or [common.make_row("https://a.test/1", "X", "UX Designer", "Estonia")],
                       {"rows": 1, "pages": 1, "total": 1, "error": None})},
    {"id": "b", "name": "B", "country": "Sweden", "url": "https://b.test", "read": lambda terms: calls.append("b")},
    {"id": "c", "name": "C", "country": "Denmark", "url": "https://c.test", "read": lambda terms: 1 / 0},
]
rows, report = run_talent_hubs(["UX"], off={"b"}, hubs=fake_hubs)
check("off hub not read", calls, ["a"])
check("rows tagged with hub id", [s for s, _ in rows], ["a"])
check("report", [(r["id"], r["off"], r["rows"]) for r in report], [("a", False, 1), ("b", True, 0), ("c", False, 0)])
check("a reader bug is reported, not raised", report[2]["error"], "ZeroDivisionError: division by zero")
check("report carries name/country/url, not the reader", sorted(report[0]),
      ["country", "error", "id", "name", "off", "pages", "rows", "total", "url"])

print(f"\n{'all passed' if not failures else str(failures) + ' FAILED'}")
sys.exit(1 if failures else 0)
