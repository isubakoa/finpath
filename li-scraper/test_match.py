"""
Offline checks for match.py and scrape.py's matching/merging -- no network, no
JobSpy. Run: python3 test_match.py
"""

from datetime import datetime, timedelta, timezone

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
    build_fresh_roles,                                    # it's only imported lazily inside run_indeed_searches()
    merge_and_prune,
    CANONICAL_MARKETS,
    EXPIRY_DAYS,
    market_for_location,
    sponsorship_signal,
    SPONSORSHIP_KEYWORDS,
)

INDEX = build_index(COMPANIES, ALIASES)

# build_fresh_roles() takes (source, row) tuples and is source-agnostic: every
# source's rows go through the same matching, filtering and dedup, and keep the
# source they came from.
#
# The float("nan") cases reproduce a real crash: JobSpy rows are pandas, a
# missing field is NaN (a truthy float), and it reached match.py's regexes.
# scrape.py's _clean_str() and match.py's _normalize() guard against it.
#
# Cases #1 (li) and #10 (welcometonl) are the same posting (Wise / Head of
# Design / London) on two sites with two URLs -- they must merge into one role.
FRESH_ROLES_CASES = [
    ("li", {"job_url": "https://x.test/1", "company": "Wise", "title": "Head of Design", "location": "London"}),
    # Indeed returns descriptions (LI's stay off): exercises the sponsorship signal
    # on the tracked-company branch.
    ("indeed", {"job_url": "https://x.test/2", "company": "HSBC Holdings plc", "title": "Senior UX Researcher", "location": "Singapore",
                "description": "We offer visa sponsorship for qualified candidates."}),
    # Untracked employer with a relevant title, but a bare "Berlin" location has no
    # country marker and "berlin" is deliberately not a CITY_ALIASES entry (a real
    # "Berlin, El Salvador" posting exists), so is_known_market() drops it before
    # the open-market gate.
    ("indeed", {"job_url": "https://x.test/3", "company": "Some Totally Unrelated Company", "title": "Head of Design", "location": "Berlin"}),  # dropped from tracked matching (no slug) and from open market (unresolvable location)
    ("li", {"job_url": "https://x.test/4", "company": "Wise", "title": "Software Engineer", "location": "London"}),  # dropped: title not relevant
    ("li", {"job_url": "https://x.test/1", "company": "Wise", "title": "Head of Design (dup)", "location": "London"}),  # dropped: duplicate URL
    # Also proves open market's empty-employer guard: relevant title, accepted
    # location, but a NaN/blank employer must not reach the feed.
    ("li", {"job_url": "https://x.test/5", "company": float("nan"), "title": "Head of Design", "location": "London"}),  # dropped, not crashed: NaN company (dropped from BOTH branches — no slug, and open-market's employer guard)
    ("li", {"job_url": "https://x.test/6", "company": "Wise", "title": "Head of Design", "location": float("nan")}),  # kept: NaN location -> ""
    ("indeed", {"job_url": "https://x.test/7", "company": "Wise", "title": float("nan"), "location": "London"}),  # dropped, not crashed: NaN title
    ("bayt", {"job_url": "https://x.test/8", "company": "Wise", "title": "Senior Product Designer", "location": "Singapore"}),  # kept, source=bayt
    # The canonical record stays li's (case #1, no description, wins
    # SOURCE_PRECEDENCE), but this row's description has a sponsorship keyword --
    # the merged role's sponsorshipSignal must keep it (union across sources).
    ("welcometonl", {"job_url": "https://x.test/9", "company": "Wise", "title": "Head of Design", "location": "London",
                "description": "We welcome international candidates from around the world."}),  # same identity as case #1 — merges, doesn't add another kept entry
    ("bayt", {"job_url": "https://x.test/10", "company": "Wise", "title": "UX Researcher", "location": "Dubai"}),  # kept, source=bayt
    # Open-market cases: none of these employers are tracked companies.
    ("li", {"job_url": "https://x.test/11", "company": "Some Random Singapore Startup Pte Ltd", "title": "Head of Product Design", "location": "Singapore"}),  # kept open-market: relevant, target tier, SG
    # Three sponsorship keywords at once; merges with #11 (li, no description) into
    # the same open-market identity -- the union-merge check on the open-market side.
    ("bayt", {"job_url": "https://x.test/11b", "company": "Some Random Singapore Startup Pte Ltd", "title": "Head of Product Design", "location": "Singapore",
                   "description": "We offer relocation support and welcome applications from international candidates as part of our Global Talent program."}),  # same open-market identity as #11, different site/URL
    # "below"-tier title: open_market_gate() accepts target or below. A different
    # title from #11/#11b, so its own kept entry, not a merge.
    ("indeed", {"job_url": "https://x.test/12", "company": "Some Random Singapore Startup Pte Ltd", "title": "Product Designer", "location": "Singapore"}),  # kept open-market: below tier, relevant, SG
    # Staffing agency, otherwise qualifying: agencies are included in open market.
    ("li", {"job_url": "https://x.test/13", "company": "Robert Walters", "title": "Head of Product Design", "location": "Netherlands"}),  # kept open-market: relevant, target tier (agencies included)
    # A searched market outside SG/NL/UAE: open market covers every searched market.
    ("li", {"job_url": "https://x.test/14", "company": "Some Random Startup GmbH", "title": "Head of Product Design", "location": "Germany"}),  # kept open-market: relevant, target tier, Germany
    # "UAE" abbreviation (not the spelled-out LOCATIONS form) exercises MARKET_ALIASES.
    ("indeed", {"job_url": "https://x.test/15", "company": "Some Random Dubai Startup FZE", "title": "Head of Product Design", "location": "Dubai, UAE"}),  # kept open-market: relevant, target tier, UAE via alias
    # Negation guard: the description contains "visa sponsorship" but negated
    # ("unfortunately ... not able to offer"), so sponsorshipSignal must be [].
    ("indeed", {"job_url": "https://x.test/16", "company": "Some Random NL Open Market Co", "title": "Head of Product Design", "location": "Netherlands",
                "description": "Unfortunately, we are not able to offer visa sponsorship for this role at this time."}),  # kept open-market; sponsorshipSignal must be [] despite the substring
    # Regression test: an otherwise-qualifying India posting must not reach open
    # market -- India isn't a searched market.
    ("li", {"job_url": "https://x.test/17", "company": "Some Random Startup Pvt Ltd", "title": "Head of Product Design", "location": "Bengaluru, India"}),  # dropped open-market: India isn't a searched market
    # Indeed's "City, StateCode, CountryCode" shape with no country name must
    # resolve via ISO_CODE_TO_MARKET (Germany) and be kept -- a naive "drop
    # anything unresolvable" rule would wrongly hide it.
    ("indeed", {"job_url": "https://x.test/18", "company": "Some Random Berlin Startup GmbH", "title": "Head of Product Design", "location": "Berlin, BE, DE"}),  # kept open-market: resolves via last-comma-segment ISO code, market=Germany
]

