"""
li-scraper: finds design/product roles on job boards and writes
data/li-snapshot.json, which check.php merges into ZenPath alongside each
company's own careers board.

Sources (one generator each, all yielding (source, row)):
  li            LinkedIn's public job search (linkedin_guest.py), every market on
                every run: the terms combined into a few OR queries, each searched
                only for the time since it last succeeded (run_linkedin).
  indeed        JobSpy keyword searches over the SEARCH_TERMS x LOCATIONS grid,
                in rotating chunks (run_indeed_searches).
  welcometonl   welcome-to-nl.nl's search backend (welcome_to_nl.py).
Retired: Glassdoor and Google (2026-09: bot walls; Glassdoor's API is gone), Bayt
(2026-10-26: Cloudflare refused GitHub's runner on 35 of 38 searches, its
robots.txt bars crawling search results, and it added ~14 roles in our markets
that LinkedIn/Indeed don't already cover), uxwork.nl (2026-10-27: its SiteGround
firewall answers GitHub's runner with HTTP 403 even in a real browser; it never
delivered a row from the runner). englishjobsearch.nl was evaluated and
skipped (tracking-redirect URLs, overlaps LI/Indeed).

Output:
  companies   {slug: {roles: [...]}} -- postings from a tracked company in
              data/companies.json (matched by employer name, match.py) that
              pass the same title-relevance filter the app uses.
  openMarket  {roles: [...], searchedMarkets, priorityMarkets, sourceHealth, ...}
              -- postings from untracked employers that clear open_market_gate()
              (relevant, target- or below-tier fit) and are located in a searched
              market (is_known_market). Agencies are included on purpose. Newest
              first. sourceHealth is this run's per-source report (the app warns
              when a source was blocked or came back empty).
  linkedinCoverage  {"<location>|<keywords>": ISO time} -- when each LinkedIn
              search last completed, so the next run asks only for what's newer.
Every role carries `source`, a `sources` list (cross-site corroboration,
precedence in SOURCE_PRECEDENCE) and `sponsorshipSignal` (visa/relocation
phrases found in the description; always [] for LI, whose descriptions cost an
extra request each and stay off).

Indeed rotation: each scheduled run covers one chunk of the ROTATING_LOCATIONS
grid (COMBOS_PER_RUN combos, chosen from wall-clock time, so it self-heals when
GitHub skips a tick) plus, every other run, a full sweep of PRIORITY_LOCATIONS
(Singapore, Dubai, Netherlands). Results accumulate across runs; a role is
dropped only after EXPIRY_DAYS without being seen again. Cycle lengths are
printed at the start of every run and published in openMarket for the app.

Usage (locally, or via .github/workflows/scrape-li.yml):
    pip install -r requirements.txt
    python scrape.py
    python scrape.py --debug          # print every kept/dropped result, write nothing
    python scrape.py --chunk N        # force an Indeed rotation chunk
    python scrape.py --priority | --no-priority   # force Indeed's priority sweep on/off
"""

import json
import logging
import math
import os
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from companies import COMPANIES, ALIASES
from match import (
    build_index,
    match_company,
    is_role_relevant,
    normalize_scraped_title,
    normalize_employer_name,
    role_identity,
    open_market_gate,
)

# When the same (employer, title, location) identity is found on several sites,
# the lowest-ranked site supplies the canonical url/source; all sites stay in
# `sources`. The NL-only boards rank last so an existing LI/Indeed/Bayt row
# keeps its url. Unknown sources rank after everything listed.
# "bayt" and "uxwork" stay (retired 2026-10-26/27) until their last roles expire
# from the snapshot.
SOURCE_PRECEDENCE = {"ats": 0, "li": 1, "indeed": 2, "bayt": 3, "welcometonl": 4, "uxwork": 5}


def _source_rank(source):
    return SOURCE_PRECEDENCE.get(source, len(SOURCE_PRECEDENCE))


def _merge_role_records(prior, new):
    """Combine an earlier record with a fresh one for the same identity -- within
        a run (two sites, same posting) and across runs (a carried-over role seen
        again). The freshest lastSeenAt/postedDate wins; the canonical source/url
        is whichever ranks higher in SOURCE_PRECEDENCE; `sources` and
        `sponsorshipSignal` are unions, so corroboration is never lost when the
        canonical record comes from a source without a description.
    """
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


# ---- Sponsorship/relocation phrases, per posting ----
# Separate from companies.json's company-level `sponsorship` notes. Literal,
# case-insensitive substring matching on the description -- deliberately not
# fuzzy: a false "offers sponsorship" is worse than a missed one.
SPONSORSHIP_KEYWORDS = [
    "visa sponsorship",
    "relocation support",
    "international candidates",
    "global talent",
]

# Negation cues checked just before a match ("no visa sponsorship", "unable to
# offer relocation support"). Best-effort, not a parser -- which is why the app
# says "a phrase was found", never "sponsorship confirmed".
_SPONSORSHIP_NEGATION_CUES = (
    "no ", "not ", "without ", "unable to", "cannot ", "can't ", "won't ",
    "does not", "doesn't", "unfortunately",
)
_SPONSORSHIP_NEGATION_WINDOW_CHARS = 40


