"""
li-scraper: finds design/product roles on job boards and writes
data/li-snapshot.json, which check.php merges into ZenPath alongside each
company's own careers board.

Sources (one generator each, all yielding (source, row)). The Talent Hubs
(official job portals) are a separate scraper, ../hb-scraper, with its own
snapshot and workflow; both share roles.py (markets, matching, duplicates).
  li            LI's public job search (li_guest.py) at human pace:
                the terms combined into a few OR queries per market, each searched
                only for the time since it last succeeded, stalest first, up to
                LI_MAX_REQUESTS_PER_RUN requests a run (run_li).
  indeed        JobSpy keyword searches over the SEARCH_TERMS x LOCATIONS grid,
                in rotating chunks (run_indeed_searches).
Retired: Glassdoor and Google (2026-09: bot walls; Glassdoor's API is gone), Bayt
(2026-10-26: Cloudflare refused GitHub's runner on 35 of 38 searches, its
robots.txt bars crawling search results, and it added ~14 roles in our markets
that LI/Indeed don't already cover), uxwork.nl (2026-10-27: its SiteGround
firewall answers GitHub's runner with HTTP 403 even in a real browser; it never
delivered a row from the runner). englishjobsearch.nl was evaluated and
skipped (tracking-redirect URLs, overlaps LI/Indeed).

Output:
  companies   {slug: {roles: [...]}} -- postings from a tracked company in
              data/companies.json (matched by employer name, match.py) that
              pass the same title-relevance filter the app uses.
  openMarket  {roles: [...], searchedMarkets, searchTerms, priorityMarkets, sourceHealth, ...}
              -- postings from untracked employers that clear open_market_gate()
              (relevant, target- or below-tier fit) and are located in a searched
              market (is_known_market). Agencies are included on purpose. Newest
              first. sourceHealth is this run's LI/Indeed report and talentHubs
              each hub's (the app warns when a source was blocked or came back
              empty). The app files a role under Talent Hubs when no general
              board (LI, Indeed) found it.
  liCoverage  {"<location>|<keywords>": ISO time} -- when each LI
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

import logging
import math
import os
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from companies import COMPANIES, ALIASES
from match import build_index
from roles import SEARCH_TERMS, SEARCHED_MARKETS, build_fresh_roles, load_snapshot, merge_and_prune, write_snapshot

OUTPUT_PATH = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "li-snapshot.json"))

# Searched markets (2026-10-27: Japan, South Korea, Sweden and Portugal removed;
# Japan back 2026-11-16, out again 2026-11-24: Mercari's own board covers it).
# The app's accepted countries (app.js TARGET_COUNTRY_NAMES) are these plus
# roles.EXTRA_MARKETS (Talent Hubs only) and Japan (Mercari).
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
# rotation turn -- see priority_combos() / next_rotation(). Must be exact
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


def _canonical_market_name(location_entry):
    """'Dubai, United Arab Emirates' -> 'United Arab Emirates'."""
    return location_entry.split(",")[-1].strip() if "," in location_entry else location_entry


assert list(dict.fromkeys(_canonical_market_name(loc) for loc in LOCATIONS)) == SEARCHED_MARKETS, \
    "roles.SEARCHED_MARKETS must be LOCATIONS collapsed to countries, in order"


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

# ---- LI (run_li, li_guest.py) ----
# Each market x keyword group is one search, and each search is one load of
# LI's public search page (up to ~60 postings), asking only for postings
# since that search last completed (+ a margin, within the min/max). Human pace
# (2026-10-27, see li_guest.py): searches are LI_PAUSE_SECONDS apart
# and a run makes at most LI_MAX_REQUESTS_PER_RUN requests, stalest searches
# first, so a run cut short still moves the oldest ones forward and the rest get a
# wider window next time (nothing is lost while the gap is under the 7-day maximum).
# A results page with no cards is a search with no new postings (done, no wait).
# A block (429/999/403, the sign-in wall, or a cardless page that isn't the
# search's results page) waits out LI's penalty
# (LI_BLOCK_BACKOFF_SECONDS, or Retry-After) and retries the same search
# once; then the run moves on. LI stops for the run after
# LI_MAX_BLOCKS_IN_A_ROW blocks in a row or LI_MAX_BLOCK_WAIT_TOTAL_SECONDS
# of waiting. The client variant (li_guest.VARIANTS) is picked at random per
# run. Every request is logged (snapshot liLastRun) and each run summarised
# (liHistory, last LI_HISTORY_RUNS runs, with the variant) to tune these
# from evidence.
LI_PAUSE_SECONDS = (60, 90)
LI_WINDOW_MARGIN_SECONDS = 3600
LI_MIN_WINDOW_SECONDS = 3 * 3600
LI_MAX_WINDOW_SECONDS = 7 * 86400
LI_FIRST_WINDOW_SECONDS = 12 * 3600  # a search with no coverage record yet
LI_BLOCK_BACKOFF_SECONDS = (300,)  # by blocks in a row; the penalty lifted after 2-4 min
LI_MAX_BLOCK_WAIT_SECONDS = 300  # cap on a Retry-After
LI_MAX_BLOCKS_IN_A_ROW = 3
LI_MAX_BLOCK_WAIT_TOTAL_SECONDS = 15 * 60
LI_MAX_REQUESTS_PER_RUN = 36  # every search (33) plus 3 retries; ~45 min at the pause above
LI_HISTORY_RUNS = 120  # ~30 days at the observed ~6 h spacing


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
# One run = one chunk of ROTATING_LOCATIONS x SEARCH_TERMS (272 combos -> 4 chunks
# of 68; 5 while Japan was searched, 16-24 Nov). Each run takes the chunk after the
# previous run's and the priority sweep alternates, both read from the snapshot
# (indeedRotation), so the grid is walked in order however far apart GitHub starts
# the runs (2026-11-16: ~6 h apart on a 2 h schedule; the wall-clock buckets used
# before skipped around). Pacing is ~8s/combo, so ~9 min per run. LI doesn't
# rotate (see run_li).
#
# The lever for rotation speed vs. request volume (block risk) is this number.
COMBOS_PER_RUN = 68
# The workflow fires every 15 minutes but only runs when this much time has passed
# since the last snapshot commit (.github/workflows/scrape-li.yml's gate step).
# GitHub delays most runs well past it, so the timings the app shows come from
# observed_run_gap_hours(), not from this.
SCHEDULE_INTERVAL_HOURS = 2  # must match .github/workflows/scrape-li.yml's gate
# How many recent runs (liHistory) the observed spacing is measured over.
RUN_GAP_SAMPLE_RUNS = 20


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
        rotating chunk when next_rotation() says the sweep is due.
    """
    return [(term, loc) for term in SEARCH_TERMS for loc in PRIORITY_LOCATIONS]


