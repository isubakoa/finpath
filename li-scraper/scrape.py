"""
FinPath — LI + Indeed + Glassdoor + Google + Bayt coverage via JobSpy
(github.com/speedyapply/JobSpy)

Runs keyword searches against five of JobSpy's eight supported sites (your
trimmed Product + Design/UX title list, across your target-region list — see
SEARCH_TERMS/LOCATIONS below). Writes li-snapshot.json with two top-level
sections:
  - `companies: { <slug>: { roles: [...] } }` — results (a) from one of the
    231 tracked companies — matched by name, see match.py — that (b) pass
    the exact same isRoleRelevant() title filter index.html itself applies.
    This is the original shape check.php has always expected from
    js-scraper's snapshot.json, byte-for-byte unchanged by Phase 2.
  - `openMarket: { roles: [...] }` (Phase 2, new; broadened to all 25
    LOCATIONS 2026-09-23) — a flat, no-slug list of postings that matched NO
    tracked company but are still worth surfacing: it clears
    open_market_gate() (relevant, real target-tier fit, not on the
    agencies.py blocklist) — see build_fresh_roles()/open_market_gate(). No
    location restriction of its own beyond that — every location this file
    already searches (all of LOCATIONS, not a narrower subset) is eligible;
    a `market` field (see market_for_location()) labels which one, purely
    for display/filtering, never for exclusion. Sorted newest-first. Each role
    in EITHER section carries its own `source` ("li", "indeed", "glassdoor",
    "google", or "bayt") plus a `sources` array (Phase 1.4) for cross-site
    corroboration, so the frontend can badge it correctly. LI and Indeed are
    both queried unconditionally for every combo, open-market locations
    included — see run_searches() below — so every open-market market has
    the same two-source floor as every tracked-company market does. As of
    2026-09-23, both sections also carry `sponsorshipSignal` (a list of
    matched sponsorship/relocation phrases from the posting's own
    description — see SPONSORSHIP_KEYWORDS/sponsorship_signal() below);
    always `[]` for a LinkedIn-only role, since linkedin_fetch_description
    stays off (see run_searches()'s docstring) — Indeed/Glassdoor/Google/
    Bayt return a description with no extra request, so those sites are
    covered for free.
ZipRecruiter (US/Canada only — a poor fit for a mostly non-US target-region
list), Naukri (India) and BDJobs (Bangladesh) were deliberately left out —
see README.md's "Widening scope further" for the reasoning behind every
site, included or not.

*** IMPORTANT — READ THIS BEFORE CHANGING TERMS/LOCATIONS/SCHEDULE ***
38 title phrases x 25 locations = 950 (term, location) combinations
(trimmed down from the original 108 x 17 = 1,836 in September 2026 for
freshness/footprint — see README.md's "How the rotation works" for the
before/after). Each combination is searched against LI, Indeed, Glassdoor
(where the location is one of the ~15 GLASSDOOR_COUNTRY supports — see that
dict below; Glassdoor's country list is a real subset of Indeed's, not a
guess) and Google — four independent requests per combo, added to in
September 2026 (Glassdoor/Google) on top of the original LI+Indeed pair —
each in its own try/except so one site's failure never takes another's
result down for that same combo. Only LI and Google get the randomized
pacing pause: Indeed has no rate limiting per JobSpy's own docs, and
Glassdoor isn't called out as rate-limited either so it's treated the same
way pending real evidence otherwise (see README's "Indeed coverage" section,
now covering all four of these); Google gets the same caution as LI despite
JobSpy's docs not calling it out specifically, because it scrapes google.com
directly rather than a job-board-specific endpoint, and Google is generally
known to be aggressive about blocking non-browser traffic at volume — a
documented hedge, not a confirmed constraint (worth revisiting once a few
real runs' logs are in, same as every other pacing choice in this file).
Bayt is architecturally different — no location parameter at all (it
"searches internationally" per JobSpy's own README) — so it isn't part of
this per-combo grid; see run_bayt_searches() below. There is still no way to
run all 950 combinations in a single pass without either proxies or
getting blocked on the LI side almost immediately — see
li-scraper/README.md's "How the rotation works" section for the full
explanation. Instead, each run covers one CHUNK of the full combination
list (COMBOS_PER_RUN of them), chosen deterministically from the current
time so consecutive scheduled runs walk through the whole list in order and
wrap back around — a full cycle takes ROTATION_CYCLE_HOURS (printed below)
to complete, unchanged by the addition of any of these sites since chunk
count is driven by combinations, not requests (each run just does more work
per chunk now — see README's "Widening scope further" for the actual
request-volume numbers and why the cycle length was deliberately kept as-is
rather than traded away for shorter runs). Results accumulate into
li-snapshot.json across runs (merged, not overwritten) and a role is only
dropped after EXPIRY_DAYS without being re-confirmed — so a company found on
Monday doesn't vanish from the tracker on Tuesday just because today's chunk
didn't include that company's search terms.

USAGE (locally or in the GitHub Actions workflow — see .github/workflows/):
    pip install -r requirements.txt
    python scrape.py
    python scrape.py --debug         # prints every kept/dropped result, no file write
    python scrape.py --chunk N       # force a specific chunk index (for testing)
"""

import json
import math
import os
import random
import sys
import time
from datetime import datetime, timedelta, timezone

from agencies import is_agency
from companies import COMPANIES, ALIASES
from match import (
    build_index,
    match_company,
    is_role_relevant,
    fit_tier,
    normalize_scraped_title,
    normalize_employer_name,
    role_identity,
    open_market_gate,
)

# ---- 1.4: cross-site dedupe source precedence — when the same normalized
# ---- (employer, title, location) identity is found via more than one site
# ---- (this run, or across runs once merge_and_prune() folds them together),
# ---- whichever site ranks lowest here supplies the role's canonical
# ---- url/source; every site that found it is retained in the role's
# ---- "sources" array regardless. "ats" is here (ranked highest) for
# ---- forward-compat with index.html's own directly-fetched roles, which
# ---- use the same precedence concept — this scraper itself never produces
# ---- an "ats"-sourced row today.
SOURCE_PRECEDENCE = {"ats": 0, "li": 1, "indeed": 2, "glassdoor": 3, "google": 4, "bayt": 5}


def _source_rank(source):
    return SOURCE_PRECEDENCE.get(source, len(SOURCE_PRECEDENCE))