def _has_nearby_negation(text, match_start):
    prefix = text[max(0, match_start - _SPONSORSHIP_NEGATION_WINDOW_CHARS):match_start]
    return any(cue in prefix for cue in _SPONSORSHIP_NEGATION_CUES)


def sponsorship_signal(description):
    """SPONSORSHIP_KEYWORDS phrases found in `description` ([] for none or no
        description). A list rather than a bool so the app can show which phrase
        matched. Only each keyword's first occurrence is negation-checked.
    """
    if not description:
        return []
    text = description.lower()
    hits = []
    for keyword in SPONSORSHIP_KEYWORDS:
        idx = text.find(keyword.lower())
        if idx != -1 and not _has_nearby_negation(text, idx):
            hits.append(keyword)
    return hits

OUTPUT_PATH = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "li-snapshot.json"))

# ---- Search terms: 8 product + 26 design/UX titles (trimmed from 108 in
# ---- 2026-09; 2026-10-27: research terms and Marketing Manager removed, Design
# ---- Director and Associate Design Director added). ----
PRODUCT_TERMS = [
    "Product Manager",
    "Product Owner",
    "Product Lead",
    "Product Strategist",
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
    "Senior Design Manager",
    "Senior UX Manager",
    "Design Strategist",
    "Design Thinking Lead",
    "Design Technologist",
    "Creative Technologist",
    "VP of Design",
    "Head of Product Design",
    "Head of Design",
    "Design Director",
    "Associate Design Director",
]

SEARCH_TERMS = PRODUCT_TERMS + DESIGN_TERMS

# Target markets (2026-10-27: Japan, South Korea, Sweden and Portugal removed).
# Bare country names search the whole country; "City, Country" entries search
# that metro only. Every entry needs an INDEED_COUNTRY
# mapping below.
LOCATIONS = [
    "Singapore",
    "Hong Kong",
    "New Zealand",
    "Australia",
    "Netherlands",
    "Italy",
    "Germany",
    "United Kingdom",
    "Ireland",
    "Kuala Lumpur, Malaysia",
    "Dubai, United Arab Emirates",
]

# Searched in full (every term) every other run instead of waiting for their
# rotation turn -- see priority_combos() / priority_sweep_due(). Must be exact
# LOCATIONS entries (asserted below). "Netherlands" already covers Amsterdam.
PRIORITY_LOCATIONS = [
    "Singapore",
    "Dubai, United Arab Emirates",
    "Netherlands",
]
assert all(loc in LOCATIONS for loc in PRIORITY_LOCATIONS), \
    "PRIORITY_LOCATIONS must be an exact subset of LOCATIONS"

# What COMBOS_PER_RUN actually rotates through.
ROTATING_LOCATIONS = [loc for loc in LOCATIONS if loc not in PRIORITY_LOCATIONS]

# ---- Markets ----
# Open-market postings are eligible from any searched market (open_market_gate()
# for title/fit, is_known_market() for location). CANONICAL_MARKETS is LOCATIONS
# collapsed to countries ("Dubai, United Arab Emirates" -> "United Arab
# Emirates"), in LOCATIONS order -- the `market` label the app filters on.
def _canonical_market_name(location_entry):
    return location_entry.split(",")[-1].strip() if "," in location_entry else location_entry


CANONICAL_MARKETS = []
for _loc_entry in LOCATIONS:
    _canonical = _canonical_market_name(_loc_entry)
    if _canonical not in CANONICAL_MARKETS:
        CANONICAL_MARKETS.append(_canonical)

# Common abbreviations a location field uses instead of the canonical name
# ("Dubai, UAE"), checked as extra substrings in market_for_location().
MARKET_ALIASES = {
    "United Arab Emirates": ["uae"],
}

# ---- Resolving a raw location to one of our markets ----
# Searches scoped to one country still return postings based elsewhere (India,
# the US, Pakistan...), so open market only keeps a posting whose own location
# resolves to a searched market. Plain substring matching on country names
# isn't enough: Indeed often returns "City, StateCode, CC" ("Berlin, BE, DE")
# and LinkedIn sometimes "Greater X Area" with no country at all, so
# market_for_location() also checks the last comma segment against
# ISO_CODE_TO_MARKET and falls back to CITY_ALIASES.
#
# Ambiguous city names are left out on purpose (a real "Berlin, El Salvador"
# posting exists; Cambridge MA, Perth Scotland): when unsure, drop the rare
# legitimate posting rather than let an off-market one in.
ISO_CODE_TO_MARKET = {
    "sg": "Singapore", "hk": "Hong Kong",
    "nz": "New Zealand", "au": "Australia", "nl": "Netherlands", "it": "Italy",
    "de": "Germany", "gb": "United Kingdom",
    "uk": "United Kingdom", "ie": "Ireland", "my": "Malaysia",
    "ae": "United Arab Emirates",
}