def next_rotation(previous, total_chunks, forced_chunk=None, forced_priority=None):
    """(chunk index, priority sweep due) for this run: the chunk after the previous
        run's and the opposite sweep choice, from the snapshot's indeedRotation. No or
        unreadable previous state starts at chunk 0 with the sweep. --chunk /
        --priority / --no-priority override either part.
    """
    try:
        chunk = (int(previous["chunk"]) + 1) % total_chunks
        priority = not bool(previous["priority"])
    except (TypeError, KeyError, ValueError):
        chunk, priority = 0, True
    if forced_chunk is not None:
        chunk = forced_chunk % total_chunks
    if forced_priority is not None:
        priority = forced_priority
    return chunk, priority


def observed_run_gap_hours(history):
    """Median hours between the last RUN_GAP_SAMPLE_RUNS runs in liHistory (its
        "at" times), or SCHEDULE_INTERVAL_HOURS with fewer than 3 gaps to go on.
    """
    times = []
    for entry in history[-(RUN_GAP_SAMPLE_RUNS + 1):]:
        try:
            times.append(datetime.strptime(entry["at"], "%Y-%m-%dT%H:%M:%SZ").timestamp())
        except (TypeError, KeyError, ValueError):
            continue
    gaps = sorted((b - a) / 3600 for a, b in zip(times, times[1:]) if b > a)
    if len(gaps) < 3:
        return float(SCHEDULE_INTERVAL_HOURS)
    mid = len(gaps) // 2
    return gaps[mid] if len(gaps) % 2 else (gaps[mid - 1] + gaps[mid]) / 2