# (raw_title, raw_location, expected_title, expected_location) for
# normalize_scraped_title() -- a port of the app's normalizeScrapedTitle().
NORMALIZE_CASES = [
    # CTA suffix stripped regardless of whether location is already known.
    ("Head of Design - View Job", "London", "Head of Design", "London"),
    ("Senior Product Designer | Apply Now", "Singapore", "Senior Product Designer", "Singapore"),
    # A trailing "City, Country" is recovered from the title only when the site
    # gave no location. It needs a comma before the city: a title made entirely of
    # Title-Case words ("Staff Product Designer Rotterdam, Netherlands") is
    # ambiguous and deliberately left alone -- same limitation as the app's regex.
    ("Product Designer, Amsterdam, Netherlands", "", "Product Designer", "Amsterdam, Netherlands"),
    ("Product Designer, Amsterdam, Netherlands", "Not specified", "Product Designer", "Amsterdam, Netherlands"),
    # The known ambiguity itself: left untouched rather than guessed wrong.
    ("Staff Product Designer Rotterdam, Netherlands", "", "Staff Product Designer Rotterdam, Netherlands", ""),
    # A normal comma'd title is left alone once a real location is present.
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
    # "International" is deliberately not stripped as a legal suffix (it once
    # turned "Network International" into a bare, dangerously generic
    # "network"). Network International itself is no longer tracked, so this
    # guards the same rule with a company that is.
    ("Fidelity International", "fidelity-international"),
    ("Random Fidelity Solutions Inc", None),  # must NOT false-match via "fidelity"
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
# exact-match key -- reviewed and accepted. build_index() is last-write-wins,
# so without this check a new collision would silently misfile postings.
#
#   "boost" -> boost / boost-bank: affiliated companies (Boost Bank is Axiata's
#   Boost + RHB) sharing one careers board, whose names become identical once
#   "Bank" is stripped. A stray misfile between them is harmless, and special-
#   casing _normalize() for one pair would be riskier.
#
# If this fails with something new, fix the aliases in data/companies.json --
# don't widen the allowlist.
KNOWN_COLLISIONS = {
    "boost": ["boost", "boost-bank"],
}

# (title, expected is_role_relevant(), expected fit_tier()). Fit is two-axis:
# seniority x domain, the weaker wins -- e.g. "VP, Design Strategy" has strong
# seniority but only DOMAIN_BROADER "strategy", so it's "below".
TITLE_CASES = [
    ("Director, Product Design", True, "target"),
    ("Head of UX Research", True, "target"),
    ("Senior Product Designer", True, "below"),
    ("Software Engineer", False, "stretch"),  # no seniority and no domain signal
    ("Design Engineer", True, "stretch"),  # alwaysAllow-relevant, but "design engineer" isn't a DOMAIN_CORE phrase and has no seniority word
    ("VP, Design Strategy", True, "below"),  # strong seniority, but "strategy" is only DOMAIN_BROADER
    ("Product Marketing Manager", True, "below"),  # relevant via the narrow "product marketing" ALWAYS_ALLOW exception; "manager" alone isn't target-tier
    ("Sales Manager", False, "stretch"),  # not relevant
    ("Data Scientist, Product Analytics", False, "below"),
    # Bare "marketing manager" doesn't bypass via ALWAYS_ALLOW; NEGATIVE's
    # "marketing" excludes it.
    ("Growth Marketing Manager, Credit Products", False, "below"),
    # Hard exclusions:
    ("Junior Product Designer", False, "excluded"),
    ("Associate Product Designer", False, "excluded"),  # "associate" with no AVP/VP/Director qualifier
    ("Associate Director, Product Design", True, "target"),  # the AVP/VP/Director exception — not excluded
    ("Associate/AVP, Product Experience", True, "below"),  # not excluded (AVP qualifies), but "Product Experience" is only DOMAIN_BROADER, so "below"
    # Catering and "onboard" both hard-exclude.
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
        ("Procurement Manager", ["procurement"]),
        ("Cabin Crew Product Lead", ["cabin crew"]),
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
         "title-not-relevant [irrelevant + NaN], 1 duplicate URL, and case #1/#10's li+welcometonl merged into one "
         "identity rather than counting as a 6th — 1.4)", len(fresh) == 5),
        ("li+welcometonl Head of Design/Wise/London merged into one identity (1.4)", id_wise_design_london in fresh),
        ("...merged role's canonical source is li, not welcometonl (outranks it in SOURCE_PRECEDENCE)",
         fresh.get(id_wise_design_london, (None, {}))[1].get("source") == "li"),
        ("...merged role's sources array retains both li and welcometonl",
         sorted(fresh.get(id_wise_design_london, (None, {}))[1].get("sources", [])) == ["li", "welcometonl"]),
        ("...merged role's canonical url is li's (case #1's), not welcometonl's (case #10's)",
         fresh.get(id_wise_design_london, (None, {}))[1].get("url") == "https://x.test/1"),
        ("...merged role's sponsorshipSignal keeps welcometonl's (case #9's) match even though li "
         "(no description) won canonical status — the UNION, not just the canonical record's own signal",
         fresh.get(id_wise_design_london, (None, {}))[1].get("sponsorshipSignal") == ["international candidates"]),
        ("hsbc role (indeed, case #2, has a description) carries its own sponsorshipSignal",
         fresh.get(id_hsbc_senior_ux_researcher_sg, (None, {}))[1].get("sponsorshipSignal") == ["visa sponsorship"]),
        ("wise role filed under correct slug", fresh.get(id_wise_design_london, (None, {}))[0] == "wise"),
        ("hsbc role tagged source=indeed", fresh.get(id_hsbc_senior_ux_researcher_sg, (None, {}))[1].get("source") == "indeed"),
        ("hsbc role filed under correct slug", fresh.get(id_hsbc_senior_ux_researcher_sg, (None, {}))[0] == "hsbc"),
        ("NaN-location role kept, location is '' — not 'Not specified' (1.5)",
         fresh.get(id_wise_design_unknown, (None, {}))[1].get("location") == ""),
        ("bayt role tagged source=bayt", fresh.get(id_wise_senior_pd_sg, (None, {}))[1].get("source") == "bayt"),
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
    id_om_nl_negation = role_identity(
        normalize_employer_name("Some Random NL Open Market Co"), "Head of Product Design", "Netherlands"
    )
    id_om_germany = role_identity(
        normalize_employer_name("Some Random Startup GmbH"), "Head of Product Design", "Germany"
    )
    # Case #3 (bare "Berlin") must NOT be kept; named so the assertion below can
    # check it.
    id_om_berlin_unrelated = role_identity(
        normalize_employer_name("Some Totally Unrelated Company"), "Head of Design", "Berlin"
    )
    # Case #17: an otherwise-qualifying India posting must not reach open market.
    id_om_india = role_identity(
        normalize_employer_name("Some Random Startup Pvt Ltd"), "Head of Product Design", "Bengaluru, India"
    )
    # Case #18: "City, StateCode, CountryCode" resolves via ISO_CODE_TO_MARKET -> Germany.
    id_om_berlin_iso = role_identity(
        normalize_employer_name("Some Random Berlin Startup GmbH"), "Head of Product Design", "Berlin, BE, DE"
    )
    # Case #12 ("Product Designer", below tier) is its own kept identity -- a
    # different title from #11/#11b, not a merge.
    id_om_startup_sg_below = role_identity(
        normalize_employer_name("Some Random Singapore Startup Pte Ltd"), "Product Designer", "Singapore"
    )
    # Case #13 (Robert Walters, an agency) is kept: agencies are included.
    id_om_robert_walters = role_identity(
        normalize_employer_name("Robert Walters"), "Head of Product Design", "Netherlands"
    )
    om_checks = [
        ("kept exactly 7 open-market identities (case #11+#11b merged into 1, case #12/below-tier, "
         "case #13/Robert Walters, case #14/Germany, case #15/UAE, case #16/NL, case #18/Berlin-"
         "via-ISO-code — all eligible now that the gate accepts target-or-below tier and no longer "
         "excludes agencies, and every one actually resolves to a searched market; #3/bare-Berlin, "
         "#5's NaN-employer row, and #17/India are the ones that correctly do NOT qualify)",
         len(fresh_open_market) == 7),
        ("case #3 (bare 'Berlin', no country marker) is NOT kept open-market (2026-10-17 — "
         "flipped back: market_for_location('Berlin') now returns None, so is_known_market() "
         "fails it before open_market_gate() is ever reached — see its dated FRESH_ROLES_CASES "
         "comment above)", id_om_berlin_unrelated not in fresh_open_market),
        ("case #17 (Bengaluru, India) is NOT kept open-market despite an otherwise fully-"
         "qualifying relevant/target title and real employer — direct proof the reported India "
         "leak is fixed", id_om_india not in fresh_open_market),
        ("case #18 (Berlin, BE, DE — Indeed's ISO-code shape) IS kept open-market — direct proof "
         "ISO_CODE_TO_MARKET's last-comma-segment resolution works, not just the full-country-"
         "name substring match", id_om_berlin_iso in fresh_open_market),
        ("...tagged with market=Germany, not a raw/unresolved fallback",
         fresh_open_market.get(id_om_berlin_iso, (None, {}))[1].get("market") == "Germany"),
        ("the Germany role (case #14) is now kept — 2026-09-23's broadening: no location ever "
         "gated it, only title/employer (open_market_gate())", id_om_germany in fresh_open_market),
        ("...tagged with market=Germany (market_for_location() label, not a gate)",
         fresh_open_market.get(id_om_germany, (None, {}))[1].get("market") == "Germany"),
        ("case #5's NaN-employer row (blank 'company' field) did NOT leak into the open-market "
         "feed despite an otherwise-qualifying relevant/target title and an eligible location — "
         "the explicit empty-employer guard in build_fresh_roles() catches it",
         all(r.get("employer") for r in (v[1] for v in fresh_open_market.values()))),
        ("the SG startup role is keyed under its normalized employer text, not a slug",
         id_om_startup_sg in fresh_open_market),
        ("...carries the raw employer display name",
         fresh_open_market.get(id_om_startup_sg, (None, {}))[1].get("employer") == "Some Random Singapore Startup Pte Ltd"),
        ("...tagged with market=Singapore", fresh_open_market.get(id_om_startup_sg, (None, {}))[1].get("market") == "Singapore"),
        ("...li+bayt (cases #11/#11b) merged, sources retains both",
         sorted(fresh_open_market.get(id_om_startup_sg, (None, {}))[1].get("sources", [])) == ["bayt", "li"]),
        ("...canonical source is li (outranks bayt)",
         fresh_open_market.get(id_om_startup_sg, (None, {}))[1].get("source") == "li"),
        ("the UAE startup role (case #15, 'Dubai, UAE' — the abbreviated form) is keyed under its "
         "normalized employer text too", id_om_startup_uae in fresh_open_market),
        ("...tagged with market=United Arab Emirates (via MARKET_ALIASES's 'uae', not a literal "
         "'united arab emirates' substring)",
         fresh_open_market.get(id_om_startup_uae, (None, {}))[1].get("market") == "United Arab Emirates"),
        ("...tagged with source=indeed", fresh_open_market.get(id_om_startup_uae, (None, {}))[1].get("source") == "indeed"),
        # Agencies are included in open market.
        ("Robert Walters (case #13) IS now kept open-market — direct proof the 2026-09-28 "
         "open_market_gate() agency-blocklist removal took effect",
         id_om_robert_walters in fresh_open_market),
        ("...carries the raw employer display name",
         fresh_open_market.get(id_om_robert_walters, (None, {}))[1].get("employer") == "Robert Walters"),
        ("...tagged with market=Netherlands", fresh_open_market.get(id_om_robert_walters, (None, {}))[1].get("market") == "Netherlands"),
        # Below-tier titles are included in open market.
        ("case #12 (below-tier title 'Product Designer') IS now kept open-market — direct proof "
         "the 2026-09-28 open_market_gate() loosening (target-only -> target-or-below) took "
         "effect, not just that the location restriction stays removed",
         id_om_startup_sg_below in fresh_open_market),
        ("...carries the raw employer display name, same employer as #11/#11b but a distinct "
         "identity (different title)",
         fresh_open_market.get(id_om_startup_sg_below, (None, {}))[1].get("employer") == "Some Random Singapore Startup Pte Ltd"),
        ("...tagged with source=indeed (case #12's own source, not merged with #11/#11b's li/bayt)",
         fresh_open_market.get(id_om_startup_sg_below, (None, {}))[1].get("source") == "indeed"),
        # Sponsorship signal on the open-market branch.
        ("SG startup role's sponsorshipSignal is the union of li's (#11, no description) and "
         "bayt's (#11b, three keywords) — canonical source is still li, signal isn't",
         fresh_open_market.get(id_om_startup_sg, (None, {}))[1].get("sponsorshipSignal") ==
         sorted(["relocation support", "international candidates", "global talent"])),
        ("UAE startup role (case #15) has no description at all -> sponsorshipSignal is []",
         fresh_open_market.get(id_om_startup_uae, (None, {}))[1].get("sponsorshipSignal") == []),
        ("case #16 (NL) kept in the open-market feed on its own merits (relevant/target-tier/not agency)",
         id_om_nl_negation in fresh_open_market),
        ("...but its sponsorshipSignal is [] — the description contains the literal substring "
         "'visa sponsorship' but negated ('not able to offer'/'unfortunately' nearby), so the "
         "negation guard correctly suppresses the false positive",
         fresh_open_market.get(id_om_nl_negation, (None, {}))[1].get("sponsorshipSignal") == []),
    ]
    for label, ok in om_checks:
        failures += 0 if ok else 1
        print(f"  {'OK ' if ok else 'FAIL'}  {label}")

    print("-- open-market: market_for_location() (2.1 -> broadened to all LOCATIONS, 2026-09-23; "
          "2026-10-17 -> ISO code + city-alias resolution, returns None when unresolved) --")
    MARKET_FOR_LOCATION_CASES = [
        ("Singapore", "Singapore"),
        ("Amsterdam, North Holland, Netherlands", "Netherlands"),
        ("Jurong East, West Region, Singapore", "Singapore"),  # real Phase 0 data shape
        ("SG", "Singapore"),  # bare country-code form, also seen in real Phase 0 data
        ("NL", "Netherlands"),
        ("Dubai, United Arab Emirates", "United Arab Emirates"),  # the spelled-out form (matches LOCATIONS verbatim)
        ("Abu Dhabi, United Arab Emirates", "United Arab Emirates"),  # both UAE cities collapse to one canonical market
        ("Dubai, UAE", "United Arab Emirates"),  # the common abbreviated form — via MARKET_ALIASES, not a literal LOCATIONS substring
        ("AE", "United Arab Emirates"),
        # Every searched location resolves to a market label.
        ("Kuala Lumpur, Malaysia", "Malaysia"),
        ("Berlin, Germany", "Germany"),  # a bare-country LOCATIONS entry, well outside the old 3-market allowlist
        ("Sydney, NSW, Australia", "Australia"),
        ("Tokyo, Japan", "Japan"),
        # ISO_CODE_TO_MARKET's last-segment pass: "City, StateCode, CountryCode".
        ("Berlin, BE, DE", "Germany"),
        ("London, ENG, GB", "United Kingdom"),
        ("Stockholm, AB, SE", "Sweden"),
        ("Outram, S00, SG", "Singapore"),
        # CITY_ALIASES: "Greater X Area" with no country marker.
        ("Greater Tokyo Area", "Japan"),
        ("Greater Kuala Lumpur", "Malaysia"),
        # Smaller Dutch cities and provinces (2026-10-25).
        ("Haarlem, North Holland", "Netherlands"),
        ("Hoofddorp", "Netherlands"),
        ("Almere Stad", "Netherlands"),
        ("Weesp, Noord-Holland", "Netherlands"),
        ("Greater Alkmaar Area", "Netherlands"),
        ("Gelderland", "Netherlands"),
        # Left out on purpose: short names inside other words.
        ("Ede, Ethiopia", None),
        # A location we never search returns None, so build_fresh_roles() drops it.
        ("Reykjavik, Iceland", None),
        ("Bengaluru, India", None),
        ("", None),
        # "berlin" is deliberately not a bare CITY_ALIASES entry -- a real "Berlin, El
        # Salvador" posting exists. Must resolve to nothing.
        ("Berlin, El Salvador", None),
    ]
    for raw, expected in MARKET_FOR_LOCATION_CASES:
        got = market_for_location(raw)
        ok = got == expected
        failures += 0 if ok else 1
        print(f"  {'OK ' if ok else 'FAIL'}  {raw!r:45s} -> {got!r} (expected {expected!r})")

    print("-- open-market: CANONICAL_MARKETS derivation (2026-09-23, sanity; "
          "LOCATIONS trimmed 25 -> 15 on 2026-09-24 — see below) --")
    canonical_checks = [
        # A tripwire, not a derived value: 15 LOCATIONS entries -> 15 distinct markets.
        # Update deliberately if LOCATIONS changes.
        ("15 distinct canonical markets from 15 LOCATIONS entries (no more "
         "multi-entry collapsing since only one UAE entry remains)",
         len(CANONICAL_MARKETS) == 15),
        ("Singapore present (bare LOCATIONS entry, unchanged)", "Singapore" in CANONICAL_MARKETS),
        ("Germany present — never eligible for open market before the broadening round",
         "Germany" in CANONICAL_MARKETS),
        ("Malaysia present (collapsed from 'Kuala Lumpur, Malaysia')", "Malaysia" in CANONICAL_MARKETS),
        ("United Arab Emirates present exactly once (from the single remaining Dubai entry)",
         CANONICAL_MARKETS.count("United Arab Emirates") == 1),
        ("Taiwan absent — cut in the 2026-09-24 location trim",
         "Taiwan" not in CANONICAL_MARKETS),
        ("France absent — cut in the 2026-09-24 location trim",
         "France" not in CANONICAL_MARKETS),
    ]
    for label, ok in canonical_checks:
        failures += 0 if ok else 1
        print(f"  {'OK ' if ok else 'FAIL'}  {label}")

    print("-- sponsorship_signal() (2026-09-23, direct) --")
    SPONSORSHIP_CASES = [
        ("We offer visa sponsorship for qualified candidates.", ["visa sponsorship"]),
        ("VISA SPONSORSHIP available for the right candidate!", ["visa sponsorship"]),  # case-insensitive
        ("We welcome international candidates from around the world.", ["international candidates"]),
        (
            "We offer relocation support and welcome applications from international "
            "candidates as part of our Global Talent program.",
            ["relocation support", "international candidates", "global talent"],
        ),  # all 4 keywords present bar one, in encounter order — not alphabetical
        ("Unfortunately, we are not able to offer visa sponsorship for this role at this time.", []),  # negated
        ("No relocation support is provided for this position.", []),  # negated ("no ")
        ("This role does not include visa sponsorship.", []),  # negated ("does not")
        ("Great benefits and a competitive salary package.", []),  # no keyword at all
        ("", []),  # empty description — the common case for a LinkedIn-only row
        (None, []),  # missing description field entirely (row.get() returns None)
    ]
    for description, expected in SPONSORSHIP_CASES:
        got = sponsorship_signal(description)
        ok = got == expected
        failures += 0 if ok else 1
        shown = (description[:55] + "…") if description and len(description) > 55 else description
        print(f"  {'OK ' if ok else 'FAIL'}  {shown!r:60s} -> {got!r} (expected {expected!r})")
    # Every keyword actually appears in at least one positive case above — guards against a
    # future SPONSORSHIP_KEYWORDS edit silently going untested.
    tested_hits = {kw for _, hits in SPONSORSHIP_CASES for kw in hits}
    all_covered = tested_hits == set(SPONSORSHIP_KEYWORDS)
    failures += 0 if all_covered else 1
    print(f"  {'OK ' if all_covered else 'FAIL'}  every SPONSORSHIP_KEYWORDS entry is exercised by at least one case above")

    print("-- open-market: open_market_gate() (2.4) --")
    # open_market_gate(title, employer): relevant and target-or-below tier only.
    # "Design Coordinator" proves "stretch" still doesn't qualify; agencies
    # (Robert Walters) qualify like anyone else.
    OPEN_MARKET_GATE_CASES = [
        ("Head of Product Design", "Random Co", True),  # relevant, "below" tier — qualifies
        ("Product Designer", "Random Co", True),  # relevant, "below" tier — now qualifies (was False pre-2026-09-28)
        # Relevant (bare "design" matches POSITIVE) but no DOMAIN_CORE/BROADER phrase,
        # so domain is "stretch" and the weaker axis wins.
        ("Design Coordinator", "Random Co", False),  # relevant, but "stretch" tier — still excluded
        ("Junior Product Designer", "Random Co", False),
        ("Head of Product Design", "Robert Walters", True),  # agency, target tier — qualifies
    ]
    for title, employer, expected in OPEN_MARKET_GATE_CASES:
        got = open_market_gate(title, employer)
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
            print(f"        unexpected new collision(s), go fix companies.json: {unexpected}")
        if missing:
            print(f"        expected collision(s) no longer present (update KNOWN_COLLISIONS if fixed on purpose): {missing}")

    total_cases = (
        len(CASES) + len(TITLE_CASES) + len(NEGATIVE_FILTER_CASES) + len(NORMALIZE_CASES)
        + len(fresh_checks) + len(om_checks)
        + len(MARKET_FOR_LOCATION_CASES) + len(canonical_checks)
        + len(SPONSORSHIP_CASES) + 1  # +1: the all_covered SPONSORSHIP_KEYWORDS-coverage check
        + len(OPEN_MARKET_GATE_CASES)
        + len(merge_om_checks) + 1  # +1: find_collisions() == KNOWN_COLLISIONS
    )
    print(f"\n{total_cases - failures}/{total_cases} passed")
    if failures:
        raise SystemExit(f"{failures} case(s) failed")


if __name__ == "__main__":
    run()
