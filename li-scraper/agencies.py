"""
Phase 2.3 — agency/staffing-firm identification for the open-market feed. An
employer name normalizes (via match.py's normalize_employer_name() — the
same function tracked-company matching itself uses) to one of these if it's
a known staffing/recruitment agency or job-aggregator brand rather than a
real employer.

2026-09-28 — this list was originally a hard blocklist: open_market_gate()
called is_agency() and dropped any posting from one of these employers
outright, regardless of title or fit tier. As of 2026-09-28, per explicit
request, open_market_gate() no longer calls is_agency() at all — staffing/
recruitment agency postings (Robert Walters, Michael Page, etc.) are now
INCLUDED in the open-market feed like any other employer. This module and
is_agency() are otherwise untouched (still directly unit tested in
test_match.py) precisely so that reinstating the blocklist, or repurposing
it as a filter/badge instead of a hard exclusion, stays a small, self-
contained change — see match.py's open_market_gate() docstring for the
full reasoning.

Seeded from two sources:
  1. The original spec's list of named agencies/staffing firms.
  2. Phase 0's own top-40 unmatched-employer measurement (2026-09-22/23,
     ~7,300 raw rows across 4 scrape runs). Two entries there stood out as
     almost certainly repost/job-aggregator brands rather than real
     employers — Jobgether (68 occurrences) and Doit (27) — both generic-
     sounding, high-volume, and not recognizable as any real company in
     this candidate's target industries. Added on that basis.

     A third, BJAK (55 occurrences), was flagged in the Phase 0 report as
     *worth checking* but not confirmed either way, and is deliberately
     left OUT of this list until it is: misclassifying a real employer as
     an agency silently drops every genuine opening they post, which is a
     worse failure mode for this tool's purpose than temporarily still
     showing a few aggregator reposts from an unconfirmed source. If BJAK
     turns out to be another aggregator, add it here; if it's a real
     company, it should stay out and might even be worth tracking properly
     instead (companies.py) rather than living in the open-market feed.
"""

from match import normalize_employer_name

AGENCY_NAMES = [
    # -- Original spec list --
    "Michael Page",
    "PageGroup",
    "Robert Walters",
    "Hays",
    "Randstad",
    "Adecco",
    "Morgan McKinley",
    "Argyll Scott",
    "Robert Half",
    "Kelly Services",
    "ManpowerGroup",
    "Hudson",
    "Charterhouse",
    "Ambition",
    "Selby Jennings",
    "Phaidon",
    "Nigel Frank",
    "Darwin Recruitment",
    "Levy Associates",
    "YER",
    "Undutchables",
    "Blue Lynx",
    "Michael Bailey",
    "Marks Sattin",
    # -- Phase 0 measurement additions (2026-09-23) — see module docstring --
    "Jobgether",
    "Doit",
]

_NORMALIZED_AGENCY_NAMES = {normalize_employer_name(name) for name in AGENCY_NAMES}


def is_agency(employer_name):
    """True if employer_name normalizes to an EXACT match against the
    blocklist. Deliberately exact-match only, not the fuzzy substring/
    containment match_company() uses for tracked companies — a blocklist's
    false-positive cost (wrongly suppressing a real company's real posting,
    silently, with nothing to notice it) is much higher-stakes than tracked
    matching's occasional false-negative, so this errs conservative rather
    than reusing match_company()'s more permissive fuzzy path."""
    return normalize_employer_name(employer_name) in _NORMALIZED_AGENCY_NAMES
