"""
Offline sanity checks for match.py — no network, no JobSpy dependency, so
these can run anywhere with plain `python3 test_match.py` (including in an
environment where python-jobspy itself can't be installed, which is how
these were actually verified before this scraper was ever run against real
LI data — see li-scraper/README.md's "Not yet live-tested" note).
"""

from companies import COMPANIES, ALIASES
from match import build_index, match_company, is_role_relevant, fit_tier
from scrape import build_fresh_roles  # top-level scrape.py imports have no jobspy dependency —
                                       # it's only imported lazily inside run_searches()

INDEX = build_index(COMPANIES, ALIASES)

# build_fresh_roles() takes (source, row) tuples since September 2026's Indeed
# addition — this exercises that both "li" and "indeed" rows flow through
# company matching, title filtering, and de-dup identically, and that each
# kept role is tagged with the source it actually came from (not hardcoded).
FRESH_ROLES_CASES = [
    ("li", {"job_url": "https://x.test/1", "company": "Wise", "title": "Head of Design", "location": "London"}),
    ("indeed", {"job_url": "https://x.test/2", "company": "HSBC Holdings plc", "title": "Senior UX Researcher", "location": "Singapore"}),
    ("indeed", {"job_url": "https://x.test/3", "company": "Some Totally Unrelated Company", "title": "Head of Design", "location": "Berlin"}),  # dropped: no company match
    ("li", {"job_url": "https://x.test/4", "company": "Wise", "title": "Software Engineer", "location": "London"}),  # dropped: title not relevant
    ("li", {"job_url": "https://x.test/1", "company": "Wise", "title": "Head of Design (dup)", "location": "London"}),  # dropped: duplicate URL
]

# (LI employer name as it might realistically appear, expected slug or None)
CASES = [
    ("Standard Chartered Bank", "standard-chartered"),
    ("Standard Chartered", "standard-chartered"),
    ("HSBC Holdings plc", "hsbc"),
    ("Wise", "wise"),
    ("WiseTech Global", None),  # must NOT false-match "Wise" via substring
    ("Zepz", "zepz-worldremit-sendwave"),
    ("WorldRemit", "zepz-worldremit-sendwave"),
    ("Sendwave", "zepz-worldremit-sendwave"),
    ("Solarisbank", "solaris-solarisbank"),
    ("Network International", "network-international"),
    ("Random Network Solutions Inc", None),  # must NOT false-match via "network"
    ("DBS Bank Ltd", "dbs-bank"),
    ("DBS", "dbs-bank"),
    ("National Australia Bank", "national-australia-bank-nab"),
    ("NAB", "national-australia-bank-nab"),
    ("Man Group plc", "man-group"),
    ("Iron Man Productions", None),  # must NOT false-match "Man Group" via "man"
    ("Grab", "grab-grab-financial-group"),
    ("Grab Financial Group", "grab-grab-financial-group"),
    ("Some Totally Unrelated Company", None),
]

TITLE_CASES = [
    ("Director, Product Design", True, "target"),
    ("Head of UX Research", True, "target"),
    ("Senior Product Designer", True, "below"),
    ("Software Engineer", False, "below"),
    ("Design Engineer", True, "below"),  # alwaysAllow, but no target-tier keyword
    ("VP, Design Strategy", True, "target"),
    ("Product Marketing Manager", True, "below"),  # alwaysAllow, but "manager" alone isn't a target-tier word
    ("Sales Manager", False, "below"),
    ("Data Scientist, Product Analytics", False, "below"),
]


def run():
    failures = 0
    print("-- company matching --")
    for employer, expected in CASES:
        got = match_company(employer, INDEX)
        ok = got == expected
        failures += 0 if ok else 1
        print(f"  {'OK ' if ok else 'FAIL'}  {employer!r:45s} -> {got!r:35s} (expected {expected!r})")

    print("-- title relevance / tier --")
    for title, expected_relevant, expected_tier in TITLE_CASES:
        relevant = is_role_relevant(title)
        tier = fit_tier(title)
        ok = relevant == expected_relevant and tier == expected_tier
        failures += 0 if ok else 1
        print(f"  {'OK ' if ok else 'FAIL'}  {title!r:35s} relevant={relevant!s:5s} tier={tier:6s} "
              f"(expected relevant={expected_relevant!s:5s} tier={expected_tier})")

    print("-- build_fresh_roles (multi-source) --")
    fresh = build_fresh_roles(FRESH_ROLES_CASES, INDEX, "2026-09-09")
    fresh_checks = [
        ("kept exactly 2 roles (2 dropped, 1 duplicate)", len(fresh) == 2),
        ("wise role tagged source=li", fresh.get("https://x.test/1", (None, {}))[1].get("source") == "li"),
        ("wise role filed under correct slug", fresh.get("https://x.test/1", (None, {}))[0] == "wise"),
        ("hsbc role tagged source=indeed", fresh.get("https://x.test/2", (None, {}))[1].get("source") == "indeed"),
        ("hsbc role filed under correct slug", fresh.get("https://x.test/2", (None, {}))[0] == "hsbc"),
        ("unrelated company's role dropped", "https://x.test/3" not in fresh),
        ("irrelevant title dropped", "https://x.test/4" not in fresh),
    ]
    for label, ok in fresh_checks:
        failures += 0 if ok else 1
        print(f"  {'OK ' if ok else 'FAIL'}  {label}")

    total_cases = len(CASES) + len(TITLE_CASES) + len(fresh_checks)
    print(f"\n{total_cases - failures}/{total_cases} passed")
    if failures:
        raise SystemExit(f"{failures} case(s) failed")


if __name__ == "__main__":
    run()