def _merge_role_records(prior, new):
    """Combine a previously-seen role record with a freshly (re-)scraped one
    for the same normalized identity (1.4) — used both within a single run
    (build_fresh_roles(), when two of this run's raw rows collide) and across
    runs (merge_and_prune(), when this run reconfirms a role carried over
    from an earlier one). The freshest lastSeenAt/postedDate always wins (the
    newer scrape just reconfirmed the role is still live), but the canonical
    source/url is whichever record ranks higher in SOURCE_PRECEDENCE — so a
    lower-precedence site re-finding an already-established ATS/LinkedIn
    posting doesn't demote its canonical URL. "sources" is always the union
    of both, so corroboration accumulates and is never lost across runs.

    2026-09-23: "sponsorshipSignal" follows the exact same union reasoning as
    "sources" — once ANY corroborating source's description has surfaced a
    matched phrase, that evidence should never be lost just because the
    canonical record this round happens to come from a source with no
    description (e.g. a LinkedIn row winning on SOURCE_PRECEDENCE after an
    Indeed row already established a signal)."""
    sources = sorted(
        set(prior.get("sources") or ([prior["source"]] if prior.get("source") else []))
        | set(new.get("sources") or ([new["source"]] if new.get("source") else [])),
        key=_source_rank,
    )
    sponsorship_signal_union = sorted(
        set(prior.get("sponsorshipSignal") or []) | set(new.get("sponsorshipSignal") or [])
    )
    canonical = new if _source_rank(new.get("source")) <= _source_rank(prior.get("source")) else prior
    merged_role = dict(canonical)
    merged_role["sources"] = sources
    merged_role["sponsorshipSignal"] = sponsorship_signal_union
    merged_role["lastSeenAt"] = new.get("lastSeenAt") or prior.get("lastSeenAt")
    merged_role["postedDate"] = new.get("postedDate") or prior.get("postedDate")
    return merged_role


# ---- Sponsorship/relocation keyword heuristic (2026-09-23) — a per-posting
# ---- signal, separate from and complementary to companies.py's existing
# ---- manually-curated, company-level `sponsorship`/`sponsorshipNote` fields
# ---- (index.html's About panel already documents those as "a rough,
# ---- size-and-market-based signal, not a verified guarantee" — this is the
# ---- same spirit, applied per-listing instead of per-company). Literal,
# ---- case-insensitive substring matching against the posting's own
# ---- description text — deliberately not fuzzy/NLP, same "exact-match,
# ---- conservative" philosophy as agencies.py's is_agency() and
# ---- _open_market_for()'s MARKET_ALIASES: a false "this posting offers
# ---- sponsorship" claim is a worse failure than an occasional missed one.
SPONSORSHIP_KEYWORDS = [
    "visa sponsorship",
    "relocation support",
    "international candidates",
    "global talent",
]

# A small set of negation cues checked immediately before a matched phrase —
# catches the most common real-world false positive ("no visa sponsorship
# available", "unable to offer relocation support") without pretending to be
# a real negation parser. This is a best-effort guard, not a guarantee: it
# won't catch every phrasing (e.g. a negation several clauses earlier), which
# is exactly why the frontend surfaces this as "a phrase was found," never as
# "this employer confirmed sponsorship" — see index.html's About panel.
_SPONSORSHIP_NEGATION_CUES = (
    "no ", "not ", "without ", "unable to", "cannot ", "can't ", "won't ",
    "does not", "doesn't", "unfortunately",
)
_SPONSORSHIP_NEGATION_WINDOW_CHARS = 40


def _has_nearby_negation(text, match_start):
    prefix = text[max(0, match_start - _SPONSORSHIP_NEGATION_WINDOW_CHARS):match_start]
    return any(cue in prefix for cue in _SPONSORSHIP_NEGATION_CUES)


def sponsorship_signal(description):
    """Returns the list of SPONSORSHIP_KEYWORDS phrases found in `description`
    (empty list = none found, including for an empty/missing description —
    the common case for a LinkedIn-only row, since linkedin_fetch_description
    stays off). Always a list, never a bare boolean, so the frontend can show
    *which* phrase(s) actually matched rather than one opaque flag. Only the
    first occurrence of each keyword is checked against
    _has_nearby_negation() — good enough for a flag, not meant to be an
    exhaustive report of every mention in a long description."""
    if not description:
        return []
    text = description.lower()
    hits = []
    for keyword in SPONSORSHIP_KEYWORDS:
        idx = text.find(keyword.lower())
        if idx != -1 and not _has_nearby_negation(text, idx):
            hits.append(keyword)
    return hits

OUTPUT_PATH = "li-snapshot.json"

# ---- Trimmed September 2026 from the original 108 (27 Product + 81
# ---- Design/UX) down to 38 (9 Product + 29 Design/UX), to shrink the
# ---- rotation cycle for freshness/footprint reasons — see README.md's
# ---- "How the rotation works". This is your reviewed and confirmed list,
# ---- kept exactly as sent (including a deliberate choice to not carry
# ---- forward explicit "Director of Product"/"Head of Product"/"VP of
# ---- Product"-style Product-lane terms — flagged at the time, kept as-is
# ---- per your call). ----
PRODUCT_TERMS = [
    "Product Manager",
    "Product Owner",
    "Product Lead",
    "Product Strategist",
    "Marketing Manager",
    "Senior Product Manager",
    "Lead Product Manager",
    "Principal Product Manager",
    "Group Product Manager",
]

DESIGN_TERMS = [
    "Product Design Lead",
    "Senior Product Designer",
    "Senior UX Designer",
    "Senior UX/UI Designer",
    "Experience Designer",
    "User Experience Designer",
    "CX Designer",
    "Lead Product Designer",
    "Principal Product Designer",
    "Staff Product Designer",
    "Design Lead",
    "UX Lead",
    "UX Strategist",
    "UX Consultant",
    "UX Specialist",
    "UX Researcher",
    "User Researcher",
    "Design Researcher",
    "Lead UX Researcher",
    "Senior UX Researcher",
    "Senior Design Manager",
    "Senior UX Manager",
    "Design Strategist",
    "Design Thinking Lead",
    "Design Technologist",
    "Creative Technologist",
    "VP of Design",
    "Head of Product Design",
    "Head of Design",
]

SEARCH_TERMS = PRODUCT_TERMS + DESIGN_TERMS

