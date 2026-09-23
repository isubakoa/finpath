"""
Offline sanity checks for match.py — no network, no JobSpy dependency, so
these can run anywhere with plain `python3 test_match.py` (including in an
environment where python-jobspy itself can't be installed, which is how
these were actually verified before this scraper was ever run against real
LI data — see li-scraper/README.md's "Not yet live-tested" note).
"""

from datetime import datetime, timedelta, timezone

from agencies import is_agency
from companies import COMPANIES, ALIASES
from match import (
    build_index,
    match_company,
    is_role_relevant,
    fit_tier,
    find_collisions,
    match_negative_filters,
    normalize_scraped_title,
    normalize_employer_name,
    role_identity,
    open_market_gate,
)
from scrape import (  # top-level scrape.py imports have no jobspy dependency —
    build_fresh_roles,                                    # it's only imported lazily inside run_searches()
    merge_and_prune,
    OPEN_MARKET_LOCATIONS,
    EXPIRY_DAYS,
    _open_market_for,
)

INDEX = build_index(COMPANIES, ALIASES)

# build_fresh_roles() takes (source, row) tuples since September 2026's Indeed
# addition, extended the same month to glassdoor/google/bayt — this exercises
# that all five sources' rows flow through company matching, title filtering,
# and de-dup identically, and that each kept role is tagged with the source
# it actually came from (not hardcoded) — build_fresh_roles() itself is
# entirely source-agnostic (it just passes whatever string it's given straight
# through to the kept role's "source" field), so these cases mainly guard
# against a future edit accidentally special-casing one source over another.
#
# The float("nan") cases below reproduce a real production crash from the
# first live GitHub Actions run (2026-09-09): JobSpy returns a pandas
# DataFrame, and pandas represents a missing field as NaN — a float, not
# None or "" — which `row.get(...) or ""` doesn't catch (float('nan') is
# truthy), so a NaN company name reached match.py's regex substitution as a
# raw float and crashed with `TypeError: expected string or bytes-like
# object, got 'float'`. Fixed via _clean_str() in scrape.py (and a matching
# guard in match.py's _normalize()) — these cases must keep passing.
#
# Case #1 (li, url1) and case #10 (google, url9) are the SAME normalized
# identity on purpose (Wise / "Head of Design" / London) — Phase 1.4's
# cross-site dedupe test: two different sites, two different URLs, one real
# posting, so build_fresh_roles() must collapse them into a single kept
# entry instead of two.
FRESH_ROLES_CASES = [
    ("li", {"job_url": "https://x.test/1", "company": "Wise", "title": "Head of Design", "location": "London"}),
    ("indeed", {"job_url": "https://x.test/2", "company": "HSBC Holdings plc", "title": "Senior UX Researcher", "location": "Singapore"}),
    ("indeed", {"job_url": "https://x.test/3", "company": "Some Totally Unrelated Company", "title": "Head of Design", "location": "Berlin"}),  # dropped: no company match
    ("li", {"job_url": "https://x.test/4", "company": "Wise", "title": "Software Engineer", "location": "London"}),  # dropped: title not relevant
    ("li", {"job_url": "https://x.test/1", "company": "Wise", "title": "Head of Design (dup)", "location": "London"}),  # dropped: duplicate URL
    ("li", {"job_url": "https://x.test/5", "company": float("nan"), "title": "Head of Design", "location": "London"}),  # dropped, not crashed: NaN company
    ("li", {"job_url": "https://x.test/6", "company": "Wise", "title": "Head of Design", "location": float("nan")}),  # kept: NaN location -> "" (1.5 — no more "Not specified")
    ("indeed", {"job_url": "https://x.test/7", "company": "Wise", "title": float("nan"), "location": "London"}),  # dropped, not crashed: NaN title
    ("glassdoor", {"job_url": "https://x.test/8", "company": "Wise", "title": "Senior Product Designer", "location": "Singapore"}),  # kept, source=glassdoor
    ("google", {"job_url": "https://x.test/9", "company": "Wise", "title": "Head of Design", "location": "London"}),  # 1.4: same identity as case #1 — merges, doesn't add a 6th kept entry
    ("bayt", {"job_url": "https://x.test/10", "company": "Wise", "title": "UX Researcher", "location": "Dubai"}),  # kept, source=bayt
    # 2.2 — open-market cases: none of these employers are tracked companies.
    ("li", {"job_url": "https://x.test/11", "company": "Some Random Singapore Startup Pte Ltd", "title": "Head of Product Design", "location": "Singapore"}),  # kept open-market: relevant, target-tier, SG, not an agency
    ("glassdoor", {"job_url": "https://x.test/11b", "company": "Some Random Singapore Startup Pte Ltd", "title": "Head of Product Design", "location": "Singapore"}),  # 1.4-style merge: same open-market identity as #11, different site/URL
    ("indeed", {"job_url": "https://x.test/12", "company": "Some Random Singapore Startup Pte Ltd", "title": "Product Designer", "location": "Singapore"}),  # dropped: relevant but only "below" tier, not "target" — fails open_market_gate()
    ("li", {"job_url": "https://x.test/13", "company": "Robert Walters", "title": "Head of Product Design", "location": "Netherlands"}),  # dropped: would otherwise qualify, but Robert Walters is agency-blocklisted
    ("li", {"job_url": "https://x.test/14", "company": "Some Random Startup GmbH", "title": "Head of Product Design", "location": "Germany"}),  # dropped: qualifying title, but Germany isn't an OPEN_MARKET_LOCATIONS market — not even offered to the gate
    # UAE added 2026-09-23 — same "genuine open-market employer" shape as #11, but for the
    # newest OPEN_MARKET_LOCATIONS market, and using the "UAE" abbreviation (not the spelled-out
    # "United Arab Emirates" that appears in LOCATIONS) to exercise MARKET_ALIASES.
    ("indeed", {"job_url": "https://x.test/15", "company": "Some Random Dubai Startup FZE", "title": "Head of Product Design", "location": "Dubai, UAE"}),  # kept open-market: relevant, target-tier, UAE (via alias), not an agency
]