# "Greater X Area" / "X Metropolitan Area" shapes with no country marker, each
# seen in real data. Ambiguous names (Berlin, Cambridge, Perth, Rome, London,
# Manchester) are deliberately absent -- see above.
CITY_ALIASES = {
    "amsterdam": "Netherlands", "eindhoven": "Netherlands", "utrecht": "Netherlands",
    "rotterdam": "Netherlands", "the hague": "Netherlands", "den haag": "Netherlands",
    "arnhem": "Netherlands", "den bosch": "Netherlands", "s-hertogenbosch": "Netherlands",
    "hilversum": "Netherlands",
    # Smaller Dutch cities and provinces seen with no country (2026-10-25). Short
    # names that occur inside other words (Ede, Oss, Assen, Emmen) are left out:
    # matching is by substring.
    "haarlem": "Netherlands", "alkmaar": "Netherlands", "weesp": "Netherlands",
    "hoofddorp": "Netherlands", "almere": "Netherlands", "amstelveen": "Netherlands",
    "schiphol": "Netherlands", "zaandam": "Netherlands", "zaanstad": "Netherlands",
    "diemen": "Netherlands", "purmerend": "Netherlands",
    "leiden": "Netherlands", "delft": "Netherlands", "zoetermeer": "Netherlands",
    "rijswijk": "Netherlands", "schiedam": "Netherlands", "dordrecht": "Netherlands",
    "gouda": "Netherlands", "amersfoort": "Netherlands", "nieuwegein": "Netherlands",
    "zeist": "Netherlands", "houten": "Netherlands", "veenendaal": "Netherlands",
    "breda": "Netherlands", "tilburg": "Netherlands", "helmond": "Netherlands",
    "nijmegen": "Netherlands", "apeldoorn": "Netherlands", "wageningen": "Netherlands",
    "zwolle": "Netherlands", "deventer": "Netherlands", "enschede": "Netherlands",
    "hengelo": "Netherlands", "groningen": "Netherlands", "leeuwarden": "Netherlands",
    "maastricht": "Netherlands", "venlo": "Netherlands", "lelystad": "Netherlands",
    "noord-holland": "Netherlands", "north holland": "Netherlands",
    "zuid-holland": "Netherlands", "south holland": "Netherlands",
    "noord-brabant": "Netherlands", "north brabant": "Netherlands",
    "gelderland": "Netherlands", "flevoland": "Netherlands", "overijssel": "Netherlands",
    "sydney": "Australia", "melbourne": "Australia", "brisbane": "Australia",
    "munich": "Germany", "hamburg": "Germany", "stuttgart": "Germany",
    "nuremberg": "Germany",
    "milan": "Italy", "padova": "Italy", "padua": "Italy", "vicenza": "Italy",
    "kuala lumpur": "Malaysia",
    "dublin": "Ireland", "cork": "Ireland",
    "auckland": "New Zealand", "wellington": "New Zealand", "christchurch": "New Zealand",
    "blackpool": "United Kingdom",
    "dubai": "United Arab Emirates",
}


def market_for_location(location):
    """Canonical market for a raw location, or None if it isn't one of ours. Three
        passes: (1) CANONICAL_MARKETS names + MARKET_ALIASES as substrings;
        (2) ISO_CODE_TO_MARKET, exact ("SG") or on the last comma segment
        ("Berlin, BE, DE"); (3) CITY_ALIASES. Used both as the display label and,
        via is_known_market(), as open market's location gate.
    """
    loc = (location or "").strip()
    if not loc:
        return None
    loc_lower = loc.lower()
    if loc_lower in ISO_CODE_TO_MARKET:
        return ISO_CODE_TO_MARKET[loc_lower]
    for market in CANONICAL_MARKETS:
        needles = [market.lower()] + MARKET_ALIASES.get(market, [])
        if any(needle in loc_lower for needle in needles):
            return market
    parts = [p.strip().lower() for p in loc.split(",") if p.strip()]
    if parts and parts[-1] in ISO_CODE_TO_MARKET:
        return ISO_CODE_TO_MARKET[parts[-1]]
    for city, market in CITY_ALIASES.items():
        if city in loc_lower:
            return market
    return None


def is_known_market(location):
    """Open market's location gate: the location resolves to a searched market."""
    return market_for_location(location) is not None


# LOCATIONS -> JobSpy's country_indeed strings (case- and spelling-sensitive;
# verified against JobSpy's supported list). "City, Country" entries also get a
# city-only INDEED_LOCATION_OVERRIDE, since Indeed treats `location` as a
# modifier within country_indeed.
INDEED_COUNTRY = {
    "Singapore": "Singapore",
    "Hong Kong": "Hong Kong",
    "New Zealand": "New Zealand",
    "Australia": "Australia",
    "Netherlands": "Netherlands",
    "Italy": "Italy",
    "Germany": "Germany",
    "United Kingdom": "UK",
    "Ireland": "Ireland",
    "Kuala Lumpur, Malaysia": "Malaysia",
    "Dubai, United Arab Emirates": "United Arab Emirates",
}
INDEED_LOCATION_OVERRIDE = {
    "Kuala Lumpur, Malaysia": "Kuala Lumpur",
    "Dubai, United Arab Emirates": "Dubai",
}