# Your target-region list, updated September 2026. Bare country names
# ("Japan", "Australia", "Netherlands", ...) resolve broadly to anywhere in
# that country via LI's own location search; "City, Country" entries
# (Kuala Lumpur, Dubai, Abu Dhabi) resolve to that specific metro only —
# that distinction is intentional (your call), not something this script
# enforces itself. Note this list is actually longer than the 17-location
# one it replaces (Sydney/Melbourne merged into one broader "Australia",
# but Italy, France, Luxembourg, Switzerland, Austria, Denmark, Sweden,
# Norway, and Ireland are all new) — the freshness win below comes entirely
# from the term-list trim above, not from narrowing locations.
LOCATIONS = [
    "Singapore",
    "Hong Kong",
    "Taiwan",
    "Japan",
    "South Korea",
    "New Zealand",
    "Australia",
    "Netherlands",
    "Italy",
    "France",
    "Luxembourg",
    "Switzerland",
    "Austria",
    "Denmark",
    "Sweden",
    "Norway",
    "Germany",
    "Belgium",
    "Spain",
    "Portugal",
    "United Kingdom",
    "Ireland",
    "Kuala Lumpur, Malaysia",
    "Dubai, United Arab Emirates",
    "Abu Dhabi, United Arab Emirates",
]

# ---- 2026-09-23 — open market broadened to every LOCATIONS entry, per your
# ---- call: "keep it open and broad across all market but specific to the
# ---- pre-defined job titles." Previously (Phase 2.1, then the UAE addition)
# ---- an unmatched-company posting only got a second look for the
# ---- open-market feed when its location was one of a 3-market allowlist
# ---- (Singapore/Netherlands/UAE) — everywhere else it was dropped even
# ---- though this file already searches all 25 LOCATIONS for every one of
# ---- the 38 pre-defined titles (see the module docstring's combo-count
# ---- note). That allowlist is gone: eligibility is now open_market_gate()
# ---- alone (relevant + target-tier fit + not agency-blocklisted, entirely
# ---- title/employer-based) — no location check gates entry at all anymore.
# ---- CANONICAL_MARKETS below is not a gate — it only supplies the `market`
# ---- label build_fresh_roles() attaches for display/filtering (the Rules &
# ---- Sources per-market toggles, the "Open market · <market>" chip),
# ---- derived by collapsing every LOCATIONS "City, Country" entry (Dubai/Abu
# ---- Dhabi, Kuala Lumpur) down to its country, deduped in LOCATIONS order.
def _canonical_market_name(location_entry):
    return location_entry.split(",")[-1].strip() if "," in location_entry else location_entry


CANONICAL_MARKETS = []
for _loc_entry in LOCATIONS:
    _canonical = _canonical_market_name(_loc_entry)
    if _canonical not in CANONICAL_MARKETS:
        CANONICAL_MARKETS.append(_canonical)

# A market whose real-world postings commonly abbreviate the country name
# differently than CANONICAL_MARKETS spells it out, checked as an extra
# substring alongside the market's own name in market_for_location() below —
# "UAE" is a very common informal abbreviation LinkedIn/Indeed location
# fields use ("Dubai, UAE") that wouldn't otherwise contain the literal
# phrase "united arab emirates". Every market not listed here just matches
# on its own lowercase name.
MARKET_ALIASES = {
    "United Arab Emirates": ["uae"],
}


def market_for_location(location):
    """Best-effort canonical market label for a raw scraped location string —
    used only for display/filtering (the Rules & Sources per-market toggles,
    the "Open market · <market>" chip), never to decide whether a posting
    qualifies for the open-market feed (that's open_market_gate() alone,
    title/employer-based — see the 2026-09-23 broadening note above). Same
    substring-match approach the original 3-market version had, generalized
    to all 24 CANONICAL_MARKETS: not exact equality, since a real result's
    location is almost always more specific than the bare country name used
    to search for it (e.g. "Amsterdam, North Holland, Netherlands", not
    literally "Netherlands"). MARKET_ALIASES checked as extra substrings.
    Also recognizes a bare two-letter country code ("SG"/"NL"/"AE") some
    sources return instead of a full location string, checked by exact (not
    substring) match since codes are too short to substring-match safely.
    Unlike the old gate version, this never returns None: a location that
    doesn't match anything in CANONICAL_MARKETS still gets labeled — with
    the raw (trimmed) location string itself — rather than the role being
    dropped or mislabeled, since this is purely a display label now."""
    loc = (location or "").strip()
    if not loc:
        return "Unspecified"
    loc_lower = loc.lower()
    country_codes = {"sg": "Singapore", "nl": "Netherlands", "ae": "United Arab Emirates"}
    if loc_lower in country_codes:
        return country_codes[loc_lower]
    for market in CANONICAL_MARKETS:
        needles = [market.lower()] + MARKET_ALIASES.get(market, [])
        if any(needle in loc_lower for needle in needles):
            return market
    return loc


# Every LOCATIONS entry mapped to the exact country_indeed string JobSpy's
# Indeed adapter expects (verified against JobSpy's own supported-countries
# list — these are case-/spelling-sensitive on JobSpy's side, not something
# to guess at). All 25 are supported. The three "City, Country" entries also
# get a trimmed, city-only LOCATION_FOR_INDEED override below, since Indeed
# treats `location` as an in-country search modifier on top of
# `country_indeed`, not a repeat of the country name.
INDEED_COUNTRY = {
    "Singapore": "Singapore",
    "Hong Kong": "Hong Kong",
    "Taiwan": "Taiwan",
    "Japan": "Japan",
    "South Korea": "South Korea",
    "New Zealand": "New Zealand",
    "Australia": "Australia",
    "Netherlands": "Netherlands",
    "Italy": "Italy",
    "France": "France",
    "Luxembourg": "Luxembourg",
    "Switzerland": "Switzerland",
    "Austria": "Austria",
    "Denmark": "Denmark",
    "Sweden": "Sweden",
    "Norway": "Norway",
    "Germany": "Germany",
    "Belgium": "Belgium",
    "Spain": "Spain",
    "Portugal": "Portugal",
    "United Kingdom": "UK",
    "Ireland": "Ireland",
    "Kuala Lumpur, Malaysia": "Malaysia",
    "Dubai, United Arab Emirates": "United Arab Emirates",
    "Abu Dhabi, United Arab Emirates": "United Arab Emirates",
}
INDEED_LOCATION_OVERRIDE = {
    "Kuala Lumpur, Malaysia": "Kuala Lumpur",
    "Dubai, United Arab Emirates": "Dubai",
    "Abu Dhabi, United Arab Emirates": "Abu Dhabi",
}

