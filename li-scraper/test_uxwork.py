"""
Tests for uxwork.py against a fake search.php that behaves like the real one
(checked 2026-10-24): ~21 items per page, sponsored items mixed in, and past the
last page it repeats earlier results instead of returning []. No network needed.
Run: python3 test_uxwork.py
"""

import sys

import uxwork as ux

failures = 0


def check(label, ok):
    global failures
    failures += 0 if ok else 1
    print(f"  {'OK ' if ok else 'FAIL'}  {label}")


class FakeResponse:
    def __init__(self, data, status=200):
        self._data = data
        self.status_code = status
        self.text = str(data)

    def json(self):
        return self._data


def make_site(n_jobs, per_page=20):
    jobs = [{"titel": f"Product Designer {i}", "bedrijfsnaam": f"Co {i}",
             "intro": "<svg viewBox='0 0 16 16'><path d='M1'/></svg> Amsterdam",
             "url": f"https://uxwork.nl/en/job/{i}", "new": "3d", "closed": False}
            for i in range(n_jobs)]
    ad = {"titel": "Build Something", "url": "https://ads.example/x", "sec_text": "<b>Sponsored</b>", "promoted": True}
    pages = [jobs[i:i + per_page] + [ad] for i in range(0, n_jobs, per_page)]
    calls = []

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append(dict(params or {}))
        page = int(params["page"])
        # Like the real site: past the end, wrap around and repeat earlier pages.
        return FakeResponse(pages[(page - 1) % len(pages)])

    return fake_get, calls


print("-- paging --")
fake_get, calls = make_site(91)
ux.requests.get = fake_get
rows = list(ux.scrape_uxwork())
check("collects every unique job across pages (91)", len(rows) == 91)
check("sponsored items are dropped", not any("ads.example" in r[1]["job_url"] for r in rows))
check("stops at the first page with nothing new (5 pages of jobs + 1 repeat)", len(calls) == 6)
check("sends a numeric page and none of the 'Alle' values that empty the response",
      all(c["page"].isdigit() for c in calls) and "Alle" not in str(calls) and calls[0].get("filt_set_lan") == "Engels")
check("location is the text after the pin icon", rows[0][1]["location"] == "Amsterdam")

print("\n-- failure handling --")
ux.requests.get = lambda *a, **k: FakeResponse([])
check("an empty first page yields nothing, doesn't raise", list(ux.scrape_uxwork()) == [])
ux.requests.get = lambda *a, **k: FakeResponse({"error": "x"})
check("a non-list response yields nothing, doesn't raise", list(ux.scrape_uxwork()) == [])
ux.requests.get = lambda *a, **k: FakeResponse([], status=500)
check("an HTTP error yields nothing, doesn't raise", list(ux.scrape_uxwork()) == [])

print("\n-- _relative_age_to_iso() --")
today = ux.datetime.now(ux.timezone.utc).date().isoformat()
check("the HTML 'New' badge reads as today",
      ux._relative_age_to_iso('<span class="badge rounded-pill pill-green align-middle">New</span>') == today)
check("'3d' is three days ago",
      ux._relative_age_to_iso("3d") == (ux.datetime.now(ux.timezone.utc) - ux.timedelta(days=3)).date().isoformat())
check("empty and unknown values return None", ux._relative_age_to_iso("") is None and ux._relative_age_to_iso("soon") is None)

print(f"\n{'ALL PASSED' if failures == 0 else f'{failures} FAILURE(S)'}")
sys.exit(1 if failures else 0)