# Indeed (JobSpy). JobSpy has no sort parameter, so recency ordering happens in
# merge_and_prune() (openMarket roles sorted by postedDate, then lastSeenAt).
RESULTS_WANTED_PER_SEARCH = 20
HOURS_OLD = 240  # 10 days — comfortably wider than one rotation cycle (see below),
                 # so a role posted right after its combo's turn is still visible
                 # the next time that combo comes up.

# Indeed: randomized rather than a fixed delay -- a perfectly uniform gap between
# requests looks scripted; a random point in a tight range costs nothing.
PAUSE_BETWEEN_SEARCHES_SECONDS_MIN = 5
PAUSE_BETWEEN_SEARCHES_SECONDS_MAX = 11

# ---- LinkedIn (run_linkedin, linkedin_guest.py) ----
# Each market x keyword group is one search. Each search asks only for postings
# since it last completed (+ a margin, within the min/max), so a search is
# usually one request. Human pace (2026-10-27, see linkedin_guest.py): requests
# are LINKEDIN_PAUSE_SECONDS apart and a run makes at most
# LINKEDIN_MAX_REQUESTS_PER_RUN, stalest searches first, so a run that can't
# reach every search still moves the oldest ones forward and the rest get a wider
# window next time (nothing is lost while the gap is under the 7-day maximum).
# A block (429/999/403) waits out LinkedIn's penalty (LINKEDIN_BLOCK_BACKOFF_SECONDS,
# or Retry-After) and probes once with the same search; then the run moves on.
# LinkedIn stops for the run after LINKEDIN_MAX_BLOCKS_IN_A_ROW blocks in a row or
# LINKEDIN_MAX_BLOCK_WAIT_TOTAL_SECONDS of waiting. The session is warmed on the
# public search page first, and the client variant (linkedin_guest.VARIANTS) is
# picked at random per run. Every request is logged (snapshot linkedinLastRun) and
# each run summarised (linkedinHistory, last LINKEDIN_HISTORY_RUNS runs, with the
# variant) to tune these from evidence.
LINKEDIN_PAUSE_SECONDS = (60, 90)
LINKEDIN_WINDOW_MARGIN_SECONDS = 3600
LINKEDIN_MIN_WINDOW_SECONDS = 3 * 3600
LINKEDIN_MAX_WINDOW_SECONDS = 7 * 86400
LINKEDIN_FIRST_WINDOW_SECONDS = 12 * 3600  # a search with no coverage record yet
LINKEDIN_BLOCK_BACKOFF_SECONDS = (300,)  # by blocks in a row; the penalty lifted after 2-4 min
LINKEDIN_MAX_BLOCK_WAIT_SECONDS = 300  # cap on a Retry-After
LINKEDIN_MAX_BLOCKS_IN_A_ROW = 3
LINKEDIN_MAX_BLOCK_WAIT_TOTAL_SECONDS = 15 * 60
LINKEDIN_MAX_REQUESTS_PER_RUN = 30  # ~40 min at the pause above
LINKEDIN_HISTORY_RUNS = 120  # ~10 days at the 2h cadence


class ErrorLogCount(logging.Handler):
    """Counts JobSpy's error log lines for one site -- its only sign of a failed
        or blocked search, since it returns an empty result rather than raising.
    """

    def __init__(self):
        super().__init__(level=logging.ERROR)
        self.count = 0

    def emit(self, record):
        self.count += 1


# ---- Indeed rotation ----
# One run = one chunk of ROTATING_LOCATIONS x SEARCH_TERMS (272 combos since the
# 2026-10-27 trim), picked from wall-clock time so runs walk the whole grid and
# wrap around. 68 divides the grid into 4 equal chunks -> a full rotation every
# ~8h at the 2h cadence (the priority sweep adds its own combos every other run).
# Pacing is ~8s/combo, so ~9 min per run. LinkedIn doesn't rotate (see run_linkedin).
#
# The lever for rotation speed vs. request volume (block risk) is this number.
COMBOS_PER_RUN = 68
# Wall-clock bucket size for the rotation and the priority sweep. Must match
# SCHEDULE_INTERVAL_HOURS in .github/workflows/scrape-li.yml's gate step: the
# workflow fires every 15 minutes, but only runs when this much time has passed
# since the last snapshot commit. Tune COMBOS_PER_RUN, not this, to change
# rotation speed.
SCHEDULE_INTERVAL_HOURS = 2  # must match .github/workflows/scrape-li.yml's gate

# A role not seen again within this many days is dropped. Kept well above two
# full rotations, so a role is never pruned just for waiting its turn.
EXPIRY_DAYS = 14


