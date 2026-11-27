"""Tests for the Talent Hubs readers with fake portals (no network), and for
duplicates across hubs and job sites. Run: python3 hb-scraper/test_talent_hubs.py"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "li-scraper"))

import arbetsformedlingen  # noqa: E402
import brainport  # noqa: E402
import common  # noqa: E402
import gothenburg  # noqa: E402
import hire_helsinki  # noqa: E402
import jobsplus  # noqa: E402
import make_it_in_munich  # noqa: E402
import nav  # noqa: E402
import skane  # noqa: E402
import south_holland  # noqa: E402
import talent_berlin  # noqa: E402
import vdab  # noqa: E402
import welcome_to_nl  # noqa: E402
import work_in_austria  # noqa: E402
import work_in_estonia  # noqa: E402
import work_in_lithuania  # noqa: E402
import work_in_luxembourg  # noqa: E402
import workindenmark  # noqa: E402
from registry import HUB_IDS, HUBS, hubs_off, run_talent_hubs  # noqa: E402
from roles import (CANONICAL_MARKETS, SEARCHED_MARKETS, SOURCE_PRECEDENCE, build_fresh_roles,  # noqa: E402
                   market_for_location, merge_and_prune, set_hub_order)
from companies import ALIASES, COMPANIES  # noqa: E402
from match import build_index  # noqa: E402

set_hub_order(HUB_IDS)

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
check("17 hubs", len(HUB_IDS), 17)
check("every hub's country is a market", all(h["country"] in CANONICAL_MARKETS for h in HUBS), True)
HUB_ONLY = ("Finland", "Estonia", "Austria", "Denmark", "Sweden", "Norway", "Belgium", "Luxembourg", "Lithuania", "Malta")
check("hub-only countries aren't searched", [c for c in HUB_ONLY if c in SEARCHED_MARKETS], [])
check("hub-only countries are accepted", [c for c in HUB_ONLY if c not in CANONICAL_MARKETS], [])
check("hubs rank after LI/Indeed", all(SOURCE_PRECEDENCE[h] > SOURCE_PRECEDENCE["indeed"] for h in HUB_IDS), True)
for raw, want in [("Tallinn, Estonia", "Estonia"), ("Linz, Austria", "Austria"), ("Gentofte, Denmark", "Denmark"),
                  ("Lund, Sweden", "Sweden"), ("Melbourne, Australia", "Australia"), ("Oslo", "Norway"),
                  ("Antwerpen, Belgium", "Belgium"), ("Kaunas, Lithuania", "Lithuania"), ("Tas-Sliema, Malta", "Malta"),
                  ("Luxembourg", "Luxembourg"), ("Buenos Aires, Argentina", None), ("Bergen op Zoom", None)]:
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

print("-- Arbetsförmedlingen --")
EN = "We are looking for a designer to join our team and you will work with the product"
SV = "Vi söker en designer som vill arbeta med oss och du är"


def af_answer(method, url, kw):
    q, off = kw["params"]["q"], kw["params"]["offset"]
    if q != "product designer":
        return Resp(200, {"total": {"value": 0}, "hits": []})
    hits = [{"headline": f"Staff Product Designer {off + i}", "employer": {"name": "Legora AB"},
             "workplace_address": {"city": "Stockholm" if i else None, "municipality": "Solna"},
             "publication_date": "2026-11-25T10:00:00", "webpage_url": f"https://arbetsformedlingen.se/platsbanken/annonser/{off + i}",
             "description": {"text": EN if i % 2 == 0 else SV}} for i in range(100 if off == 0 else 20)]
    return Resp(200, {"total": {"value": 120}, "hits": hits})


http = FakeHttp(af_answer)
rows, health = arbetsformedlingen.read(http=http, sleep=NO_SLEEP)
check("offset paging", [c[2]["params"]["offset"] for c in http.calls if c[2]["params"]["q"] == "product designer"], [0, 100])
check("only English ads kept", len(rows), 60)
check("row", (rows[0]["location"], rows[1]["location"], rows[0]["date_posted"], rows[0]["company"]),
      ("Solna, Sweden", "Stockholm, Sweden", "2026-11-25", "Legora AB"))

print("-- NAV arbeidsplassen --")


def nav_article(n):
    return (f'<article aria-label="x"><p>21. november 2026</p><h2><a href="/stillinger/stilling/id-{n}">UX Designer {n}</a></h2>'
            f'<p>Arbeidsgiver</p><p>Nofence</p><p>Sted</p><p>Oslo</p><p>Søk snarest mulig</p></article>')


def nav_answer(method, url, kw):
    p = kw["params"]
    if p["q"] != "ux":
        return Resp(200, text="<p>0 treff</p>")
    n = 25 if p["from"] == 0 else 5
    return Resp(200, text="<p>30 treff</p>" + "".join(nav_article(p["from"] + i) for i in range(n)))


http = FakeHttp(nav_answer)
rows, health = nav.read(http=http, sleep=NO_SLEEP)
check("English filter sent, paged by 25", ([c[2]["params"]["workLanguage"] for c in http.calls][0],
                                          [c[2]["params"]["from"] for c in http.calls if c[2]["params"]["q"] == "ux"]),
      ("Engelsk", [0, 25]))
check("row", (len(rows), rows[0]["job_url"], rows[0]["company"], rows[0]["location"], rows[0]["date_posted"]),
      (30, "https://arbeidsplassen.nav.no/stillinger/stilling/id-0", "Nofence", "Oslo, Norway", "2026-11-21"))
check("Norwegian date", (nav.norwegian_date("5. desember 2026"), nav.norwegian_date("snarest")), ("2026-12-05", None))

print("-- Work in Lithuania --")


def lt_answer(method, url, kw):
    page = kw["params"]["page"]
    offers = [{"name": f"Product Manager {page}-{i}", "company": {"name": "UAB Teltonika"},
               "location": "Kaunas, Remote job" if i else "Other", "slug": f"https://www.cvbankas.lt/x-{page}-{i}"} for i in range(12)]
    return Resp(200, {"data": offers if page < 2 else offers[:3], "meta": {"total": 15, "last_page": 2}})


rows, health = work_in_lithuania.read(http=FakeHttp(lt_answer), sleep=NO_SLEEP)
check("rows and places", (len(rows), rows[1]["location"], rows[0]["location"], health["total"]),
      (15, "Kaunas, Lithuania", "Lithuania", 15))

print("-- Work in Luxembourg --")


def lu_answer(method, url, kw):
    page = kw["params"]["page"]
    content = [{"id": f"id-{page}-{i}", "titles": {"en": f"Product Manager Digital Assets {page}{i}"},
                "exhibitorName": "LUXEMBOURG STOCK EXCHANGE", "publishedAt": "2026-11-19T00:00:00Z", "expired": i == 9}
               for i in range(10)]
    return Resp(200, {"content": content, "totalElements": 20, "totalPages": 2})


http = FakeHttp(lu_answer)
rows, health = work_in_luxembourg.read(http=http, sleep=NO_SLEEP)
check("board id header, 0-based pages", (http.calls[0][2]["headers"]["JobBoard-Id"] == work_in_luxembourg.BOARD_ID,
                                        [c[2]["params"]["page"] for c in http.calls]), (True, [0, 1]))
check("expired skipped, row", (len(rows), rows[0]["job_url"], rows[0]["location"], rows[0]["date_posted"]),
      (18, "https://jobs.workinluxembourg.com/offers/id-0-0", "Luxembourg", "2026-11-19"))

print("-- Talent Berlin --")


def berlin_answer(method, url, kw):
    if "q=product%20manager" not in url:
        return Resp(200, {"template": "", "nextSearchPageCount": 0})
    page = int(url.split("/page/")[1].split("/")[0])
    cards = "".join(f'<div class="c-joblist__item"><a href="/jobs/search-results/job-offer/job/ext/pm-{page}-{i}">'
                    f'<p class="c-joblist__date"> 11/25/2026 </p><h3>Senior Product Manager (m/w/d)</h3>'
                    f'<p class="c-joblist__company">Studyflix GmbH {i}</p></a></div>' for i in range(12 if page == 1 else 4))
    return Resp(200, {"template": cards, "nextSearchPageCount": 4 if page == 1 else 0})


rows, health = talent_berlin.read(http=FakeHttp(berlin_answer), sleep=NO_SLEEP)
check("pages until none left", (len(rows), health["pages"]), (16, 2 + len(talent_berlin.QUERIES) - 1))
check("row", (rows[0]["job_url"], rows[0]["location"], rows[0]["date_posted"]),
      ("https://talent.berlin/jobs/search-results/job-offer/job/ext/pm-1-0", "Berlin, Germany", "2026-11-25"))

print("-- Make it in Munich --")


def munich_answer(method, url, kw):
    p = kw["params"]
    if p["job_title"] != "Product Owner":
        return Resp(200, {"total": 0, "total_pages": 0, "jobs": []})
    jobs = [{"job_title": "Product Owner SAP (m/w/d)", "company_name": f"BVK {i}", "postal_code": "81541.0" if i else "85521.0",
             "created_at": "2026-11-26 05:01:12", "url": f"https://jobs.test/{p['page']}-{i}"} for i in range(3)]
    return Resp(200, {"total": 3, "total_pages": 1, "jobs": jobs})


rows, health = make_it_in_munich.read(http=FakeHttp(munich_answer), sleep=NO_SLEEP)
check("Munich vs Bavaria", (rows[1]["location"], rows[0]["location"], rows[0]["date_posted"]),
      ("Munich, Germany", "Bavaria, Germany", "2026-11-26"))

print("-- Jobsplus --")


def jp_answer(method, url, kw):
    p = kw["params"]
    if p["searchText"] != "ux":
        return Resp(200, text="<ul><li><strong>0 Job(s)</strong></li></ul><ul class='list-d'></ul>")
    items = "".join(f'<li id="45{p["pageNumber"]}{i}"><a href="#"><h3>FRONT-END / UI-UX DESIGNER</h3>'
                    f'<ul><li><span><i class="fad fa-map-pin"></i> TAS-SLIEMA, MALTA</span></li></ul>'
                    f'<p> (Please log in to view Company Name) </p><p>MedTrips is seeking a designer.</p></a></li>'
                    for i in range(10 if p["pageNumber"] == 1 else 2))
    return Resp(200, text=f"<ul><li><strong>12 Job(s)</strong></li></ul><ul class='list-d'>{items}</ul>")


rows, health = jobsplus.read(http=FakeHttp(jp_answer), sleep=NO_SLEEP)
check("row", (len(rows), rows[0]["title"], rows[0]["location"], rows[0]["company"], rows[0]["job_url"], rows[0]["description"]),
      (12, "Front-End / UI-UX Designer", "Tas-Sliema, Malta", jobsplus.COMPANY_HIDDEN,
       "https://jobsplus.gov.mt/vacancy/vacancy-details?id=4510", "MedTrips is seeking a designer."))

print("-- Brainport (browser answers faked) --")
bp_calls = []


def fake_pages(query, page):
    bp_calls.append((query, page))
    if query != "designer":
        return {"data": [], "meta": {"current_page": 1, "last_page": 1}}
    data = [{"title": f"UX Designer {page}-{i}", "url": f"https://careers.test/{page}-{i}", "job_date": "2026-11-23",
             "organization": {"name": "Philips"}, "location": {"name": "Eindhoven"}} for i in range(15)]
    return {"data": data, "meta": {"current_page": page, "last_page": 2}}


rows, health = brainport.read(sleep=NO_SLEEP, pages=fake_pages)
check("search then load more", [p for q, p in bp_calls if q == "designer"], [1, 2])
check("row", (len(rows), rows[0]["location"], rows[0]["date_posted"]), (30, "Eindhoven, Netherlands", "2026-11-23"))

print("-- VDAB (browser answers faked) --")


def fake_vdab(query, page):
    if query != "product designer":
        return {"resultaten": [], "paginaGrootte": 15}
    res = [{"id": {"id": 75000000 + page * 100 + i}, "vacaturefunctie": {"naam": "Digital Product Designer"},
            "vacatureBedrijfsnaam": f"Sopra Steria {i}", "tewerkstellingsLocatieRegioOfAdres": "DIEGEM",
            "eerstePublicatieDatum": "2026-06-16T16:41:49Z"} for i in range(15 if page == 1 else 3)]
    return {"resultaten": res, "paginaGrootte": 15}


rows, health = vdab.read(sleep=NO_SLEEP, search=fake_vdab)
check("row", (len(rows), rows[0]["job_url"], rows[0]["location"], rows[0]["date_posted"]),
      (18, "https://www.vdab.be/vindeenjob/vacatures/75000100", "Diegem, Belgium", "2026-06-16"))
check("results page url", vdab.page_url("ux designer", 2),
      "https://www.vdab.be/vindeenjob/vacatures?trefwoord=ux%20designer&sort=standaard&sinds=9000&p=2")

print("-- duplicates across hubs and job sites --")
INDEX = build_index(COMPANIES, ALIASES)
row = common.make_row
dup_rows = [
    ("li", row("https://li.test/1", "Bolt", "Senior Product Designer", "Tallinn, Estonia")),
    ("workinestonia", row("https://cv.ee/1?utm_source=workinestonia", "Bolt Technology OÜ", "Senior Product Designer", "Estonia")),
    ("workinestonia", row("https://cv.ee/1", "Bolt", "Senior Product Designer", "Estonia")),  # same link once utm is gone
    ("welcometonl", row("https://emp.test/a", "Mendix", "Product Designer (m/f/d)", "Rotterdam")),
    ("southholland", row("https://careers.mendix.test/a", "Mendix B.V.", "Product Designer", "Rotterdam, Netherlands")),
    ("brainport", row("https://careers.mendix.test/b", "Mendix", "Product Designer - all genders", "Eindhoven, Netherlands")),
    ("arbetsformedlingen", row("https://af.test/1", "Spotify AB", "Senior Product Manager", "Stockholm, Sweden")),
    ("indeed", row("https://indeed.test/1", "Spotify", "Senior Product Manager", "Stockholm")),
    ("talentberlin", row("https://tb.test/1", "SATO Europe GmbH", "Senior Product Manager (m/w/d)", "Berlin, Germany")),
    ("makeitinmunich", row("https://mm.test/1", "SATO Europe", "Senior Product Manager", "Munich, Germany")),
    ("jobsplus", row("https://jp.test/1", jobsplus.COMPANY_HIDDEN, "Senior Product Designer", "Sliema, Malta")),
    ("jobsplus", row("https://jp.test/2", jobsplus.COMPANY_HIDDEN, "Senior UX Designer", "Gzira, Malta")),
]
fresh, om = build_fresh_roles(dup_rows, INDEX, "2026-11-27")
everything = list(fresh.values()) + list(om.values())


def find(employer_word):
    return [r for _, r in everything if employer_word.lower() in (r.get("employer") or r.get("url")).lower()]


bolt = [r for _, r in everything if "Senior Product Designer" == r["title"] and "Estonia" in r["location"]]
check("Bolt: LI + Work in Estonia -> one role, LI's link", (len(bolt), bolt[0]["url"] if bolt else None,
                                                        sorted(bolt[0]["sources"]) if bolt else None),
      (1, "https://li.test/1", ["li", "workinestonia"]))
mendix = [r for _, r in everything if r["title"].startswith("Product Designer")]
check("Mendix on 3 Dutch hubs, 3 spellings, 2 cities -> one role", (len(mendix), sorted(mendix[0]["sources"]) if mendix else None),
      (1, ["brainport", "southholland", "welcometonl"]))
spotify = [r for _, r in everything if r["title"] == "Senior Product Manager" and "Sweden" in (r.get("market") or "Sweden")
           and "Stockholm" in r["location"]]
check("Spotify: Indeed + Arbetsförmedlingen -> one role, Indeed's link", (len(spotify), spotify[0]["url"] if spotify else None),
      (1, "https://indeed.test/1"))
sato = [r for _, r in everything if r.get("employer", "").startswith("SATO")]
check("same employer and title in two German cities -> one role (accepted limitation)", len(sato), 1)
malta = [r for _, r in everything if "Malta" in r["location"]]
check("Jobsplus roles with the hidden company stay apart by title", len(malta), 2)

# Across runs: a duplicate pair already in the snapshot under the old city-level key collapses on the next run.
existing = {"companies": {}, "openMarket": {"roles": [
    {"employer": "Adyen", "market": "Netherlands", "title": "Senior Product Designer", "location": "Amsterdam",
     "url": "https://li.test/old", "postedDate": "2026-11-20", "source": "li", "sources": ["li"], "sponsorshipSignal": [],
     "lastSeenAt": "2026-11-26"},
    {"employer": "Adyen N.V.", "market": "Netherlands", "title": "Senior Product Designer (m/f/d)",
     "location": "Amsterdam, Netherlands", "url": "https://wtnl.test/old", "postedDate": None, "source": "welcometonl",
     "sources": ["welcometonl"], "sponsorshipSignal": ["visa sponsorship"], "lastSeenAt": "2026-11-26"}]}}
snapshot = merge_and_prune(existing, {}, "2026-11-27", fresh_open_market_roles={})
adyen = snapshot["openMarket"]["roles"]
check("old duplicates merged in the snapshot", (len(adyen), sorted(adyen[0]["sources"]), adyen[0]["url"],
                                                adyen[0]["sponsorshipSignal"]),
      (1, ["li", "welcometonl"], "https://li.test/old", ["visa sponsorship"]))

print(f"\n{'all passed' if not failures else str(failures) + ' FAILED'}")
sys.exit(1 if failures else 0)
