"""
FinPath — LI + Indeed coverage via JobSpy (github.com/speedyapply/JobSpy),
plus Bayt via a dedicated Playwright scraper (see *** BAYT: NOW VIA
PLAYWRIGHT *** below, and bayt_playwright.py's own module docstring for the
full story). Glassdoor and Google were both evaluated and retired outright,
neither replaced — see *** GLASSDOOR: RETIRED *** and *** GOOGLE: RETIRED
*** below.

Runs keyword searches against three of JobSpy's eight supported sites (your
trimmed Product + Design/UX title list, across your target-region list — see
SEARCH_TERMS/LOCATIONS below). Writes li-snapshot.json with two top-level
sections:
  - `companies: { <slug>: { roles: [...] } }` — results (a) from one of the
    231 tracked companies — matched by name, see match.py — that (b) pass
    the exact same isRoleRelevant() title filter index.html itself applies.
    This is the original shape check.php has always expected from
    js-scraper's snapshot.json, byte-for-byte unchanged by Phase 2.
  - `openMarket: { roles: [...] }` (Phase 2, new; broadened to all LOCATIONS
    2026-09-23, LOCATIONS trimmed 25 -> 15 the same day per your explicit
    market picks) — a flat, no-slug list of postings that matched NO
    tracked company but are still worth surfacing: it clears
    open_market_gate() (relevant, real target-tier fit, not on the
    agencies.py blocklist) — see build_fresh_roles()/open_market_gate(). No
    location restriction of its own beyond that — every location this file
    already searches (all of LOCATIONS, not a narrower subset) is eligible;
    a `market` field (see market_for_location()) labels which one, purely
    for display/filtering, never for exclusion. Sorted newest-first. Each role
    in EITHER section carries its own `source` ("li", "indeed", or "bayt")
    plus a `sources` array (Phase 1.4) for cross-site corroboration, so the
    frontend can badge it correctly. LI and Indeed are both queried
    unconditionally for every combo, open-market locations included — see
    run_searches() below — so every open-market market has the same
    two-source floor as every tracked-company market does. As of
    2026-09-23, both sections also carry `sponsorshipSignal` (a list of
    matched sponsorship/relocation phrases from the posting's own
    description — see SPONSORSHIP_KEYWORDS/sponsorship_signal() below);
    always `[]` for a LinkedIn-only role, since linkedin_fetch_description
    stays off (see run_searches()'s docstring) — Indeed and Bayt return a
    description with no extra request, so those sites are covered for free.
ZipRecruiter (US/Canada only — a poor fit for a mostly non-US target-region
list), Naukri (India) and BDJobs (Bangladesh) were deliberately left out —
see README.md's "Widening scope further" for the reasoning behind every
site, included or not.

*** IMPORTANT — READ THIS BEFORE CHANGING TERMS/LOCATIONS/SCHEDULE ***
38 title phrases x 15 locations = 570 (term, location) combinations as of
2026-09-24 (trimmed from 25 locations/950 combos the same day, at the
user's explicit request, after being walked through the full list of 25
and choosing which 15 to keep — see LOCATIONS below for the current list).
Originally 108 x 17 = 1,836 before a September 2026 term-list trim brought
it to 38 x 25 = 950; this round's location trim is a second, independent
reduction on top of that one. Each combination is searched against LI and
Indeed via JobSpy — two independent requests per combo, each in its own
try/except so one site's failure never takes the other's result down for
that same combo. Only LI gets the randomized pacing pause between the two
JobSpy calls: Indeed has no rate limiting per JobSpy's own docs (see
README's "Indeed coverage" section). Glassdoor and Google used to be part
of this grid too — both retired outright 2026-09-24, see the module
docstring's "GLASSDOOR: RETIRED" and "GOOGLE: RETIRED" sections; neither is
searched at all anymore, by any method. Bayt is architecturally different
from LI/Indeed — no location parameter at all (it "searches
internationally" per JobSpy's own README) — so it isn't part of this
per-combo grid either, searched separately and unchunked; see
run_bayt_playwright_searches() below. There is still no way to run all 570 combinations in a single pass
without either proxies or getting blocked on the LI side almost
immediately — see li-scraper/README.md's "How the rotation works" section
for the full
explanation. Instead, each run covers one CHUNK of the full combination
list (COMBOS_PER_RUN of them), chosen deterministically from the current
time so consecutive scheduled runs walk through the whole list in order and
wrap back around — a full cycle takes ROTATION_CYCLE_HOURS (printed below)
to complete. As of 2026-09-24, COMBOS_PER_RUN=95 divides the 570-combo grid
into exactly 6 equal chunks -> a 6-hour cycle, at ~2,280 LI requests/day —
see COMBOS_PER_RUN's own comment below for how that number was chosen and
the two levers (grid size, combos/run) that went into it. Results
accumulate into li-snapshot.json across runs (merged, not overwritten) and
a role is only dropped after EXPIRY_DAYS without being re-confirmed — so a
company found on Monday doesn't vanish from the tracker on Tuesday just
because today's chunk didn't include that company's search terms.

*** BAYT: NOW VIA PLAYWRIGHT, NOT JOBSPY (2026-09-24) ***
JobSpy's own Bayt adapter (run_bayt_searches() below) got an outright 403
on every single request — confirmed both from GitHub Actions AND from a
real home/office IP via a standalone diagnostic script, so this was never
a GitHub-Actions-specific IP block. A `user_agent` override (a real Chrome
UA, not JobSpy's default) didn't fix it either. JobSpy's own maintainers,
in a GitHub issue about the closely analogous Google/ZipRecruiter/Glassdoor
situation, say sites in this class need "a JS-executing fetch (Playwright
etc.)" — not a header or proxy tweak. You explicitly asked to keep Bayt
working rather than retire it (it's this scraper's only Middle
East-focused source, and covers UAE heavily), so run_bayt_playwright_searches()
below replaces the JobSpy call with a real headless-Chromium scrape via
bayt_playwright.py — see that file's module docstring for the verified DOM
selectors and the full reasoning. run_bayt_searches() (the old JobSpy path)
is left fully intact below, just no longer called from main() — a
ready rollback if the Playwright approach ever needs to be abandoned.

*** GLASSDOOR: RETIRED (2026-09-24, after a same-day Playwright attempt) ***
JobSpy's own Glassdoor adapter (removed — see below) got a 400/403
("location not parsed") on every real request, the same shape of failure
Bayt originally had. A same-day Playwright replacement was built and
shipped, following the same reasoning that fixed Bayt: an initial manual
check with a real, headed browser tab got a normal, fully-rendered results
page on the first try, suggesting — wrongly, as it turned out — that
Glassdoor doesn't bot-block real browsers the way Google does.

That manual check used a headed browser, not the headless Chromium
`sync_playwright()` actually launches in production, and the two behaved
differently. The first live GitHub Actions run of the Playwright version
came back with 0 Glassdoor results out of 63 eligible combos attempted. A
local diagnostic (run against the real, unmodified scraper code, from a
real residential IP — ruling out a GitHub-Actions-specific block) showed
exactly why: Glassdoor's own homepage returned HTTP 401, titled
"Authenticating...", running a script that redirects straight to
`glassdoor.com/member/profile/login?reason=bot-detection&...` —
Cloudflare's bot-management layer explicitly detecting the headless
browser itself (not just "can this client run JS", which is what let Bayt
through) and gating it behind a login wall, citing bot-detection as the
reason in the URL itself.

Getting past a page that explicitly declares itself a bot-detection
response would mean deploying stealth countermeasures — spoofing
`navigator.webdriver`, faking browser fingerprints, that whole toolkit —
specifically to defeat a site's active anti-automation defense. That's a
hard line regardless of the reason or who's asking, the same one that
ruled out Google below. Separately, real research (not a guess) confirmed
there's no legitimate way around it either: Glassdoor's official v1
partner API (api.glassdoor.com) has returned HTTP 410 Gone since
2025-08-20 — dead even for existing partner-key holders — and any new API
access has required an undisclosed, enterprise-only sales process since
2024, not a fit for this project. So Glassdoor is retired outright, same
as Google: glassdoor_playwright.py, test_glassdoor_playwright.py, and
every Glassdoor-specific code path that used to live in this file
(GLASSDOOR_COUNTRY, run_glassdoor_searches(), run_glassdoor_playwright_
searches()) have been deleted entirely rather than kept as a rollback —
there's no working approach to roll back to. If this ever needs
revisiting, the real alternative isn't a scraper at all: paid third-party
job-data aggregators (e.g. JobsPipe, TheirStack) relicense Glassdoor's
data themselves — a vendor decision, not something to build against
unilaterally.

*** GOOGLE: RETIRED, NOT REPLACED (2026-09-24) ***
JobSpy's Google adapter returns 0 rows with an "initial cursor not found"
warning on every request — no loud error the way Bayt's JobSpy adapter
had, just silent nothing. Real diagnosis (a JobSpy maintainer's own
account of this exact situation): Google serves an HTTP-200 "enable
JavaScript" bootstrap shell to any non-JS-executing HTTP client — in
principle the same root cause Bayt had, and initially thought to be
Glassdoor's too (see above — Glassdoor's real problem turned out to be
different and worse: active headless-browser detection, not just a JS
requirement). It was NOT built. Loading Google's own search results page
in a real browser — a single manual request, no automation, no scale at
all — got an immediate "unusual traffic... verify you're not a robot"
interstitial on the very first try, unlike Bayt (which loaded cleanly, and
still does via Playwright today). Building recurring automated
infrastructure specifically to defeat Google's own bot-check, against
Google's own search results specifically (not a job board), at an hourly
schedule, is a materially different and more serious thing than Bayt's
case — Google's Terms of Service explicitly prohibit automated querying of
its search results, and actually solving/bypassing a CAPTCHA-class
challenge is out of scope regardless of the reason (the same reasoning
that ultimately caught up with Glassdoor too, once its headless-specific
Cloudflare block came to light — see above). So Google is retired
outright: run_google_searches() below is extracted verbatim from what
used to be inline in run_searches(), kept intact as a reference, but never
called from main() or from anywhere else. If Google coverage matters
enough to revisit, the real, compliant path is Google's official Custom
Search JSON API — but that returns general web-search snippets/links, not
Google's special Jobs-panel data, so it would need real re-architecture
(crawling each linked page separately) rather than being a drop-in
replacement; not scoped or built.

The Bayt Playwright addition adds a real new per-run cost — a full
Chromium install in CI, plus 38 real browser page loads every run — that
the old JobSpy call didn't have. Worth watching in the first several live
GitHub Actions runs before fully trusting the normal hourly cadence; see
the workflow's own comments.

USAGE (locally or in the GitHub Actions workflow — see .github/workflows/):
    pip install -r requirements.txt
    playwright install --with-deps chromium   # needed once, for the Bayt scraper
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

# Your target-region list. Bare country names ("Japan", "Australia",
# "Netherlands", ...) resolve broadly to anywhere in that country via LI's
# own location search; "City, Country" entries (Kuala Lumpur, Dubai)
# resolve to that specific metro only — that distinction is intentional
# (your call), not something this script enforces itself.
#
# 2026-09-24: trimmed from 25 entries to these 15, at your explicit request
# to reduce scraper load/block-risk, after being shown the full list and
# choosing which markets to keep. Cut: Taiwan, France, Luxembourg,
# Switzerland, Austria, Denmark, Norway, Belgium, Spain, and one of the two
# UAE entries (Abu Dhabi — Dubai stays, and both always collapsed to the
# same "United Arab Emirates" canonical market/label anyway, see
# CANONICAL_MARKETS below, so keeping just one loses no distinct market,
# only the 2x-search-frequency UAE used to get from having two entries).
# INDEED_COUNTRY/INDEED_LOCATION_OVERRIDE below were trimmed to match —
# every kept entry here has (at minimum) an INDEED_COUNTRY mapping.
LOCATIONS = [
    "Singapore",
    "Hong Kong",
    "Japan",
    "South Korea",
    "New Zealand",
    "Australia",
    "Netherlands",
    "Italy",
    "Sweden",
    "Germany",
    "Portugal",
    "United Kingdom",
    "Ireland",
    "Kuala Lumpur, Malaysia",
    "Dubai, United Arab Emirates",
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
# to guess at). All 15 are supported. The two remaining "City, Country"
# entries also get a trimmed, city-only LOCATION_FOR_INDEED override below,
# since Indeed treats `location` as an in-country search modifier on top of
# `country_indeed`, not a repeat of the country name. Trimmed 2026-09-24 to
# match LOCATIONS above (Taiwan/France/Luxembourg/Switzerland/Austria/
# Denmark/Norway/Belgium/Spain/Abu Dhabi entries removed).
INDEED_COUNTRY = {
    "Singapore": "Singapore",
    "Hong Kong": "Hong Kong",
    "Japan": "Japan",
    "South Korea": "South Korea",
    "New Zealand": "New Zealand",
    "Australia": "Australia",
    "Netherlands": "Netherlands",
    "Italy": "Italy",
    "Sweden": "Sweden",
    "Germany": "Germany",
    "Portugal": "Portugal",
    "United Kingdom": "UK",
    "Ireland": "Ireland",
    "Kuala Lumpur, Malaysia": "Malaysia",
    "Dubai, United Arab Emirates": "United Arab Emirates",
}
INDEED_LOCATION_OVERRIDE = {
    "Kuala Lumpur, Malaysia": "Kuala Lumpur",
    "Dubai, United Arab Emirates": "Dubai",
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
# ---- 2026-09-24: two changes landed together — LOCATIONS was trimmed
# ---- 25 -> 15 (see LOCATIONS' own comment above) AND this was set to 95
# ---- (from 60). The grid trim alone (950 -> 570 combos) would have sped
# ---- the old 60/run pace up to a ~9.5h cycle for free, at LOWER daily
# ---- volume than before (24*60=1,440/day, same as the very first
# ---- baseline). Instead, 95 was chosen so the smaller grid divides evenly
# ---- into exactly 6 chunks (570/95=6.0) -> a 6-hour cycle, matching what
# ---- had just been approved (and shipped, then superseded by this round)
# ---- at COMBOS_PER_RUN=160 on the old 950-combo grid — same freshness,
# ---- but at ~2,280 LI requests/day instead of ~3,840/day (a ~40% cut),
# ---- and a real safety-margin win too: the deliberate pacing pauses alone
# ---- (see PAUSE_BETWEEN_SEARCHES_* above) total ~16s/combo, so 95 combos
# ---- is ~25 minutes of guaranteed pause time per run, well clear of the
# ---- 60-minute gap between scheduled runs (versus ~43 minutes at the
# ---- previous 160/950 combination) — a run finishing late enough to
# ---- overlap the next one is now a lot less likely. If real GitHub
# ---- Actions run logs confirm plenty of margin, both COMBOS_PER_RUN and
# ---- LOCATIONS have room to grow again later; this was chosen to bank
# ---- the smaller grid as risk reduction, not to spend it on more speed.
COMBOS_PER_RUN = 95
# 2026-09-25 — was 1 (hourly), matching the cron that used to be
# "0 * * * *". That cron turned out to fire wildly irregularly in practice
# (gaps from 45min to ~6h between runs, at least one run missing outright) —
# see .github/workflows/scrape-li.yml's header comment for the full
# diagnosis (GitHub's scheduler documented to drop `schedule` triggers
# anchored at minute 0 under load) and the fix (cron moved to "13 */3 * * *"
# — every 3h, off the top of the hour). This value must always match that
# cron's *interval* (the hour spacing, e.g. 3 for "every 3 hours" — not the
# minute offset), or the chunk-rotation math below picks the wrong bucket.
# At 3h instead of 1h, the runtime-overlap concern noted in COMBOS_PER_RUN's
# comment above (95 combos ~= 25min of guaranteed pause time versus a
# 60-minute gap) is no longer a live constraint — 25min is well clear of a
# 180-minute gap — so COMBOS_PER_RUN was deliberately left unchanged here
# rather than raised to compensate; the grid now takes ~18h to fully rotate
# instead of ~6h (total_chunks unchanged at 6, cycle_hours = 6 * 3). Raise
# COMBOS_PER_RUN, not this value, if that rotation speed ever needs tuning
# back up.
SCHEDULE_INTERVAL_HOURS = 3  # must match the cron interval in .github/workflows/scrape-li.yml

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
    # scheduled runs land in consecutive buckets — the cron (currently
    # "13 */3 * * *", see .github/workflows/scrape-li.yml) fires a few
    # minutes into each SCHEDULE_INTERVAL_HOURS-wide epoch boundary, which is
    # plenty close for a multi-hour-wide bucket — so this advances by 1 each
    # scheduled run without needing to persist any state between runs. A
    # manually-triggered or delayed run may occasionally repeat or skip a
    # chunk — harmless, it evens out over the next cycle.
    bucket = int(time.time() // (SCHEDULE_INTERVAL_HOURS * 3600))
    return bucket % total_chunks


def run_searches(combos, debug=False):
    """Yields (source, row) for this run's chunk of (term, location)
    combinations — source is "li" or "indeed"; row is a raw JobSpy result
    (dict-like). Imports jobspy lazily so match.py/test_match.py can be
    exercised without the dependency installed.

    *** 2026-09-24: Glassdoor and Google used to be inline here too — see
    "GLASSDOOR: RETIRED" and "GOOGLE: RETIRED" in the module docstring.
    Glassdoor's old JobSpy-based logic (and its Playwright replacement) was
    deleted outright, not kept as a rollback — see the module docstring for
    why. Google's old logic is preserved verbatim in run_google_searches()
    below (retired, no longer called at all — there's no Playwright
    replacement for Google, see the module docstring for why). Only LI and
    Indeed remain here. ***

    Each site is run as its own independent scrape_jobs() call per combo,
    each in its own try/except — deliberately, so any one site's failure
    (an unsupported country value, a transient error, a block) can never
    take another site's result for that same combo down with it. Only LI
    gets the randomized pacing pause now (Google used to share this
    reasoning; see PAUSE_BETWEEN_SEARCHES_*'s comment above, unchanged from
    before Google's retirement).

    Description availability (2026-09-23, checked directly against JobSpy's
    own README before writing this): Indeed returns a `description` field
    on every row with no extra parameter needed. LI is the one exception —
    JobSpy only populates it when linkedin_fetch_description=True is
    passed, which adds one extra request PER RESULT ("increases requests by
    O(n)" per JobSpy's own docs) — a real cost given LI is this scraper's
    single biggest source. Deliberately left off (see the
    linkedin_fetch_description=False call below) — a LI-only role's
    `sponsorshipSignal` (see sponsorship_signal() above) will always be [],
    not because nothing was found but because nothing was ever fetched to
    look at. Revisit if this proves to be a real gap once more data has
    accumulated (a LI-corroborated role that also turns up on Indeed/Bayt
    still gets a description via that second source — see
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


def run_google_searches(combos, debug=False):
    """*** RETIRED 2026-09-24, NO LONGER CALLED FROM main() AT ALL — see the
    module docstring's "GOOGLE: RETIRED" section. Unlike Bayt, there is no
    Playwright replacement for this one. *** Extracted verbatim from what
    used to be inline in run_searches() above. Left fully intact purely as
    a reference/rollback path; not exercised by any live code path today.
    JobSpy's Google adapter returns 0 rows with an "initial cursor not
    found" warning on every real request — Google serves an HTTP-200
    "enable JavaScript" bootstrap shell to non-JS HTTP clients (per a
    JobSpy maintainer's own account of this exact failure mode), so this
    doesn't even fail loudly the way Bayt's 403s did."""
    from jobspy import scrape_jobs

    for term, location in combos:
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
        except Exception as e:  # noqa: BLE001 — same isolation as run_searches()
            print(f"[scrape] google search failed ({query!r}): {e}", file=sys.stderr)
            df4 = None
        if df4 is not None and len(df4):
            for row in df4.to_dict(orient="records"):
                yield ("google", row)
        time.sleep(random.uniform(PAUSE_BETWEEN_SEARCHES_SECONDS_MIN, PAUSE_BETWEEN_SEARCHES_SECONDS_MAX))


def run_bayt_searches(debug=False):
    """*** RETIRED 2026-09-24, NO LONGER CALLED FROM main() — see the module
    docstring's "BAYT: NOW VIA PLAYWRIGHT, NOT JOBSPY" section. *** JobSpy's
    Bayt adapter gets an outright 403 on every request regardless of IP or
    user_agent — confirmed both from GitHub Actions and from a real home
    IP. Left fully intact (not deleted) purely as a ready rollback path if
    the Playwright replacement (run_bayt_playwright_searches() below) ever
    needs to be abandoned; not exercised by any live code path today.

    Originally: yields (source, row) for every one of SEARCH_TERMS against
    Bayt — all 38, every run, not chunked (see BAYT_PAUSE_BETWEEN_SEARCHES_*'s
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


def run_bayt_playwright_searches(debug=False):
    """Yields (source, row) for every SEARCH_TERMS entry against Bayt, via a
    real headless-Chromium Playwright scrape — the replacement for
    run_bayt_searches() above (see the module docstring's "BAYT: NOW VIA
    PLAYWRIGHT" section for why). Thin wrapper around
    bayt_playwright.scrape_bayt() — imports it lazily, inside this
    function, so scrape.py itself stays importable (match.py/test_match.py/
    test_rotation.py, none of which need Bayt at all) without the
    playwright package installed, same reasoning as jobspy's own lazy
    import in run_searches()/run_bayt_searches()."""
    from bayt_playwright import scrape_bayt

    yield from scrape_bayt(SEARCH_TERMS, debug=debug)


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
    of (source, row) — source is "li", "indeed", or "bayt", tagged onto the kept role (plus retained in its "sources" array
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
    # 2 JobSpy requests/combo now (li + indeed only — google and glassdoor
    # both retired outright, see the module docstring) + a flat 38 Bayt page
    # loads via Playwright, not a JobSpy request — see
    # run_bayt_playwright_searches().
    max_requests_this_run = len(this_chunk) * 2 + len(SEARCH_TERMS)
    print(
        f"[scrape] {len(combos)} total combos ({len(SEARCH_TERMS)} terms x {len(LOCATIONS)} locations), "
        f"{COMBOS_PER_RUN}/run -> {total_chunks} chunks -> full cycle ~{cycle_hours}h (~{cycle_hours / 24:.1f} days) "
        f"[cycle length set independently of which sites are queried — see COMBOS_PER_RUN's own comment]"
    )
    print(f"[scrape] this run: chunk {chunk_index + 1}/{total_chunks} "
          f"({len(this_chunk)} combos x li+indeed (JobSpy) "
          f"+ {len(SEARCH_TERMS)} bayt page loads (Playwright) = up to {max_requests_this_run} requests; "
          f"google and glassdoor both retired, neither searched at all)")

    index = build_index(COMPANIES, ALIASES)
    rows = (
        list(run_searches(this_chunk, debug=debug))
        + list(run_bayt_playwright_searches(debug=debug))
    )
    counts = {}
    for source, _ in rows:
        counts[source] = counts.get(source, 0) + 1
    counts_str = ", ".join(f"{counts.get(s, 0)} {s}" for s in ("li", "indeed", "bayt"))
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