def li_searches():
    """(location, keywords) for every LI search: each market x each keyword group."""
    from li_guest import keyword_groups

    groups = keyword_groups(SEARCH_TERMS)
    return [(loc, kw) for loc in LOCATIONS for kw in groups]


def li_key(location, keywords):
    return f"{location}|{keywords}"


def _iso_utc(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _epoch(iso):
    try:
        return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
    except (TypeError, ValueError):
        return None


def run_li(coverage, get=None, sleep=time.sleep, now=time.time, variant=None):
    """LI for this run (see the LI constants). Returns (rows, coverage,
        health, request_log): rows as ("li", row); coverage updated for the searches
        that completed (searches no longer configured are dropped); health for
        sourceHealth and liHistory; request_log one entry per request.
        `get` replaces the HTTP client (tests).
    """
    from li_guest import VARIANTS, Blocked, open_session, page_title, search, search_url

    if get is None:
        variant = variant or random.choice(VARIANTS)
        get = open_session(variant)

    searches = li_searches()
    keys = {li_key(loc, kw) for loc, kw in searches}
    groups = sorted({kw for _, kw in searches}, key=[kw for _, kw in searches].index)
    coverage = {k: v for k, v in (coverage or {}).items() if k in keys}
    # Stalest first, so a run cut short still moves the oldest searches forward.
    searches.sort(key=lambda s: _epoch(coverage.get(li_key(*s))) or 0)

    run_started = now()
    request_log = []
    last_response = {}

    def recording_get(url, **kw):
        resp = get(url, **kw)
        last_response["resp"] = resp
        return resp

    rows, requests_made, done, blocks, capped = [], 0, 0, 0, 0
    blocks_in_a_row = waited = 0
    stopped = False
    referer = None
    for i, (location, keywords) in enumerate(searches):
        if requests_made >= LI_MAX_REQUESTS_PER_RUN:
            print(f"[li] request budget ({LI_MAX_REQUESTS_PER_RUN}) used; "
                  f"{len(searches) - i} search(es) wait for the next run", file=sys.stderr)
            break
        if blocks_in_a_row >= LI_MAX_BLOCKS_IN_A_ROW or waited >= LI_MAX_BLOCK_WAIT_TOTAL_SECONDS:
            stopped = True
            print(f"[li] {blocks_in_a_row} blocks in a row / {waited}s waited; "
                  f"no more LI this run ({len(searches) - i} search(es) wait)", file=sys.stderr)
            break
        if i:
            sleep(random.uniform(*LI_PAUSE_SECONDS))
        started = now()
        last = _epoch(coverage.get(li_key(location, keywords)))
        window = (LI_FIRST_WINDOW_SECONDS if last is None
                  else min(max(started - last + LI_WINDOW_MARGIN_SECONDS, LI_MIN_WINDOW_SECONDS),
                           LI_MAX_WINDOW_SECONDS))
        found = None
        for attempt in (1, 2):
            if requests_made >= LI_MAX_REQUESTS_PER_RUN:
                break
            requests_made += 1
            last_response.clear()
            entry = {"s": round(now() - run_started), "loc": location, "g": groups.index(keywords),
                     "windowH": round(window / 3600, 1)}
            request_log.append(entry)
            try:
                found, was_capped = search(recording_get, keywords, location, window, referer=referer)
                entry.update(status=200, cards=len(found))
                capped += was_capped
                blocks_in_a_row = 0
                referer = search_url(keywords, location, window)
                break
            except Blocked as b:
                resp = last_response.get("resp")
                entry.update(status=b.status, blocked=True, title=page_title(resp.text) if resp is not None else "")
                blocks += 1
                blocks_in_a_row += 1
                if blocks_in_a_row >= LI_MAX_BLOCKS_IN_A_ROW:
                    break
                step = LI_BLOCK_BACKOFF_SECONDS[min(blocks_in_a_row, len(LI_BLOCK_BACKOFF_SECONDS)) - 1]
                wait = min(b.wait or step, LI_MAX_BLOCK_WAIT_SECONDS)
                print(f"[li] blocked (HTTP {b.status}{', ' + entry['title'] if entry['title'] else ''}) on "
                      f"{location!r}, request {len(request_log)}; waiting {wait}s"
                      + (", then one retry" if attempt == 1 else ", then the next search"), file=sys.stderr)
                sleep(wait)
                waited += wait
            except Exception as e:  # noqa: BLE001 — one bad search must not kill the run
                entry.update(status=getattr(last_response.get("resp"), "status_code", 0), error=type(e).__name__)
                print(f"[li] {location!r} failed: {type(e).__name__}: {e}", file=sys.stderr)
                break
            finally:
                if "resp" in last_response:
                    entry["bytes"] = len(last_response["resp"].text or "")
        if found is not None:
            rows.extend(("li", r) for r in found)
            coverage[li_key(location, keywords)] = _iso_utc(started)
            done += 1
    # The last search can end on the block that reaches the limit, without the
    # loop's own check running again.
    stopped = stopped or blocks_in_a_row >= LI_MAX_BLOCKS_IN_A_ROW

    end = now()
    covered = [_epoch(coverage.get(li_key(*s))) for s in searches]
    stalest = max(((end - c) / 3600 if c else None) for c in covered) if all(covered) else None
    first_block = next((n for n, e in enumerate(request_log, 1) if e.get("blocked")), None)
    health = {
        "variant": variant,  # client (li_guest.open_session); None when injected
        "searches": len(searches), "done": done, "requests": requests_made, "blocked": blocks,
        "stoppedEarly": stopped, "rows": len(rows), "capped": capped,
        # Hours since the least recently completed search (None: some never completed).
        "stalestHours": round(stalest, 1) if stalest is not None else None,
        # Which request was the first refused, and how far into the run (tuning evidence).
        "firstBlockRequest": first_block,
        "firstBlockSecs": request_log[first_block - 1]["s"] if first_block else None,
        "minutes": round((end - run_started) / 60, 1),
    }
    print(f"[li] {variant or 'injected'} client: {done} of {len(searches)} searches done, "
          f"{requests_made} requests, {blocks} block(s)"
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



def main():
    debug = "--debug" in sys.argv
    forced_chunk = None
    if "--chunk" in sys.argv:
        forced_chunk = int(sys.argv[sys.argv.index("--chunk") + 1])
    # --priority / --no-priority force the priority sweep on or off, like --chunk.
    forced_priority = None
    if "--priority" in sys.argv:
        forced_priority = True
    elif "--no-priority" in sys.argv:
        forced_priority = False

    existing = load_snapshot(OUTPUT_PATH)
    rotating = rotating_combos()
    total_chunks = math.ceil(len(rotating) / COMBOS_PER_RUN)
    chunk_index, include_priority = next_rotation(
        existing.get("indeedRotation"), total_chunks, forced_chunk, forced_priority)
    this_chunk = rotating[chunk_index * COMBOS_PER_RUN: (chunk_index + 1) * COMBOS_PER_RUN]
    priority = priority_combos() if include_priority else []
    combos_this_run = this_chunk + priority

    print(
        f"[scrape] LI: {len(li_searches())} searches ({len(LOCATIONS)} markets x keyword groups), "
        f"every run. Indeed: rotating pool of {len(rotating)} combos ({len(SEARCH_TERMS)} terms x "
        f"{len(ROTATING_LOCATIONS)} rotating locations), {COMBOS_PER_RUN}/run -> {total_chunks} chunks, "
        f"one per run; priority pool {len(PRIORITY_LOCATIONS)} markets ({', '.join(PRIORITY_LOCATIONS)}) "
        f"x {len(SEARCH_TERMS)} terms, swept every other run."
    )
    print(f"[scrape] this run: Indeed chunk {chunk_index + 1}/{total_chunks} ({len(this_chunk)} combos)"
          + (f" + priority sweep ({len(priority)} combos)" if include_priority else " (priority sweep not due)")
          + f"; LI up to {LI_MAX_REQUESTS_PER_RUN} requests")

    index = build_index(COMPANIES, ALIASES)
    checked_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    # LI spends most of its ~40 min pausing between requests (human pace), so
    # it runs alongside Indeed rather than before it.
    with ThreadPoolExecutor(max_workers=1) as pool:
        li_job = pool.submit(run_li, existing.get("liCoverage"))
        indeed_rows, indeed_health = run_indeed_searches(combos_this_run, debug=debug)
        li_rows, coverage, li_health, li_log = li_job.result()
    rows = li_rows + indeed_rows
    print(f"[scrape] {len(rows)} raw results this run ({len(li_rows)} li, {len(indeed_rows)} indeed)")

    today_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    fresh_roles, fresh_open_market_roles = build_fresh_roles(rows, index, today_iso, debug=debug)
    # Roles only the Talent Hubs found (from before they moved to hb-scraper) are
    # left to hb-scraper's snapshot.
    snapshot = merge_and_prune(existing, fresh_roles, today_iso, fresh_open_market_roles=fresh_open_market_roles,
                               debug=debug, keep_sources={"li", "indeed", "bayt"})
    snapshot["liCoverage"] = coverage
    # Evidence for tuning the LI settings: this run's requests, and a summary
    # of the last LI_HISTORY_RUNS runs.
    snapshot["liLastRun"] = li_log
    history = existing.get("liHistory") if isinstance(existing.get("liHistory"), list) else []
    snapshot["liHistory"] = (history + [{"at": checked_at, **li_health}])[-LI_HISTORY_RUNS:]
    snapshot["indeedRotation"] = {"chunk": chunk_index, "priority": include_priority}
    run_gap = observed_run_gap_hours(snapshot["liHistory"])

    # What the app's "which markets" tooltip and source warnings show -- published
    # here so they can never drift from LOCATIONS / the rotation settings.
    snapshot["openMarket"].update({
        "searchedMarkets": list(SEARCHED_MARKETS),
        "searchTerms": list(SEARCH_TERMS),
        "priorityMarkets": [_canonical_market_name(loc) for loc in PRIORITY_LOCATIONS],
        # From the observed spacing between runs, not the 2 h schedule.
        "runEveryHours": round(run_gap, 1),
        "fullCycleHours": round(total_chunks * run_gap),
        "prioritySweepHours": round(2 * run_gap),
        # At best one request per search, LI_MAX_REQUESTS_PER_RUN per run.
        "liEveryHours": round(math.ceil(li_health["searches"] / LI_MAX_REQUESTS_PER_RUN) * run_gap),
        "sourceHealth": {
            "checkedAt": checked_at,
            "li": li_health,
            "indeed": indeed_health,
        },
    })

    open_market_count = len(snapshot["openMarket"]["roles"])
    if debug:
        print(f"\n[debug] {len(snapshot['companies'])} companies, "
              f"{sum(len(c['roles']) for c in snapshot['companies'].values())} roles total, "
              f"{open_market_count} open-market roles (all searched markets) — "
              f"not written to {OUTPUT_PATH} (--debug mode)", file=sys.stderr)
        return

    write_snapshot(OUTPUT_PATH, snapshot)
    total_roles = sum(len(c["roles"]) for c in snapshot["companies"].values())
    print(
        f"[scrape] wrote {OUTPUT_PATH}: {len(snapshot['companies'])} companies, {total_roles} roles, "
        f"{open_market_count} open-market roles"
    )


if __name__ == "__main__":
    main()
