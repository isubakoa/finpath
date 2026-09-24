"""
Regression check for the 2026-09-24 Glassdoor retirement (see scrape.py's
module docstring and GLASSDOOR_COUNTRY's own comment for the full writeup:
every Glassdoor request this scraper ever made failed — 400/403 + "location
not parsed" in every GitHub Actions run since Glassdoor support was added —
and the entire accumulated li-snapshot.json has zero roles ever sourced from
it). This test proves run_searches() no longer calls Glassdoor at all, for
both a Glassdoor-eligible location (per the still-present, now-unused
GLASSDOOR_COUNTRY mapping) and a Glassdoor-ineligible one — so a future edit
can't silently reintroduce the dead call without this failing.

No real network/jobspy dependency needed: run_searches() only imports
jobspy lazily, the moment its generator is first iterated (see
test_match.py's own note on this) — so a fake jobspy module recording every
scrape_jobs() call is inserted into sys.modules before that happens, exactly
the same pattern a real jobspy install would satisfy from run_searches()'s
point of view. Run with `python3 test_glassdoor_retired.py` — no
pytest/network required, same as every other test file in this project.
"""

import sys
import types

import pandas as pd

# ---- Fake jobspy module, inserted before scrape.py's lazy `from jobspy
# import scrape_jobs` executes. Records every call's site_name so this test
# can assert Glassdoor is never among them; returns an empty DataFrame so
# run_searches() has nothing to yield and moves straight to the next call.
CALLS = []


def _fake_scrape_jobs(**kwargs):
    CALLS.append(kwargs)
    return pd.DataFrame()


fake_jobspy = types.ModuleType("jobspy")
fake_jobspy.scrape_jobs = _fake_scrape_jobs
sys.modules["jobspy"] = fake_jobspy

from scrape import run_searches, GLASSDOOR_COUNTRY, PAUSE_BETWEEN_SEARCHES_SECONDS_MIN  # noqa: E402

failures = 0


def check(label, ok):
    global failures
    failures += 0 if ok else 1
    print(f"  {'OK ' if ok else 'FAIL'}  {label}")


# Speed the test up — the real PAUSE_BETWEEN_SEARCHES_* range (5-11s) would
# make this test itself slow for no reason; this only affects time.sleep(),
# not which calls get made, so it doesn't weaken what's being checked.
import scrape  # noqa: E402
scrape.PAUSE_BETWEEN_SEARCHES_SECONDS_MIN = 0
scrape.PAUSE_BETWEEN_SEARCHES_SECONDS_MAX = 0

print("-- run_searches() no longer calls Glassdoor --")

# "Singapore" is Glassdoor-eligible per GLASSDOOR_COUNTRY (still present,
# unused) — the strongest case: if retirement were incomplete, this is
# exactly the location that would still trigger a Glassdoor call.
check("Singapore is (still) in GLASSDOOR_COUNTRY, i.e. this is a real eligible-location test",
      "Singapore" in GLASSDOOR_COUNTRY)

# "Japan" is Glassdoor-ineligible even before retirement (never in
# GLASSDOOR_COUNTRY — Indeed-only, see that dict's comment) — included so
# this test covers both branches run_searches() used to have.
check("Japan is NOT in GLASSDOOR_COUNTRY (sanity check on the fixture itself)",
      "Japan" not in GLASSDOOR_COUNTRY)

combos = [("Product Manager", "Singapore"), ("Product Manager", "Japan")]
list(run_searches(combos, debug=False))

site_names_called = [c.get("site_name") for c in CALLS]
check("no call anywhere used site_name=[\"glassdoor\"]",
      all(sn != ["glassdoor"] for sn in site_names_called))
check("every call used only linkedin/indeed/google",
      all(sn in (["linkedin"], ["indeed"], ["google"]) for sn in site_names_called))

# 2 combos x 3 sites (li/indeed/google) each = 6 calls total — was 2x4=8
# (with Singapore's combo also making a Glassdoor call) before retirement.
check(f"exactly 6 scrape_jobs() calls total (2 combos x li+indeed+google, was up to 8 pre-retirement) — got {len(CALLS)}",
      len(CALLS) == 6)

# Per-combo shape: run_searches() processes combos in order, li-then-indeed-
# then-google for each (Glassdoor used to sit between indeed and google —
# see the comment left in its place in run_searches()) — so with Glassdoor
# gone, calls 0-2 are Singapore's (Glassdoor-eligible) and 3-5 are Japan's
# (never eligible), 3 each, same site_name sequence for both — proving
# eligibility no longer affects the call count at all, not just that this
# one run happened to skip Glassdoor.
singapore_site_names = [c.get("site_name") for c in CALLS[0:3]]
japan_site_names = [c.get("site_name") for c in CALLS[3:6]]
check(f"Singapore combo (Glassdoor-eligible) made exactly [linkedin, indeed, google], not 4 calls — got {singapore_site_names}",
      singapore_site_names == [["linkedin"], ["indeed"], ["google"]])
check(f"Japan combo (never Glassdoor-eligible) made the identical [linkedin, indeed, google] shape — got {japan_site_names}",
      japan_site_names == [["linkedin"], ["indeed"], ["google"]])

print(f"\n{'ALL PASSED' if failures == 0 else f'{failures} FAILURE(S)'}")
sys.exit(1 if failures else 0)
