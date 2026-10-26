"""
Tests for uxwork.py's paging against a fake search.php that behaves like the real one
(checked 2026-10-24): ~21 items per page, sponsored items mixed in, and past the
last page it repeats earlier results instead of returning []. No network needed.
Run: python3 test_uxwork.py
"""

import json
import sys

import uxwork as ux

failures = 0


def check(label, ok):
    global failures
    failures += 0 if ok else 1
    print(f"  {'OK ' if ok else 'FAIL'}  {label}")


def make_site(n_jobs, per_page=20):
    jobs = [{"titel": f"Product Designer {i}", "bedrijfsnaam": f"Co {i}",
             "intro": "<svg viewBox='0 0 16 16'><path d='M1'/></svg> Amsterdam",
             "url": f"https://uxwork.nl/en/job/{i}", "new": "3d", "closed": False}
            for i in range(n_jobs)]
    ad = {"titel": "Build Something", "url": "https://ads.example/x", "sec_text": "<b>Sponsored</b>", "promoted": True}
    pages = [jobs[i:i + per_page] + [ad] for i in range(0, n_jobs, per_page)]
    calls = []

    def fake_fetch(page):
        calls.append(page)
        # Like the real site: past the end, wrap around and repeat earlier pages.
        return 200, json.dumps(pages[(page - 1) % len(pages)])

    return fake_fetch, calls


print("-- paging --")
fake_fetch, calls = make_site(91)
rows = list(ux._page_through(fake_fetch))
check("collects every unique job across pages (91)", len(rows) == 91)
check("sponsored items are dropped", not any("ads.example" in r[1]["job_url"] for r in rows))
check("stops at the first page with nothing new (5 pages of jobs + 1 repeat)", len(calls) == 6)
check("asks for pages 1, 2, 3... in order", calls == list(range(1, 7)))
check("filters: none of the 'Alle' values that empty the response",
      "Alle" not in str(ux.DEFAULT_PARAMS) and ux.DEFAULT_PARAMS.get("filt_set_lan") == "Engels")
check("location is the text after the pin icon", rows[0][1]["location"] == "Amsterdam")

print("\n-- failure handling --")
check("an empty first page yields nothing, doesn't raise", list(ux._page_through(lambda n: (200, "[]"))) == [])
check("a non-list response yields nothing, doesn't raise", list(ux._page_through(lambda n: (200, '{"error": "x"}'))) == [])
check("an HTTP error yields nothing, doesn't raise", list(ux._page_through(lambda n: (500, "[]"))) == [])
check("a non-JSON answer (bot check page) yields nothing, doesn't raise",
      list(ux._page_through(lambda n: (200, "<html>Checking your browser</html>"))) == [])

def boom(n):
    raise RuntimeError("page closed")
check("a failed fetch yields nothing, doesn't raise", list(ux._page_through(boom)) == [])

print("\n-- _relative_age_to_iso() --")
today = ux.datetime.now(ux.timezone.utc).date().isoformat()
check("the HTML 'New' badge reads as today",
      ux._relative_age_to_iso('<span class="badge rounded-pill pill-green align-middle">New</span>') == today)
check("'3d' is three days ago",
      ux._relative_age_to_iso("3d") == (ux.datetime.now(ux.timezone.utc) - ux.timedelta(days=3)).date().isoformat())
check("empty and unknown values return None", ux._relative_age_to_iso("") is None and ux._relative_age_to_iso("soon") is None)

print(f"\n{'ALL PASSED' if failures == 0 else f'{failures} FAILURE(S)'}")
sys.exit(1 if failures else 0)