# The subset of LOCATIONS Glassdoor actually supports — `country_indeed` is
# the same parameter JobSpy uses for both Indeed and Glassdoor, but
# Glassdoor's own country list is a real subset of Indeed's, not a superset
# or an unrelated list. Verified 2026-09 directly against JobSpy's source
# (jobspy/model.py's Country enum — Glassdoor support is a 3rd tuple element
# present only for these countries, not just the README's own summary table,
# which is the authoritative behavior check.php-equivalent code actually
# runs on). Taiwan, Japan, South Korea, Luxembourg, Denmark, Sweden, Norway,
# Portugal, and United Arab Emirates are Indeed-only — deliberately absent
# here rather than guessed at, so those combos just skip the Glassdoor call
# cleanly (same pattern as INDEED_COUNTRY's own "shouldn't happen but skip
# cleanly" guard in run_searches()).
#
# One flagged discrepancy: Malaysia. JobSpy's own README table doesn't mark
# Malaysia with the Glassdoor asterisk, but the actual source code's Country
# enum gives Malaysia a 3-element tuple (the code's real condition for
# Glassdoor support) — added in a later commit that the README's hand-written
# table apparently never caught up with. Included here on the code's
# authority, since that's what actually executes, but worth specifically
# watching in the first few live runs: if Malaysia's Glassdoor combos come
# back consistently empty where Singapore/Hong Kong/etc. don't, that's the
# README's version turning out to be the more accurate one in practice.
GLASSDOOR_COUNTRY = {
    "Singapore": "Singapore",
    "Hong Kong": "Hong Kong",
    "New Zealand": "New Zealand",
    "Australia": "Australia",
    "Netherlands": "Netherlands",
    "Italy": "Italy",
    "France": "France",
    "Switzerland": "Switzerland",
    "Austria": "Austria",
    "Germany": "Germany",
    "Belgium": "Belgium",
    "Spain": "Spain",
    "United Kingdom": "UK",
    "Ireland": "Ireland",
    "Kuala Lumpur, Malaysia": "Malaysia",  # see the Malaysia caveat above
}

# Google ignores `location`/`hours_old`/etc. entirely once `google_search_term`
# is set (JobSpy builds the literal `q=` string from it verbatim, no parsing
# on JobSpy's side) — so the "near <location>" and time-window phrasing has
# to be embedded by hand, following the exact convention JobSpy's own README
# example uses ("software engineer jobs near San Francisco, CA since
# yesterday"). HOURS_OLD (240h / 10 days) doesn't map cleanly onto Google's
# four literal time-phrase buckets (get_time_range() in JobSpy's own source:
# "since yesterday" <=24h, "in the last 3 days" <=72h, "in the last week"
# <=168h, else "in the last month") — "in the last month" is the safe
# superset choice (never narrower than the 10-day window the other sites
# use), not an attempt at an exact match. A Google result older than 10 days
# just rides the same EXPIRY_DAYS/lastSeenAt lifecycle as everything else
# once it's matched and kept — see build_fresh_roles/merge_and_prune.
GOOGLE_TIME_PHRASE = "in the last month"


def google_query(term, location):
    return f"{term} jobs near {location} {GOOGLE_TIME_PHRASE}"

RESULTS_WANTED_PER_SEARCH = 20
# ---- Phase 2.6 originally asked for more results per search (50 instead of
# ---- 20) on any OPEN_MARKET_LOCATIONS-eligible combo, since that widened
# ---- net directly widened open-market coverage for a small 3-market
# ---- allowlist. 2026-09-23: now that open-market eligibility covers every
# ---- LOCATIONS entry (not a 3-market subset — see market_for_location()'s
# ---- note above), applying that same +50 boost everywhere would mean
# ---- meaningfully more requests across all 950 combos, not just a handful
# ---- — a real footprint/rate-limit tradeoff, and your explicit call was to
# ---- keep the flat 20-per-search default instead and take the filtering
# ---- fix without also scraping harder. RESULTS_WANTED_OPEN_MARKET/
# ---- _results_wanted_for() are retired; every combo now just uses
# ---- RESULTS_WANTED_PER_SEARCH directly, open-market-eligible or not.
# ---- "sorted by recency" from the spec is NOT implemented as a JobSpy call
# ---- parameter — scrape_jobs() has no sort/date-ordering parameter at all
# ---- (checked directly against JobSpy's own README before writing this;
# ---- inventing one that doesn't exist would just crash the next live run).
# ---- Recency ordering is applied instead where it actually matters for a
# ---- consumer — merge_and_prune() sorts openMarket.roles[] by postedDate
# ---- (falling back to lastSeenAt) before it's written to the snapshot.
HOURS_OLD = 240  # 10 days — comfortably wider than one rotation cycle (see below),
                 # so a role posted right after its combo's turn is still visible
                 # the next time that combo comes up.

# Polite, but randomized rather than a flat delay — September 2026, paired
# with the move to hourly runs (below): a perfectly uniform 8.0s gap between
# every single request, run after run, is a very identifiable non-human
# pattern; a random point in a tight range costs nothing in total run time
# (same ~6-8 minutes either way) but doesn't look mechanically scripted.
# Shared by LI and Google — see the module docstring for why Google gets the
# same caution as LI despite not being explicitly flagged as rate-limited by
# JobSpy's docs (it scrapes google.com directly, a generally block-happy
# surface, and there's no cost to being cautious here versus real evidence).
PAUSE_BETWEEN_SEARCHES_SECONDS_MIN = 5
PAUSE_BETWEEN_SEARCHES_SECONDS_MAX = 11

# Bayt has no location parameter at all (see module docstring), so it isn't
# part of the term x location grid or the chunked rotation — it's cheap
# enough (38 requests, one per SEARCH_TERMS entry, no location multiplier)
# to just run in full every single scheduled run rather than needing its own
# rotation logic. Same randomized-pause treatment as Google/LI: JobSpy's docs
# don't call Bayt out as rate-limited either way, so this is the same
# "no evidence yet, so don't assume it's as tolerant as Indeed" hedge.
BAYT_PAUSE_BETWEEN_SEARCHES_SECONDS_MIN = 5
BAYT_PAUSE_BETWEEN_SEARCHES_SECONDS_MAX = 11