def all_combos():
    """Every Indeed combo across all of LOCATIONS (priority + rotating) -- for
        accounting and tests; main() searches rotating_combos()/priority_combos().
    """
    return [(term, loc) for term in SEARCH_TERMS for loc in LOCATIONS]


def rotating_combos():
    """Combos for ROTATING_LOCATIONS -- what COMBOS_PER_RUN chunks through."""
    return [(term, loc) for term in SEARCH_TERMS for loc in ROTATING_LOCATIONS]


def priority_combos():
    """Every term x every PRIORITY_LOCATIONS entry; added on top of a run's
        rotating chunk when priority_sweep_due().
    """
    return [(term, loc) for term in SEARCH_TERMS for loc in PRIORITY_LOCATIONS]


def current_chunk_index(total_chunks, forced=None):
    if forced is not None:
        return forced % total_chunks
    # Which SCHEDULE_INTERVAL_HOURS-wide bucket of wall-clock time this is.
    # Consecutive real runs land in consecutive buckets without any stored state;
    # a delayed or manual run may repeat or skip a chunk, which evens out.
    bucket = int(time.time() // (SCHEDULE_INTERVAL_HOURS * 3600))
    return bucket % total_chunks


def priority_sweep_due(forced=None):
    """Whether this run adds the PRIORITY_LOCATIONS sweep: due on even-numbered
        wall-clock buckets (same buckets as current_chunk_index()), so roughly
        every other real run. Stateless, so a dropped GitHub tick can't desync it.
    """
    if forced is not None:
        return forced % 2 == 0
    bucket = int(time.time() // (SCHEDULE_INTERVAL_HOURS * 3600))
    return bucket % 2 == 0


def linkedin_searches():
    """(location, keywords) for every LinkedIn search: each market x each keyword group."""
    from linkedin_guest import keyword_groups

    groups = keyword_groups(SEARCH_TERMS)
    return [(loc, kw) for loc in LOCATIONS for kw in groups]


def linkedin_key(location, keywords):
    return f"{location}|{keywords}"


def _iso_utc(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _epoch(iso):
    try:
        return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
    except (TypeError, ValueError):
        return None


def run_linkedin(coverage, get=None, sleep=time.sleep, now=time.time, variant=None):
    """LinkedIn for this run (see the LinkedIn constants). Returns (rows, coverage,
        health, request_log): rows as ("li", row); coverage updated for the searches
        that completed (searches no longer configured are dropped); health for
        sourceHealth and linkedinHistory; request_log one entry per search request
        (the warm-up is in health). `get` replaces the HTTP client (tests).
    """
    from linkedin_guest import BLOCK_STATUSES, VARIANTS, Blocked, open_session, page_title, search, warm_up

    if get is None:
        variant = variant or random.choice(VARIANTS)
        get = open_session(variant)

    searches = linkedin_searches()
    keys = {linkedin_key(loc, kw) for loc, kw in searches}
    groups = sorted({kw for _, kw in searches}, key=[kw for _, kw in searches].index)
    coverage = {k: v for k, v in (coverage or {}).items() if k in keys}
    # Stalest first, so a run cut short still moves the oldest searches forward.
    searches.sort(key=lambda s: _epoch(coverage.get(linkedin_key(*s))) or 0)

    run_started = now()
    request_log = []

    def logged_get(url, params=None, **kw):
        entry = {"s": round(now() - run_started), "loc": params["location"], "g": groups.index(params["keywords"]),
                 "start": params["start"], "windowH": round(int(params["f_TPR"][1:]) / 3600, 1)}
        try:
            resp = get(url, params=params, **kw)
        except Exception as e:  # noqa: BLE001 — logged, then handled by the caller
            entry.update(status=0, error=type(e).__name__)
            request_log.append(entry)
            raise
        entry.update(status=resp.status_code, bytes=len(resp.text or ""))
        if resp.status_code in BLOCK_STATUSES:
            entry["title"] = page_title(resp.text)
        request_log.append(entry)
        return resp

    def pause():
        sleep(random.uniform(*LINKEDIN_PAUSE_SECONDS))

    rows, requests_made, done, blocks, capped = [], 0, 0, 0, 0
    blocks_in_a_row = waited = 0
    stopped = False
    warm_status = warm_up(get, searches[0][1], searches[0][0]) if searches else None
    if searches:
        pause()
    for i, (location, keywords) in enumerate(searches):
        if requests_made >= LINKEDIN_MAX_REQUESTS_PER_RUN:
            print(f"[linkedin] request budget ({LINKEDIN_MAX_REQUESTS_PER_RUN}) used; "
                  f"{len(searches) - i} search(es) wait for the next run", file=sys.stderr)
            break
        if blocks_in_a_row >= LINKEDIN_MAX_BLOCKS_IN_A_ROW or waited >= LINKEDIN_MAX_BLOCK_WAIT_TOTAL_SECONDS:
            stopped = True
            print(f"[linkedin] {blocks_in_a_row} blocks in a row / {waited}s waited; "
                  f"no more LinkedIn this run ({len(searches) - i} search(es) wait)", file=sys.stderr)
            break
        if i:
            pause()
        started = now()
        last = _epoch(coverage.get(linkedin_key(location, keywords)))
        window = (LINKEDIN_FIRST_WINDOW_SECONDS if last is None
                  else min(max(started - last + LINKEDIN_WINDOW_MARGIN_SECONDS, LINKEDIN_MIN_WINDOW_SECONDS),
                           LINKEDIN_MAX_WINDOW_SECONDS))
        found = None
        for attempt in (1, 2):
            try:
                found, n, was_capped = search(logged_get, keywords, location, window, pause)
                requests_made += n
                capped += was_capped
                blocks_in_a_row = 0
                break
            except Blocked as b:
                requests_made += b.requests
                rows.extend(("li", r) for r in b.rows)
                blocks += 1
                blocks_in_a_row += 1
                if blocks_in_a_row >= LINKEDIN_MAX_BLOCKS_IN_A_ROW:
                    break
                step = LINKEDIN_BLOCK_BACKOFF_SECONDS[min(blocks_in_a_row, len(LINKEDIN_BLOCK_BACKOFF_SECONDS)) - 1]
                wait = min(b.wait or step, LINKEDIN_MAX_BLOCK_WAIT_SECONDS)
                print(f"[linkedin] blocked (HTTP {b.status}) on {location!r}, request {len(request_log)}; waiting {wait}s"
                      + (", then one retry" if attempt == 1 else ", then the next search"), file=sys.stderr)
                sleep(wait)
                waited += wait
            except Exception as e:  # noqa: BLE001 — one bad search must not kill the run
                requests_made += 1
                print(f"[linkedin] {location!r} failed: {type(e).__name__}: {e}", file=sys.stderr)
                break
        if found is not None:
            rows.extend(("li", r) for r in found)
            coverage[linkedin_key(location, keywords)] = _iso_utc(started)
            done += 1
    # The last search can end on the block that reaches the limit, without the
    # loop's own check running again.
    stopped = stopped or blocks_in_a_row >= LINKEDIN_MAX_BLOCKS_IN_A_ROW

    end = now()
    covered = [_epoch(coverage.get(linkedin_key(*s))) for s in searches]
    stalest = max(((end - c) / 3600 if c else None) for c in covered) if all(covered) else None
    first_block = next((n for n, e in enumerate(request_log, 1) if e["status"] in BLOCK_STATUSES), None)
    health = {
        # Client variant (linkedin_guest.open_session) and the warm-up's HTTP status.
        "variant": variant, "warmStatus": warm_status,
        "searches": len(searches), "done": done, "requests": requests_made, "blocked": blocks,
        "stoppedEarly": stopped, "rows": len(rows), "capped": capped,
        # Hours since the least recently completed search (None: some never completed).
        "stalestHours": round(stalest, 1) if stalest is not None else None,
        # Which request was the first refused, and how far into the run (tuning evidence).
        "firstBlockRequest": first_block,
        "firstBlockSecs": request_log[first_block - 1]["s"] if first_block else None,
        "minutes": round((end - run_started) / 60, 1),
    }
    print(f"[linkedin] {variant or 'injected'} client, warm-up HTTP {warm_status}; "
          f"{done} of {len(searches)} searches done, {requests_made} requests, {blocks} block(s)"
          + (f", first at request {first_block}" if first_block else "")
          + ("; stopped early" if stopped else ""), file=sys.stderr)
    return rows, coverage, health, request_log


def run_indeed_searches(combos, debug=False, scrape_jobs=None, sleep=time.sleep):
    """Indeed for this run's combos, paced, one scrape_jobs() call and try/except
        per combo. Returns (rows as ("indeed", row), health). jobspy is imported
        lazily so the tests run without it (they pass scrape_jobs/sleep).
    """
    if scrape_jobs is None:
        from jobspy import scrape_jobs

    errors = ErrorLogCount()
    indeed_logger = logging.getLogger("jobspy.indeed")
    indeed_logger.addHandler(errors)
    rows, failed = [], 0
    try:
        for i, (term, location) in enumerate(combos):
            if i:
                sleep(random.uniform(PAUSE_BETWEEN_SEARCHES_SECONDS_MIN, PAUSE_BETWEEN_SEARCHES_SECONDS_MAX))
            indeed_country = INDEED_COUNTRY.get(location)
            if not indeed_country:
                continue  # shouldn't happen — every LOCATIONS entry has a mapping — but skip cleanly if it ever doesn't
            indeed_location = INDEED_LOCATION_OVERRIDE.get(location, location)
            if debug:
                print(f"[scrape] searching (indeed): {term!r} @ {indeed_location!r} ({indeed_country})", file=sys.stderr)
            before = errors.count
            try:
                df = scrape_jobs(
                    site_name=["indeed"],
                    search_term=term,
                    location=indeed_location,
                    country_indeed=indeed_country,
                    results_wanted=RESULTS_WANTED_PER_SEARCH,
                    hours_old=HOURS_OLD,
                    verbose=1 if debug else 0,
                )
            except Exception as e:  # noqa: BLE001 — one bad search must not kill the run
                print(f"[scrape] indeed search failed ({term!r} @ {indeed_location!r}): {e}", file=sys.stderr)
                df = None
                errors.count += 1
            failed += errors.count > before
            if df is not None and len(df):
                rows.extend(("indeed", row) for row in df.to_dict(orient="records"))
    finally:
        indeed_logger.removeHandler(errors)
    print(f"[scrape] indeed: {len(combos) - failed} of {len(combos)} searches ok, {len(rows)} results", file=sys.stderr)
    return rows, {"searches": len(combos), "failed": failed, "rows": len(rows)}


def run_welcome_to_nl_searches(debug=False):
    """Yields ("welcometonl", row) for every SEARCH_TERMS entry (welcome_to_nl.py,
        imported lazily like the others).
    """
    from welcome_to_nl import scrape_welcome_to_nl

    yield from scrape_welcome_to_nl(SEARCH_TERMS, debug=debug)


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
    """Coerce a raw JobSpy field to str. Pandas represents a missing value as NaN,
        a truthy float, so `value or ""` lets it through to string code; `value !=
        value` catches NaN without importing pandas.
    """
    if value is None or (isinstance(value, float) and value != value):
        return ""
    return str(value)


def build_fresh_roles(rows, index, today_iso, debug=False):
    """Filter this run's raw (source, row) results down to real matches, keyed by
        role_identity() (normalized employer + title + location, not URL -- the
        same posting often has a different URL per site, or a new one later).
    
        Returns (fresh, fresh_open_market), both {identity: (key, role)}:
          fresh              tracked-company matches; key = company slug.
          fresh_open_market  no tracked match, but open_market_gate() (title/fit)
                             and is_known_market() (location) both pass;
                             key = normalize_employer_name(employer).
        Everything else is dropped. Exact-URL duplicates are dropped first, as a
        cheap check before the identity merge.
    """
    fresh = {}  # identity tuple -> (slug, role dict)
    fresh_open_market = {}  # identity tuple -> (normalized employer key, role dict) — 2.2
    seen_urls = set()
    kept = dropped_company = dropped_title = duplicate = merged_cross_site = 0
    kept_open_market = dropped_open_market_strict = merged_cross_site_open_market = 0
    dropped_off_market = 0  # location doesn't resolve to a searched market

    for source, row in rows:
        url = _clean_str(row.get("job_url"))
        if not url or url in seen_urls:
            duplicate += 1
            continue
        seen_urls.add(url)

        employer = _clean_str(row.get("company"))
        # Strip CTA run-on text and, only when the site gave no location, recover one
        # from the title. _clean_str() first: normalize_scraped_title() would
        # str() a NaN.
        title, location = normalize_scraped_title(_clean_str(row.get("title")), _clean_str(row.get("location")))
        slug = match_company(employer, index)

        if not slug:
            dropped_company += 1
            if debug:
                print(f"[match] no company match: {employer!r} — {row.get('title')!r}", file=sys.stderr)
            # Not a tracked company: a candidate for open market. Requires a searched
            # market (is_known_market) and a non-empty employer -- an open-market row with
            # no employer name is useless in the app.
            if not is_known_market(location):
                dropped_off_market += 1
                if debug:
                    print(f"[open-market] off-market location: {title!r} @ {employer!r} ({location!r})", file=sys.stderr)
                continue
            market = market_for_location(location)
            if employer and open_market_gate(title, employer):
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
            f"dropped_off_market={dropped_off_market} "
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
    """Merge mechanics shared by both branches of merge_and_prune() (tracked and
        open market); they differ only in output shape, handled there.
    
        existing_items: (key, role) pairs from the existing snapshot (key = slug,
        or normalized employer for open market). fresh_roles: {identity: (key,
        role)} from this run. Returns (kept_items, stats): this run's roles merged
        via _merge_role_records(), plus carried-over roles younger than
        EXPIRY_DAYS since lastSeenAt; stats counts added/updated/carried_over/
        expired. Older roles missing `sources` or `sponsorshipSignal` are
        backfilled here.
    """
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
    """Merge this run's results into the snapshot loaded from disk and prune
        expired roles. Returns {"companies": {slug: {"roles": [...]}},
        "openMarket": {"roles": [...]}}; open-market roles are never filed under
        a company.
    """
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

    # Same mechanics on the open-market side; the key is re-derived from the
    # employer. Carried-over roles go through the same market gate as fresh ones,
    # so a rule change applies to the whole snapshot on the next run.
    existing_open_market_items = (
        (normalize_employer_name(role.get("employer", "")), dict(role, market=market_for_location(role.get("location", ""))))
        for role in existing.get("openMarket", {}).get("roles", [])
        if is_known_market(role.get("location", ""))
    )
    kept_open_market_items, om_stats = _merge_identity_roles(
        existing_open_market_items, fresh_open_market_roles, cutoff
    )
    # Newest postedDate first; roles without one sort last ("" is smallest, and
    # reverse=True puts it at the end).
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
    # --priority / --no-priority force the priority sweep on or off, like --chunk.
    forced_priority = None
    if "--priority" in sys.argv:
        forced_priority = 0  # even -> due, per priority_sweep_due()
    elif "--no-priority" in sys.argv:
        forced_priority = 1  # odd -> not due

    rotating = rotating_combos()
    total_chunks = math.ceil(len(rotating) / COMBOS_PER_RUN)
    chunk_index = current_chunk_index(total_chunks, forced=forced_chunk)
    this_chunk = rotating[chunk_index * COMBOS_PER_RUN: (chunk_index + 1) * COMBOS_PER_RUN]

    include_priority = priority_sweep_due(forced=forced_priority)
    priority = priority_combos() if include_priority else []
    combos_this_run = this_chunk + priority

    cycle_hours = total_chunks * SCHEDULE_INTERVAL_HOURS
    print(
        f"[scrape] LinkedIn: {len(linkedin_searches())} searches ({len(LOCATIONS)} markets x keyword groups), "
        f"every run. Indeed: rotating pool of {len(rotating)} combos ({len(SEARCH_TERMS)} terms x "
        f"{len(ROTATING_LOCATIONS)} rotating locations), {COMBOS_PER_RUN}/run -> {total_chunks} chunks -> "
        f"full cycle ~{cycle_hours}h; priority pool {len(PRIORITY_LOCATIONS)} markets ({', '.join(PRIORITY_LOCATIONS)}) "
        f"x {len(SEARCH_TERMS)} terms, swept every other run (~{2 * SCHEDULE_INTERVAL_HOURS}h)."
    )
    print(f"[scrape] this run: Indeed chunk {chunk_index + 1}/{total_chunks} ({len(this_chunk)} combos)"
          + (f" + priority sweep ({len(priority)} combos)" if include_priority else " (priority sweep not due)")
          + f"; LinkedIn up to {LINKEDIN_MAX_REQUESTS_PER_RUN} requests; welcome-to-nl up to "
          f"{len(SEARCH_TERMS) * 2} requests")

    index = build_index(COMPANIES, ALIASES)
    existing = load_existing_snapshot()
    checked_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    # LinkedIn spends most of its ~40 min pausing between requests (human pace), so
    # it runs alongside Indeed and Welcome to NL rather than before them.
    with ThreadPoolExecutor(max_workers=1) as pool:
        linkedin = pool.submit(run_linkedin, existing.get("linkedinCoverage"))
        indeed_rows, indeed_health = run_indeed_searches(combos_this_run, debug=debug)
        welcome_rows = list(run_welcome_to_nl_searches(debug=debug))
        li_rows, coverage, li_health, li_log = linkedin.result()
    rows = li_rows + indeed_rows + welcome_rows
    counts = {}
    for source, _ in rows:
        counts[source] = counts.get(source, 0) + 1
    counts_str = ", ".join(f"{counts.get(s, 0)} {s}" for s in ("li", "indeed", "welcometonl"))
    print(f"[scrape] {len(rows)} raw results this run ({counts_str})")

    today_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    fresh_roles, fresh_open_market_roles = build_fresh_roles(rows, index, today_iso, debug=debug)
    snapshot = merge_and_prune(existing, fresh_roles, today_iso, fresh_open_market_roles=fresh_open_market_roles, debug=debug)
    snapshot["linkedinCoverage"] = coverage
    # Evidence for tuning the LinkedIn settings: this run's requests, and a summary
    # of the last LINKEDIN_HISTORY_RUNS runs.
    snapshot["linkedinLastRun"] = li_log
    history = existing.get("linkedinHistory") if isinstance(existing.get("linkedinHistory"), list) else []
    snapshot["linkedinHistory"] = (history + [{"at": checked_at, **li_health}])[-LINKEDIN_HISTORY_RUNS:]

    # What the app's "which markets" tooltip and source warnings show -- published
    # here so they can never drift from LOCATIONS / the rotation settings.
    snapshot["openMarket"].update({
        "searchedMarkets": list(CANONICAL_MARKETS),
        "priorityMarkets": [_canonical_market_name(loc) for loc in PRIORITY_LOCATIONS],
        "fullCycleHours": cycle_hours,
        "prioritySweepHours": 2 * SCHEDULE_INTERVAL_HOURS,
        # At best one request per search, LINKEDIN_MAX_REQUESTS_PER_RUN per run.
        "linkedinEveryHours": math.ceil(li_health["searches"] / LINKEDIN_MAX_REQUESTS_PER_RUN) * SCHEDULE_INTERVAL_HOURS,
        "sourceHealth": {
            "checkedAt": checked_at,
            "linkedin": li_health,
            "indeed": indeed_health,
            "welcometonl": {"rows": len(welcome_rows)},
        },
    })

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