# 1.5 — (raw_title, raw_location, expected_title, expected_location), tested
# directly against normalize_scraped_title(), ported from index.html's
# normalizeScrapedTitle()/CTA_SUFFIX_RE/TRAILING_LOCATION_RE.
NORMALIZE_CASES = [
    # CTA suffix stripped regardless of whether location is already known.
    ("Head of Design - View Job", "London", "Head of Design", "London"),
    ("Senior Product Designer | Apply Now", "Singapore", "Senior Product Designer", "Singapore"),
    # Trailing "City, Country" recovered from the title, but ONLY when the
    # site gave no location of its own (or the old "Not specified"
    # placeholder — same as truly empty for this purpose). Note the title
    # itself needs a comma ahead of the city for this to work cleanly — the
    # recovery regex matches a run of Title-Case words on each side of a
    # comma, so a title made ENTIRELY of Title-Case words with no comma of
    # its own (e.g. "Staff Product Designer Rotterdam, Netherlands") is a
    # real, known ambiguity it can't safely resolve (the city name is
    # indistinguishable from more title words) and is deliberately left
    # untouched rather than guessed at wrong — see TRAILING_LOCATION_RE's
    # comment. This is inherited as-is from index.html's own regex, not
    # something Phase 1.5 set out to fix.
    ("Product Designer, Amsterdam, Netherlands", "", "Product Designer", "Amsterdam, Netherlands"),
    ("Product Designer, Amsterdam, Netherlands", "Not specified", "Product Designer", "Amsterdam, Netherlands"),
    # The known ambiguity itself, documented as a passing case rather than
    # silently unhandled: left untouched, not guessed at wrong.
    ("Staff Product Designer Rotterdam, Netherlands", "", "Staff Product Designer Rotterdam, Netherlands", ""),
    # A perfectly normal comma'd title is left alone once a real location is
    # already present — must NOT get mangled by the recovery regex (real
    # LI/Indeed titles routinely end in ", Principal" / ", Architect" / a
    # second job-title clause with nothing to do with location).
    ("Director, Product Design", "Netherlands", "Director, Product Design", "Netherlands"),
    ("Product Management, Principal", "Kuala Lumpur, Malaysia", "Product Management, Principal", "Kuala Lumpur, Malaysia"),
    # Whitespace collapse.
    ("Head   of\tDesign", "  London  ", "Head of Design", "London"),
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

# Every normalized name/alias that two different companies both claim as an
# exact-match key, as of the last time this was reviewed. build_index()'s
# `exact` dict is last-write-wins with no collision detection of its own, so
# without this test a new collision (e.g. a future company whose name also
# reduces to "boost" once suffixes are stripped) would fail silently --
# postings would just get filed under the wrong slug with nothing to notice.
# Each entry here has been individually reviewed and accepted:
#
#   "boost" -> boost / boost-bank: genuinely affiliated companies (Boost
#   Bank is a 2024 digital-banking JV between Axiata's Boost and RHB, and
#   literally shares Boost's own careers.myboost.co board per its note in
#   index.html) whose names become identical text once "Bank" is stripped
#   as a legal/corporate suffix. There's no text-only way to tell a real
#   "Boost" posting from a real "Boost Bank" posting apart, and since both
#   businesses share one careers site anyway, a stray misfile between the
#   two slugs has minimal practical impact on what a reviewer sees. Adding
#   a special-case exception to _normalize() for this one pair was judged
#   riskier (touches shared normalization logic used by all 210 companies)
#   than documenting and testing for it here.
#
# If this test starts failing because find_collisions() returns something
# NOT in this allowlist, that's a real new bug (same class as the du/Emirates
# collision caught and fixed in Sep 2026) -- go fix companies.py's aliases,
# don't just widen the allowlist.
KNOWN_COLLISIONS = {
    "boost": ["boost", "boost-bank"],
}

# (title, expected is_role_relevant(), expected fit_tier()) — covers 1.1
# (ALWAYS_ALLOW's "marketing manager" removal), 1.2 (hard exclusion ->
# "excluded"), and 1.3 (the two-axis seniority/domain split, replacing the
# old single-regex tier). Several of the pre-Phase-1 rows' expected tiers
# changed here on purpose: the two-axis split is a genuinely different (and
# stricter) algorithm than the old single TARGET_TIER regex, not a
# regression — see match.py's fit_tier()/domain_tier() comments. This is the
# same demotion pattern the Phase 0 report flagged in real SG/NL data (e.g.
# "VP, Design Strategy" has real seniority but only a DOMAIN_BROADER
# "strategy" match, not a DOMAIN_CORE design phrase, so the weaker domain
# axis correctly pulls it down to "below").
TITLE_CASES = [
    ("Director, Product Design", True, "target"),
    ("Head of UX Research", True, "target"),
    ("Senior Product Designer", True, "below"),
    ("Software Engineer", False, "stretch"),  # was "below" pre-1.3 — no seniority AND no domain signal at all
    ("Design Engineer", True, "stretch"),  # alwaysAllow-relevant, but "design engineer" isn't a DOMAIN_CORE phrase and has no seniority word either
    ("VP, Design Strategy", True, "below"),  # was "target" pre-1.3 — strong seniority, but "strategy" is only DOMAIN_BROADER, not DOMAIN_CORE
    ("Product Marketing Manager", True, "below"),  # still relevant via the narrow "product marketing" ALWAYS_ALLOW exception (1.1) — "manager" alone isn't a target-tier word
    ("Sales Manager", False, "stretch"),  # was "below" pre-1.3
    ("Data Scientist, Product Analytics", False, "below"),
    # 1.1 acceptance case: bare "marketing manager" no longer bypasses via
    # ALWAYS_ALLOW — NEGATIVE's "marketing" correctly excludes it now.
    ("Growth Marketing Manager, Credit Products", False, "below"),
    # 1.2 acceptance cases: hard exclusion.
    ("Junior Product Designer", False, "excluded"),
    ("Associate Product Designer", False, "excluded"),  # "associate" with no AVP/VP/Director qualifier
    ("Associate Director, Product Design", True, "target"),  # the AVP/VP/Director exception — not excluded
    ("Associate/AVP, Product Experience", True, "below"),  # acceptance case: not excluded (AVP qualifies), but "Product Experience" is only DOMAIN_BROADER so overall tier is "below", not "target"
    # 1.3 acceptance case: catering + the newly-added "onboard" both hard-exclude.
    ("BA Cityflyer Catering & Onboard Product Lead", False, "excluded"),
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

    print("-- match_negative_filters (1.2/1.3 hard exclusion, direct) --")
    NEGATIVE_FILTER_CASES = [
        ("Junior Product Designer", ["junior"]),
        ("Procurement Manager", ["procurement"]),  # 1.3 extension
        ("Cabin Crew Product Lead", ["cabin crew"]),  # 1.3 extension
        ("Associate Product Designer", ["associate (without AVP/VP/Director)"]),
        ("Associate Director, Product Design", []),  # the AVP/VP/Director exception
        ("Senior Product Designer", []),
    ]
    for title, expected_hits in NEGATIVE_FILTER_CASES:
        got = match_negative_filters(title)
        ok = got == expected_hits
        failures += 0 if ok else 1
        print(f"  {'OK ' if ok else 'FAIL'}  {title!r:35s} -> {got!r} (expected {expected_hits!r})")

    print("-- title/location normalization (1.5) --")
    for raw_title, raw_location, expected_title, expected_location in NORMALIZE_CASES:
        got_title, got_location = normalize_scraped_title(raw_title, raw_location)
        ok = got_title == expected_title and got_location == expected_location
        failures += 0 if ok else 1
        print(f"  {'OK ' if ok else 'FAIL'}  {raw_title!r:45s} @ {raw_location!r:25s} -> "
              f"{got_title!r:35s} @ {got_location!r:30s} (expected {expected_title!r} @ {expected_location!r})")

    print("-- build_fresh_roles (multi-source + NaN handling + 1.4 cross-site dedupe + 2.2 open-market branch) --")
    try:
        fresh, fresh_open_market = build_fresh_roles(FRESH_ROLES_CASES, INDEX, "2026-09-09")
        crashed = False
    except TypeError as e:
        fresh, fresh_open_market = {}, {}
        crashed = True
        print(f"  FAIL  build_fresh_roles crashed: {e}")

    id_wise_design_london = role_identity("wise", "Head of Design", "London")
    id_wise_design_unknown = role_identity("wise", "Head of Design", "")
    id_wise_senior_pd_sg = role_identity("wise", "Senior Product Designer", "Singapore")
    id_wise_ux_researcher_dubai = role_identity("wise", "UX Researcher", "Dubai")
    id_hsbc_senior_ux_researcher_sg = role_identity("hsbc", "Senior UX Researcher", "Singapore")

    fresh_checks = [
        ("did not crash on NaN fields (the actual production bug)", not crashed),
        ("kept exactly 5 distinct identities (2 dropped no-company-match [unrelated + NaN], 2 dropped "
         "title-not-relevant [irrelevant + NaN], 1 duplicate URL, and case #1/#10's li+google merged into one "
         "identity rather than counting as a 6th — 1.4)", len(fresh) == 5),
        ("li+google Head of Design/Wise/London merged into one identity (1.4)", id_wise_design_london in fresh),
        ("...merged role's canonical source is li, not google (outranks it in SOURCE_PRECEDENCE)",
         fresh.get(id_wise_design_london, (None, {}))[1].get("source") == "li"),
        ("...merged role's sources array retains both li and google",
         sorted(fresh.get(id_wise_design_london, (None, {}))[1].get("sources", [])) == ["google", "li"]),
        ("...merged role's canonical url is li's (case #1's), not google's (case #10's)",
         fresh.get(id_wise_design_london, (None, {}))[1].get("url") == "https://x.test/1"),
        ("wise role filed under correct slug", fresh.get(id_wise_design_london, (None, {}))[0] == "wise"),
        ("hsbc role tagged source=indeed", fresh.get(id_hsbc_senior_ux_researcher_sg, (None, {}))[1].get("source") == "indeed"),
        ("hsbc role filed under correct slug", fresh.get(id_hsbc_senior_ux_researcher_sg, (None, {}))[0] == "hsbc"),
        ("NaN-location role kept, location is '' — not 'Not specified' (1.5)",
         fresh.get(id_wise_design_unknown, (None, {}))[1].get("location") == ""),
        ("glassdoor role tagged source=glassdoor", fresh.get(id_wise_senior_pd_sg, (None, {}))[1].get("source") == "glassdoor"),
        ("bayt role tagged source=bayt", fresh.get(id_wise_ux_researcher_dubai, (None, {}))[1].get("source") == "bayt"),
    ]
    for label, ok in fresh_checks:
        failures += 0 if ok else 1
        print(f"  {'OK ' if ok else 'FAIL'}  {label}")

    print("-- build_fresh_roles open-market branch (2.2) --")
    id_om_startup_sg = role_identity(
        normalize_employer_name("Some Random Singapore Startup Pte Ltd"), "Head of Product Design", "Singapore"
    )
    id_om_startup_uae = role_identity(
        normalize_employer_name("Some Random Dubai Startup FZE"), "Head of Product Design", "Dubai, UAE"
    )
    om_checks = [
        ("kept exactly 2 open-market identities (case #11+#11b merged into 1, case #15 is the 2nd; "
         "#12 fails the strict gate, #13 is agency-blocklisted, #14 isn't an OPEN_MARKET_LOCATIONS market)",
         len(fresh_open_market) == 2),
        ("the SG startup role is keyed under its normalized employer text, not a slug",
         id_om_startup_sg in fresh_open_market),
        ("...carries the raw employer display name",
         fresh_open_market.get(id_om_startup_sg, (None, {}))[1].get("employer") == "Some Random Singapore Startup Pte Ltd"),
        ("...tagged with market=Singapore", fresh_open_market.get(id_om_startup_sg, (None, {}))[1].get("market") == "Singapore"),
        ("...li+glassdoor (cases #11/#11b) merged, sources retains both",
         sorted(fresh_open_market.get(id_om_startup_sg, (None, {}))[1].get("sources", [])) == ["glassdoor", "li"]),
        ("...canonical source is li (outranks glassdoor)",
         fresh_open_market.get(id_om_startup_sg, (None, {}))[1].get("source") == "li"),
        ("the UAE startup role (case #15, 'Dubai, UAE' — the abbreviated form) is keyed under its "
         "normalized employer text too", id_om_startup_uae in fresh_open_market),
        ("...tagged with market=United Arab Emirates (via MARKET_ALIASES's 'uae', not a literal "
         "'united arab emirates' substring)",
         fresh_open_market.get(id_om_startup_uae, (None, {}))[1].get("market") == "United Arab Emirates"),
        ("...tagged with source=indeed", fresh_open_market.get(id_om_startup_uae, (None, {}))[1].get("source") == "indeed"),
        ("Robert Walters (case #13) did not leak into the open-market feed despite otherwise qualifying",
         all(r.get("employer") != "Robert Walters" for _, r in fresh_open_market.values())),
        ("the Germany case (#14) did not leak in either — not an OPEN_MARKET_LOCATIONS market",
         all(r.get("market") != "" and "Germany" not in (r.get("location") or "") for _, r in fresh_open_market.values())),
    ]
    for label, ok in om_checks:
        failures += 0 if ok else 1
        print(f"  {'OK ' if ok else 'FAIL'}  {label}")

    print("-- open-market: _open_market_for() (2.1, UAE added 2026-09-23) --")
    OPEN_MARKET_LOCATION_CASES = [
        ("Singapore", "Singapore"),
        ("Amsterdam, North Holland, Netherlands", "Netherlands"),
        ("Jurong East, West Region, Singapore", "Singapore"),  # real Phase 0 data shape
        ("SG", "Singapore"),  # bare country-code form, also seen in real Phase 0 data
        ("NL", "Netherlands"),
        ("Dubai, United Arab Emirates", "United Arab Emirates"),  # the spelled-out form (matches LOCATIONS verbatim)
        ("Abu Dhabi, United Arab Emirates", "United Arab Emirates"),
        ("Dubai, UAE", "United Arab Emirates"),  # the common abbreviated form — via MARKET_ALIASES, not a literal LOCATIONS substring
        ("AE", "United Arab Emirates"),  # bare country-code form
        ("Kuala Lumpur, Malaysia", None),
        ("", None),
    ]
    for raw, expected in OPEN_MARKET_LOCATION_CASES:
        got = _open_market_for(raw)
        ok = got == expected
        failures += 0 if ok else 1
        print(f"  {'OK ' if ok else 'FAIL'}  {raw!r:45s} -> {got!r} (expected {expected!r})")

    print("-- open-market: is_agency() (2.3) --")
    AGENCY_CASES = [
        ("Robert Walters", True),
        ("Michael Page", True),
        ("Robert Walters Pte Ltd", True),  # legal suffixes stripped, still an exact match
        ("Robert Half International", False),  # deliberately NOT a match — exact-match only, not fuzzy containment (see is_agency()'s docstring)
        ("Some Random Startup", False),
    ]
    for employer, expected in AGENCY_CASES:
        got = is_agency(employer)
        ok = got == expected
        failures += 0 if ok else 1
        print(f"  {'OK ' if ok else 'FAIL'}  {employer!r:30s} -> {got!s:5s} (expected {expected!s})")

    print("-- open-market: open_market_gate() (2.4) --")
    OPEN_MARKET_GATE_CASES = [
        ("Head of Product Design", "Random Co", (lambda _: False), True),
        ("Product Designer", "Random Co", (lambda _: False), False),  # relevant, but only "below" tier
        ("Junior Product Designer", "Random Co", (lambda _: False), False),  # hard-excluded — not relevant at all
        ("Head of Product Design", "Robert Walters", is_agency, False),  # would otherwise qualify — agency-blocked
    ]
    for title, employer, agency_fn, expected in OPEN_MARKET_GATE_CASES:
        got = open_market_gate(title, employer, agency_fn)
        ok = got == expected
        failures += 0 if ok else 1
        print(f"  {'OK ' if ok else 'FAIL'}  {title!r:30s} @ {employer!r:20s} -> {got!s:5s} (expected {expected!s})")

    print("-- merge_and_prune openMarket branch (2.5/2.6): recency sort + expiry --")
    _now = datetime.now(timezone.utc)
    _stale_last_seen = (_now - timedelta(days=EXPIRY_DAYS + 16)).strftime("%Y-%m-%d")  # well past EXPIRY_DAYS
    _recent_last_seen = (_now - timedelta(days=3)).strftime("%Y-%m-%d")  # well within EXPIRY_DAYS
    _today = _now.strftime("%Y-%m-%d")
    existing_snapshot = {
        "companies": {},
        "openMarket": {"roles": [
            {"employer": "Acme Singapore Pte Ltd", "market": "Singapore", "title": "Head of Product Design",
             "location": "Singapore", "url": "https://x.test/OM-OLD", "postedDate": _stale_last_seen,
             "source": "bayt", "lastSeenAt": _stale_last_seen},  # should be pruned — stale
            {"employer": "Beta Netherlands BV", "market": "Netherlands", "title": "Staff Product Designer",
             "location": "Amsterdam, Netherlands", "url": "https://x.test/OM-KEEP", "postedDate": _recent_last_seen,
             "source": "li", "lastSeenAt": _recent_last_seen},  # not refreshed this run, but recent enough to carry over
        ]},
    }
    new_key = normalize_employer_name("Gamma Singapore Pte Ltd")
    new_identity = role_identity(new_key, "Lead Product Designer", "Singapore")
    fresh_open_market_for_merge = {
        new_identity: (new_key, {
            "employer": "Gamma Singapore Pte Ltd", "market": "Singapore", "title": "Lead Product Designer",
            "location": "Singapore", "url": "https://x.test/OM-NEW", "postedDate": _today,
            "source": "li", "sources": ["li"], "lastSeenAt": _today,
        })
    }
    merged_snapshot = merge_and_prune(
        existing_snapshot, {}, _today, fresh_open_market_roles=fresh_open_market_for_merge
    )
    om_roles_out = merged_snapshot["openMarket"]["roles"]
    merge_om_checks = [
        ("companies{} passed through untouched (no tracked-company fresh roles given)", merged_snapshot["companies"] == {}),
        ("stale bayt role pruned past EXPIRY_DAYS", all(r["url"] != "https://x.test/OM-OLD" for r in om_roles_out)),
        ("recent li role carried over even though not refreshed this run",
         any(r["url"] == "https://x.test/OM-KEEP" for r in om_roles_out)),
        ("this run's new role present", any(r["url"] == "https://x.test/OM-NEW" for r in om_roles_out)),
        ("exactly 2 roles survive (1 pruned, 1 carried over, 1 added)", len(om_roles_out) == 2),
        ("output sorted newest-postedDate-first (2.6)",
         [r["url"] for r in om_roles_out] == ["https://x.test/OM-NEW", "https://x.test/OM-KEEP"]),
    ]
    for label, ok in merge_om_checks:
        failures += 0 if ok else 1
        print(f"  {'OK ' if ok else 'FAIL'}  {label}")

    print("-- exact-match key collisions (reviewed allowlist) --")
    got_collisions = find_collisions(COMPANIES, ALIASES)
    ok = got_collisions == KNOWN_COLLISIONS
    failures += 0 if ok else 1
    print(f"  {'OK ' if ok else 'FAIL'}  find_collisions() == KNOWN_COLLISIONS")
    if not ok:
        unexpected = {k: v for k, v in got_collisions.items() if k not in KNOWN_COLLISIONS}
        missing = {k: v for k, v in KNOWN_COLLISIONS.items() if k not in got_collisions}
        if unexpected:
            print(f"        unexpected new collision(s), go fix companies.py: {unexpected}")
        if missing:
            print(f"        expected collision(s) no longer present (update KNOWN_COLLISIONS if fixed on purpose): {missing}")

    total_cases = (
        len(CASES) + len(TITLE_CASES) + len(NEGATIVE_FILTER_CASES) + len(NORMALIZE_CASES)
        + len(fresh_checks) + len(om_checks)
        + len(OPEN_MARKET_LOCATION_CASES) + len(AGENCY_CASES) + len(OPEN_MARKET_GATE_CASES)
        + len(merge_om_checks) + 1
    )
    print(f"\n{total_cases - failures}/{total_cases} passed")
    if failures:
        raise SystemExit(f"{failures} case(s) failed")


if __name__ == "__main__":
    run()