# ---- Rotation: see the module docstring. One run = one chunk of the full
# ---- term x location grid, chosen deterministically from wall-clock time so
# ---- scheduled runs naturally advance through the whole grid and wrap
# ---- around. Tune COMBOS_PER_RUN to trade off per-run LI load against
# ---- how long a full cycle takes (both printed at the top of every run).
COMBOS_PER_RUN = 60
SCHEDULE_INTERVAL_HOURS = 1  # must match the cron in .github/workflows/scrape-li.yml

# A role not re-confirmed within this many days is dropped from the
# snapshot — see the module docstring's "accumulate, don't overwrite" note.
# Kept safely above 2x a full rotation cycle so normal rotation timing never
# prunes a role that just hasn't had its combo's turn yet.
EXPIRY_DAYS = 14


def all_combos():
    return [(term, loc) for term in SEARCH_TERMS for loc in LOCATIONS]


def current_chunk_index(total_chunks, forced=None):
    if forced is not None:
        return forced % total_chunks
    # Deterministic, stateless: which SCHEDULE_INTERVAL_HOURS-wide bucket of
    # wall-clock time are we in right now, since the Unix epoch. Consecutive
    # scheduled runs land in consecutive buckets (cron "0 * * * *" fires
    # exactly on 1-hour epoch boundaries), so this advances by 1 each
    # scheduled run without needing to persist any state between runs. A
    # manually-triggered or delayed run may occasionally repeat or skip a
    # chunk — harmless, it evens out over the next cycle.
    bucket = int(time.time() // (SCHEDULE_INTERVAL_HOURS * 3600))
    return bucket % total_chunks


def run_searches(combos, debug=False):
    """Yields (source, row) for this run's chunk of (term, location)
    combinations — source is "li", "indeed", "glassdoor", or "google"; row
    is a raw JobSpy result (dict-like). Imports jobspy lazily so
    match.py/test_match.py can be exercised without the dependency
    installed.

    Each of the four sites is run as its own independent scrape_jobs() call
    per combo, each in its own try/except, rather than one combined
    site_name=[...] call — deliberately, so any one site's failure (an
    unsupported country value, a transient error, a block) can never take
    another site's result for that same combo down with it. Only LI and
    Google get the randomized pacing pause — see PAUSE_BETWEEN_SEARCHES_*'s
    comment above for why Google gets the same treatment as LI despite not
    being explicitly flagged as rate-limited anywhere in JobSpy's docs.

    Description availability (2026-09-23, checked directly against JobSpy's
    own README before writing this): Indeed, Glassdoor, and Google all return
    a `description` field on every row with no extra parameter needed. LI is
    the one exception — JobSpy only populates it when linkedin_fetch_description=True
    is passed, which adds one extra request PER RESULT ("increases requests
    by O(n)" per JobSpy's own docs) — a real cost given LI is this scraper's
    single biggest source. Deliberately left off (see the
    linkedin_fetch_description=False call below) — a LI-only role's
    `sponsorshipSignal` (see sponsorship_signal() above) will always be [],
    not because nothing was found but because nothing was ever fetched to
    look at. Revisit if this proves to be a real gap once more data has
    accumulated (a LI-corroborated role that also turns up on Indeed/
    Glassdoor/Google still gets a description via that second source — see
    _merge_role_records()'s sponsorshipSignal union)."""
    from jobspy import scrape_jobs

    for term, location in combos:
        if debug:
            print(f"[scrape] searching (li): {term!r} @ {location!r}", file=sys.stderr)
        try:
            df = scrape_jobs(
                site_name=["linkedin"],
                search_term=term,
                location=location,
                results_wanted=RESULTS_WANTED_PER_SEARCH,  # 2.6, flat since 2026-09-23
                hours_old=HOURS_OLD,
                linkedin_fetch_description=False,
                verbose=1 if debug else 0,
            )
        except Exception as e:  # noqa: BLE001 — one bad search must not kill the whole run
            print(f"[scrape] li search failed ({term!r} @ {location!r}): {e}", file=sys.stderr)
            df = None
        if df is not None and len(df):
            for row in df.to_dict(orient="records"):
                yield ("li", row)
        time.sleep(random.uniform(PAUSE_BETWEEN_SEARCHES_SECONDS_MIN, PAUSE_BETWEEN_SEARCHES_SECONDS_MAX))

        indeed_country = INDEED_COUNTRY.get(location)
        if not indeed_country:
            indeed_location = None  # shouldn't happen — every LOCATIONS entry has a mapping — but skip cleanly if it ever doesn't
        else:
            indeed_location = INDEED_LOCATION_OVERRIDE.get(location, location)
            if debug:
                print(f"[scrape] searching (indeed): {term!r} @ {indeed_location!r} ({indeed_country})", file=sys.stderr)
            try:
                df2 = scrape_jobs(
                    site_name=["indeed"],
                    search_term=term,
                    location=indeed_location,
                    country_indeed=indeed_country,
                    results_wanted=RESULTS_WANTED_PER_SEARCH,  # 2.6, flat since 2026-09-23
                    hours_old=HOURS_OLD,
                    verbose=1 if debug else 0,
                )
            except Exception as e:  # noqa: BLE001 — same isolation as the LI call above
                print(f"[scrape] indeed search failed ({term!r} @ {indeed_location!r}): {e}", file=sys.stderr)
                df2 = None
            if df2 is not None and len(df2):
                for row in df2.to_dict(orient="records"):
                    yield ("indeed", row)

        glassdoor_country = GLASSDOOR_COUNTRY.get(location)
        if glassdoor_country:
            glassdoor_location = INDEED_LOCATION_OVERRIDE.get(location, location)
            if debug:
                print(f"[scrape] searching (glassdoor): {term!r} @ {glassdoor_location!r} ({glassdoor_country})", file=sys.stderr)
            try:
                df3 = scrape_jobs(
                    site_name=["glassdoor"],
                    search_term=term,
                    location=glassdoor_location,
                    country_indeed=glassdoor_country,
                    results_wanted=RESULTS_WANTED_PER_SEARCH,  # 2.6, flat since 2026-09-23
                    hours_old=HOURS_OLD,
                    verbose=1 if debug else 0,
                )
            except Exception as e:  # noqa: BLE001 — same isolation as LI/Indeed above
                print(f"[scrape] glassdoor search failed ({term!r} @ {glassdoor_location!r}): {e}", file=sys.stderr)
                df3 = None
            if df3 is not None and len(df3):
                for row in df3.to_dict(orient="records"):
                    yield ("glassdoor", row)
            # No pause here — Glassdoor isn't flagged as rate-limited by JobSpy's
            # docs, same reasoning as Indeed getting none. Revisit if the first
            # several live runs suggest otherwise.
        # else: this location isn't in GLASSDOOR_COUNTRY — skip cleanly, no request made.

        query = google_query(term, location)
        if debug:
            print(f"[scrape] searching (google): {query!r}", file=sys.stderr)
        try:
            df4 = scrape_jobs(
                site_name=["google"],
                google_search_term=query,
                results_wanted=RESULTS_WANTED_PER_SEARCH,  # 2.6, flat since 2026-09-23
                verbose=1 if debug else 0,
            )
        except Exception as e:  # noqa: BLE001 — same isolation as every other site above
            print(f"[scrape] google search failed ({query!r}): {e}", file=sys.stderr)
            df4 = None
        if df4 is not None and len(df4):
            for row in df4.to_dict(orient="records"):
                yield ("google", row)
        time.sleep(random.uniform(PAUSE_BETWEEN_SEARCHES_SECONDS_MIN, PAUSE_BETWEEN_SEARCHES_SECONDS_MAX))


def run_bayt_searches(debug=False):
    """Yields (source, row) for every one of SEARCH_TERMS against Bayt —
    all 38, every run, not chunked (see BAYT_PAUSE_BETWEEN_SEARCHES_*'s
    comment above for why this doesn't need the term x location rotation
    the other four sites use: Bayt takes no location parameter at all, so
    there's no location axis to rotate through, and 38 requests/run is
    cheap enough to just always run in full). Same try/except-per-search
    isolation as run_searches()."""
    from jobspy import scrape_jobs

    for term in SEARCH_TERMS:
        if debug:
            print(f"[scrape] searching (bayt): {term!r}", file=sys.stderr)
        try:
            df = scrape_jobs(
                site_name=["bayt"],
                search_term=term,
                results_wanted=RESULTS_WANTED_PER_SEARCH,
                verbose=1 if debug else 0,
            )
        except Exception as e:  # noqa: BLE001 — one bad search must not kill the whole run
            print(f"[scrape] bayt search failed ({term!r}): {e}", file=sys.stderr)
            df = None
        if df is not None and len(df):
            for row in df.to_dict(orient="records"):
                yield ("bayt", row)
        time.sleep(random.uniform(BAYT_PAUSE_BETWEEN_SEARCHES_SECONDS_MIN, BAYT_PAUSE_BETWEEN_SEARCHES_SECONDS_MAX))


def normalize_posted_date(value):
    """JobSpy's date_posted comes back as a pandas Timestamp/date/NaT/None
    depending on what LI gave it — collapse all of that to either an
    ISO 'YYYY-MM-DD' string or None."""
    if value is None:
        return None
    s = str(value)
    if not s or s.lower() in ("nat", "none", "nan"):
        return None
    return s[:10]  # Timestamp's str() is 'YYYY-MM-DD ...' or already just the date


def _clean_str(value):
    """Coerce a raw JobSpy result field to a string. JobSpy returns a pandas
    DataFrame under the hood, and pandas represents a missing value as NaN —
    a float, not None or "". `value or ""` doesn't catch that, because
    float('nan') is truthy in Python (only None/0/""/empty containers are
    falsy) — so an ungated `row.get(...) or ""` lets a raw NaN float sail
    through and blow up the moment any downstream code (match.py's regex
    substitutions, is_role_relevant's string checks) tries to treat it as a
    string. `value != value` is True only for NaN among common types, so
    this catches it without needing a pandas import here."""
    if value is None or (isinstance(value, float) and value != value):
        return ""
    return str(value)


def build_fresh_roles(rows, index, today_iso, debug=False):
    """Filters this run's raw results down to real matches, keyed by
    role_identity() (1.4: normalized employer+title+location — NOT job_url;
    the same real posting frequently turns up at a different URL per site,
    or even a fresh URL on the same site on a later run, and that's exactly
    the cross-site duplication Phase 0 set out to measure). rows: iterable
    of (source, row) — source is "li", "indeed", "glassdoor", "google", or
    "bayt", tagged onto the kept role (plus retained in its "sources" array
    when more than one site reports the same identity) so the frontend badge
    shows which site(s) actually found it.

    Returns (fresh, fresh_open_market) — two separate identity-keyed dicts,
    same (identity -> (key, role)) shape. `fresh` is unchanged from before
    Phase 2: tracked-company matches only, `key` is the company slug.
    `fresh_open_market` is new (2.2; broadened 2026-09-23): a posting that
    matched NO tracked company but clears open_market_gate() (relevant +
    real target-tier fit + not agency-blocklisted) — no location check gates
    entry at all anymore, since this file already searches every LOCATIONS
    entry for every pre-defined title regardless. `market_for_location()`
    still labels which market a kept role is in, purely for display/
    filtering (never to decide inclusion). Keyed the same way as `fresh` but
    with `key` being normalize_employer_name(employer) instead of a slug
    (there's no slug — that's the whole point of "open market"). Every other
    unmatched posting — failing open_market_gate() on title/employer — is
    still just dropped, exactly as before.

    A URL is still required and still deduped on its own first (`duplicate`
    below) — that's a much cheaper, unambiguous check (the literal same URL
    really is the literal same JobSpy row) and catches the common case
    before the heavier identity-based merge ever runs."""
    fresh = {}  # identity tuple -> (slug, role dict)
    fresh_open_market = {}  # identity tuple -> (normalized employer key, role dict) — 2.2
    seen_urls = set()
    kept = dropped_company = dropped_title = duplicate = merged_cross_site = 0
    kept_open_market = dropped_open_market_strict = merged_cross_site_open_market = 0

    for source, row in rows:
        url = _clean_str(row.get("job_url"))
        if not url or url in seen_urls:
            duplicate += 1
            continue
        seen_urls.add(url)

        employer = _clean_str(row.get("company"))
        # 1.5: strip CTA-button run-on text and, only when the site gave no
        # location, recover one that's run into the title text itself.
        # _clean_str() first, same as employer above — normalize_scraped_title()
        # ultimately just does str(value), which doesn't catch a raw pandas
        # NaN float the way _clean_str()'s explicit `value != value` check
        # does (see _clean_str()'s own docstring for the production crash
        # this guards against).
        title, location = normalize_scraped_title(_clean_str(row.get("title")), _clean_str(row.get("location")))
        slug = match_company(employer, index)

        if not slug:
            dropped_company += 1
            if debug:
                print(f"[match] no company match: {employer!r} — {row.get('title')!r}", file=sys.stderr)
            # 2.2 (broadened 2026-09-23): not a tracked company — still worth
            # a second look for the open-market feed, gated purely on title/
            # employer now (open_market_gate()) — no location restriction.
            # An empty employer (e.g. a NaN "company" field — see _clean_str()'s
            # docstring) can never qualify: an "open market" posting with no
            # employer name to show is useless in the UI, not just noise.
            # Previously this was accidentally caught by the location
            # allowlist (an empty-employer row's location was essentially
            # never one of the 3 old markets) rather than by an explicit
            # check — now that there's no location allowlist to lean on,
            # this guards it directly instead of relying on that coincidence.
            market = market_for_location(location)
            if employer and open_market_gate(title, employer, is_agency):
                kept_open_market_this_row = True
            else:
                kept_open_market_this_row = False
                dropped_open_market_strict += 1
                if debug:
                    print(f"[open-market] failed gate: {title!r} @ {employer!r} ({market})", file=sys.stderr)
            if not kept_open_market_this_row:
                continue

            employer_key = normalize_employer_name(employer)
            identity = role_identity(employer_key, title, location)
            candidate_role = {
                "employer": employer,
                "market": market,
                "title": title,
                "location": location,
                "url": url,
                "postedDate": normalize_posted_date(row.get("date_posted")),
                "source": source,
                "sources": [source],
                "sponsorshipSignal": sponsorship_signal(_clean_str(row.get("description"))),
                "lastSeenAt": today_iso,
            }
            if identity in fresh_open_market:
                merged_cross_site_open_market += 1
                _, prior_role = fresh_open_market[identity]
                fresh_open_market[identity] = (employer_key, _merge_role_records(prior_role, candidate_role))
            else:
                kept_open_market += 1
                fresh_open_market[identity] = (employer_key, candidate_role)
            continue

        if not is_role_relevant(title):
            dropped_title += 1
            if debug:
                print(f"[match] title filtered out: {title!r} @ {employer!r}", file=sys.stderr)
            continue

        identity = role_identity(slug, title, location)
        candidate_role = {
            "title": title,
            "location": location,
            "url": url,
            "postedDate": normalize_posted_date(row.get("date_posted")),
            "source": source,
            "sources": [source],
            "sponsorshipSignal": sponsorship_signal(_clean_str(row.get("description"))),
            "lastSeenAt": today_iso,
        }

        if identity in fresh:
            merged_cross_site += 1
            _, prior_role = fresh[identity]
            fresh[identity] = (slug, _merge_role_records(prior_role, candidate_role))
            continue

        kept += 1
        fresh[identity] = (slug, candidate_role)

    if debug:
        print(
            f"[match] kept={kept} dropped_no_company_match={dropped_company} "
            f"dropped_title_filter={dropped_title} duplicate_urls={duplicate} "
            f"merged_cross_site_identities={merged_cross_site}",
            file=sys.stderr,
        )
        print(
            f"[open-market] kept={kept_open_market} dropped_strict_gate={dropped_open_market_strict} "
            f"merged_cross_site_identities={merged_cross_site_open_market} "
            f"(of the {dropped_company} with no company match)",
            file=sys.stderr,
        )
    return fresh, fresh_open_market


def load_existing_snapshot():
    if not os.path.exists(OUTPUT_PATH):
        return {"companies": {}}
    try:
        with open(OUTPUT_PATH) as f:
            data = json.load(f)
        if not isinstance(data, dict) or not isinstance(data.get("companies"), dict):
            return {"companies": {}}
        return data
    except (OSError, json.JSONDecodeError) as e:
        print(f"[merge] couldn't read existing {OUTPUT_PATH} ({e}) — starting fresh", file=sys.stderr)
        return {"companies": {}}


def _merge_identity_roles(existing_items, fresh_roles, cutoff):
    """Shared merge mechanics behind both branches of merge_and_prune()
    (tracked-company and, as of Phase 2.5, open-market — "extended not
    forked" per the backlog: one function doing both jobs, not a
    copy-pasted merge_and_prune_open_market(). The two branches differ
    enough in OUTPUT shape (tracked groups by slug into
    {slug: {"roles": [...]}}, open-market is a flat, recency-sorted list —
    see merge_and_prune() below) that fully sharing the grouping step too
    wasn't worth the extra indirection; this covers everything upstream of
    that: flattening, merging, and expiry.

    existing_items: iterable of (key, role) pairs already extracted from
    wherever they're grouped in the existing snapshot (key is a company
    slug for tracked roles, normalize_employer_name(employer) for
    open-market ones — either way, whatever role_identity() expects as its
    first argument). fresh_roles: {identity: (key, role)} found THIS run.

    Returns (kept_items, stats) — kept_items is a list of (key, role) pairs
    (this run's fresh roles, upserted/merged via _merge_role_records(), plus
    everything carried over that hasn't hit EXPIRY_DAYS since its own
    lastSeenAt); stats is {"added","updated","carried_over","expired"}.

    Roles written before 1.4 shipped only have a singular "source"/"url", no
    "sources" array yet — backfilled from "source" here on the fly so every
    role is on the new shape again the first time it's touched, no separate
    migration needed for this field specifically (li-scraper/migrate_titles.py
    handles the still-outstanding title/location text migration). Roles
    written before the 2026-09-23 sponsorship-keyword addition are backfilled
    the same way, to an empty list — not because a description was checked
    and found nothing, just because no description was ever fetched/scanned
    for that role yet."""
    merged = {}
    for key, role in existing_items:
        identity = role_identity(key, role.get("title", ""), role.get("location", ""))
        if "sources" not in role or "sponsorshipSignal" not in role:
            role = dict(role)
            if "sources" not in role:
                role["sources"] = [role["source"]] if role.get("source") else []
            if "sponsorshipSignal" not in role:
                role["sponsorshipSignal"] = []
        merged[identity] = (key, role)

    stats = {"added": 0, "updated": 0, "carried_over": 0, "expired": 0}
    for identity, (key, role) in fresh_roles.items():
        if identity in merged:
            stats["updated"] += 1
            _, prior_role = merged[identity]
            role = _merge_role_records(prior_role, role)
        else:
            stats["added"] += 1
        merged[identity] = (key, role)

    kept_items = []
    for identity, (key, role) in merged.items():
        if identity in fresh_roles:
            kept_items.append((key, role))
            continue
        last_seen = role.get("lastSeenAt") or "1970-01-01"
        if last_seen < cutoff:
            stats["expired"] += 1
            continue
        kept_items.append((key, role))

    return kept_items, stats


def merge_and_prune(existing, fresh_roles, today_iso, fresh_open_market_roles=None, debug=False):
    """existing: the snapshot loaded from disk (accumulated from prior runs).
    fresh_roles: {identity: (slug, role)} found THIS run (1.4: identity is
    role_identity()'s normalized employer+title+location tuple, not a URL —
    see build_fresh_roles()). fresh_open_market_roles: the second dict
    build_fresh_roles() now returns (2.2/2.5) — same shape, but keyed by
    normalized employer text instead of a slug, since there's no tracked
    company to resolve to. Returns the merged, pruned snapshot — "companies"
    unchanged in shape from before Phase 2, plus a new top-level "openMarket"
    key (2.5) — no synthetic slugs, never merged into "companies"."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=EXPIRY_DAYS)).strftime("%Y-%m-%d")
    fresh_open_market_roles = fresh_open_market_roles or {}

    existing_tracked_items = (
        (slug, role)
        for slug, entry in existing.get("companies", {}).items()
        for role in entry.get("roles", [])
    )
    kept_items, stats = _merge_identity_roles(existing_tracked_items, fresh_roles, cutoff)
    companies_out = {}
    for slug, role in kept_items:
        companies_out.setdefault(slug, {"roles": []})["roles"].append(role)

    # 2.5: same identity/expiry mechanics, applied to the open-market side.
    # normalize_employer_name(role["employer"]) recomputes the same key a
    # role was first filed under (see build_fresh_roles()) — nothing extra
    # needs to be persisted on the role dict just to re-derive it next run.
    existing_open_market_items = (
        (normalize_employer_name(role.get("employer", "")), role)
        for role in existing.get("openMarket", {}).get("roles", [])
    )
    kept_open_market_items, om_stats = _merge_identity_roles(
        existing_open_market_items, fresh_open_market_roles, cutoff
    )
    # 2.6: "sorted by recency" — see RESULTS_WANTED_OPEN_MARKET's comment on
    # why this isn't a JobSpy call parameter instead. Newest postedDate
    # first; a role with no postedDate sorts last (not first) — "" is the
    # lexicographically smallest fallback value, so reverse=True puts it at
    # the end, not the start.
    open_market_roles_out = [role for _, role in kept_open_market_items]
    open_market_roles_out.sort(key=lambda r: (r.get("postedDate") or "", r.get("lastSeenAt") or ""), reverse=True)

    if debug:
        print(
            f"[merge] tracked: added={stats['added']} updated={stats['updated']} "
            f"carried_over={stats['carried_over']} expired_pruned={stats['expired']} (cutoff {cutoff})",
            file=sys.stderr,
        )
        print(
            f"[merge] open-market: added={om_stats['added']} updated={om_stats['updated']} "
            f"carried_over={om_stats['carried_over']} expired_pruned={om_stats['expired']}",
            file=sys.stderr,
        )

    return {
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "companies": companies_out,
        "openMarket": {"roles": open_market_roles_out},
    }


def main():
    debug = "--debug" in sys.argv
    forced_chunk = None
    if "--chunk" in sys.argv:
        forced_chunk = int(sys.argv[sys.argv.index("--chunk") + 1])

    combos = all_combos()
    total_chunks = math.ceil(len(combos) / COMBOS_PER_RUN)
    chunk_index = current_chunk_index(total_chunks, forced=forced_chunk)
    this_chunk = combos[chunk_index * COMBOS_PER_RUN: (chunk_index + 1) * COMBOS_PER_RUN]

    cycle_hours = total_chunks * SCHEDULE_INTERVAL_HOURS
    glassdoor_calls_this_chunk = sum(1 for _, loc in this_chunk if loc in GLASSDOOR_COUNTRY)
    # Up to 4 requests/combo (li + indeed + google always attempted, glassdoor only
    # where GLASSDOOR_COUNTRY covers the location) + a flat 38 for Bayt, unchunked.
    max_requests_this_run = len(this_chunk) * 3 + glassdoor_calls_this_chunk + len(SEARCH_TERMS)
    print(
        f"[scrape] {len(combos)} total combos ({len(SEARCH_TERMS)} terms x {len(LOCATIONS)} locations), "
        f"{COMBOS_PER_RUN}/run -> {total_chunks} chunks -> full cycle ~{cycle_hours}h (~{cycle_hours / 24:.1f} days) "
        f"[cycle length unchanged since the Sep 2026 Glassdoor/Google/Bayt addition — see module docstring]"
    )
    print(f"[scrape] this run: chunk {chunk_index + 1}/{total_chunks} "
          f"({len(this_chunk)} combos x li+indeed+google + {glassdoor_calls_this_chunk} glassdoor-eligible "
          f"+ {len(SEARCH_TERMS)} bayt = up to {max_requests_this_run} requests)")

    index = build_index(COMPANIES, ALIASES)
    rows = list(run_searches(this_chunk, debug=debug)) + list(run_bayt_searches(debug=debug))
    counts = {}
    for source, _ in rows:
        counts[source] = counts.get(source, 0) + 1
    counts_str = ", ".join(f"{counts.get(s, 0)} {s}" for s in ("li", "indeed", "glassdoor", "google", "bayt"))
    print(f"[scrape] {len(rows)} raw results this run ({counts_str})")

    today_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    fresh_roles, fresh_open_market_roles = build_fresh_roles(rows, index, today_iso, debug=debug)
    existing = load_existing_snapshot()
    snapshot = merge_and_prune(existing, fresh_roles, today_iso, fresh_open_market_roles=fresh_open_market_roles, debug=debug)

    open_market_count = len(snapshot["openMarket"]["roles"])
    if debug:
        print(f"\n[debug] {len(snapshot['companies'])} companies, "
              f"{sum(len(c['roles']) for c in snapshot['companies'].values())} roles total, "
              f"{open_market_count} open-market roles (all searched markets) — "
              f"not written to {OUTPUT_PATH} (--debug mode)", file=sys.stderr)
        return

    with open(OUTPUT_PATH, "w") as f:
        json.dump(snapshot, f, indent=2)
        f.write("\n")
    total_roles = sum(len(c["roles"]) for c in snapshot["companies"].values())
    print(
        f"[scrape] wrote {OUTPUT_PATH}: {len(snapshot['companies'])} companies, {total_roles} roles, "
        f"{open_market_count} open-market roles"
    )


if __name__ == "__main__":
    main()
