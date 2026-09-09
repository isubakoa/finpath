"""
FinPath — LI + Indeed coverage via JobSpy (github.com/speedyapply/JobSpy)

Runs keyword searches against LI and Indeed (your trimmed Product +
Design/UX title list, across your target-region list — see
SEARCH_TERMS/LOCATIONS below), keeps only the results that are (a) from one
of the 179 tracked companies — matched by name, see match.py — and (b) pass
the exact same isRoleRelevant() title filter index.html itself applies.
Writes the result to li-snapshot.json in the same
`{ companies: { <slug>: { roles: [...] } } }` shape check.php already
expects from js-scraper's snapshot.json — each role carries its own
`source` ("li" or "indeed") so the frontend can badge it correctly.

*** IMPORTANT — READ THIS BEFORE CHANGING TERMS/LOCATIONS/SCHEDULE ***
38 title phrases x 25 locations = 950 (term, location) combinations
(trimmed down from the original 108 x 17 = 1,836 in September 2026 for
freshness/footprint — see README.md's "How the rotation works" for the
before/after). Each combination is searched against LI AND Indeed —
added September 2026, see README.md's "Indeed coverage" section — as two
independent requests (Indeed has no rate limiting per JobSpy's own docs, so
only the LI side needs the randomized pacing pause). There is still no
way to run all 950 combinations in a single pass without either proxies or
getting blocked on the LI side almost immediately — see
li-scraper/README.md's "How the rotation works" section for the full
explanation. Instead, each run covers one CHUNK of the full combination
list (COMBOS_PER_RUN of them), chosen deterministically from the current
time so consecutive scheduled runs walk through the whole list in order and
wrap back around — a full cycle takes ROTATION_CYCLE_HOURS (printed below)
to complete, unchanged by the addition of Indeed since chunk count is driven
by combinations, not requests. Results accumulate into li-snapshot.json
across runs (merged, not overwritten) and a role is only dropped after
EXPIRY_DAYS without being re-confirmed — so a company found on Monday
doesn't vanish from the tracker on Tuesday just because today's chunk
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

from companies import COMPANIES, ALIASES
from match import build_index, match_company, is_role_relevant, fit_tier

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

RESULTS_WANTED_PER_SEARCH = 20
HOURS_OLD = 240  # 10 days — comfortably wider than one rotation cycle (see below),
                 # so a role posted right after its combo's turn is still visible
                 # the next time that combo comes up.

# Polite, but randomized rather than a flat delay — September 2026, paired
# with the move to hourly runs (below): a perfectly uniform 8.0s gap between
# every single request, run after run, is a very identifiable non-human
# pattern; a random point in a tight range costs nothing in total run time
# (same ~6-8 minutes either way) but doesn't look mechanically scripted.
PAUSE_BETWEEN_SEARCHES_SECONDS_MIN = 5
PAUSE_BETWEEN_SEARCHES_SECONDS_MAX = 11

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
    combinations — source is "li" or "indeed", row is a raw JobSpy result
    (dict-like). Imports jobspy lazily so match.py/test_match.py can be
    exercised without the dependency installed.

    LI and Indeed are run as two independent scrape_jobs() calls per
    combo, each in its own try/except, rather than one combined
    site_name=["linkedin","indeed"] call — deliberately, so an Indeed-side
    failure (an unsupported country_indeed value, a transient error) can
    never take LI's result for that same combo down with it, and vice
    versa. Only LI gets the randomized pacing pause: Indeed has no
    rate limiting per JobSpy's own docs, so there's nothing to be polite
    about pacing around on that side."""
    from jobspy import scrape_jobs

    for term, location in combos:
        if debug:
            print(f"[scrape] searching (li): {term!r} @ {location!r}", file=sys.stderr)
        try:
            df = scrape_jobs(
                site_name=["linkedin"],
                search_term=term,
                location=location,
                results_wanted=RESULTS_WANTED_PER_SEARCH,
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
            continue  # shouldn't happen — every LOCATIONS entry has a mapping — but skip cleanly if it ever doesn't
        indeed_location = INDEED_LOCATION_OVERRIDE.get(location, location)
        if debug:
            print(f"[scrape] searching (indeed): {term!r} @ {indeed_location!r} ({indeed_country})", file=sys.stderr)
        try:
            df2 = scrape_jobs(
                site_name=["indeed"],
                search_term=term,
                location=indeed_location,
                country_indeed=indeed_country,
                results_wanted=RESULTS_WANTED_PER_SEARCH,
                hours_old=HOURS_OLD,
                verbose=1 if debug else 0,
            )
        except Exception as e:  # noqa: BLE001 — same isolation as the LI call above
            print(f"[scrape] indeed search failed ({term!r} @ {indeed_location!r}): {e}", file=sys.stderr)
            df2 = None
        if df2 is not None and len(df2):
            for row in df2.to_dict(orient="records"):
                yield ("indeed", row)


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


def build_fresh_roles(rows, index, today_iso, debug=False):
    """Filters this run's raw results down to real matches, keyed by URL.
    rows: iterable of (source, row) — source is "li" or "indeed", tagged
    onto the kept role so the frontend badge shows which site actually
    found it."""
    fresh = {}  # url -> (slug, role dict)
    kept = dropped_company = dropped_title = duplicate = 0

    for source, row in rows:
        url = row.get("job_url") or ""
        if not url or url in fresh:
            duplicate += 1
            continue

        employer = row.get("company") or ""
        slug = match_company(employer, index)
        if not slug:
            dropped_company += 1
            if debug:
                print(f"[match] no company match: {employer!r} — {row.get('title')!r}", file=sys.stderr)
            continue

        title = row.get("title") or ""
        if not is_role_relevant(title):
            dropped_title += 1
            if debug:
                print(f"[match] title filtered out: {title!r} @ {employer!r}", file=sys.stderr)
            continue

        kept += 1
        fresh[url] = (slug, {
            "title": title,
            "location": row.get("location") or "Not specified",
            "url": url,
            "postedDate": normalize_posted_date(row.get("date_posted")),
            "source": source,
            "lastSeenAt": today_iso,
        })

    if debug:
        print(
            f"[match] kept={kept} dropped_no_company_match={dropped_company} "
            f"dropped_title_filter={dropped_title} duplicates={duplicate}",
            file=sys.stderr,
        )
    return fresh


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


def merge_and_prune(existing, fresh_roles, today_iso, debug=False):
    """existing: the snapshot loaded from disk (accumulated from prior runs).
    fresh_roles: {url: (slug, role)} found THIS run. Returns the merged,
    pruned snapshot: fresh roles upsert (refreshing lastSeenAt), everything
    else carries over unless it's past EXPIRY_DAYS since its own
    lastSeenAt."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=EXPIRY_DAYS)).strftime("%Y-%m-%d")

    # Flatten existing into the same {url: (slug, role)} shape to merge simply.
    merged = {}
    for slug, entry in existing.get("companies", {}).items():
        for role in entry.get("roles", []):
            url = role.get("url")
            if url:
                merged[url] = (slug, role)

    carried_over = expired = updated = added = 0
    for url, (slug, role) in fresh_roles.items():
        if url in merged:
            updated += 1
        else:
            added += 1
        merged[url] = (slug, role)

    companies_out = {}
    for url, (slug, role) in merged.items():
        if url in fresh_roles:
            companies_out.setdefault(slug, {"roles": []})["roles"].append(role)
            continue
        last_seen = role.get("lastSeenAt") or "1970-01-01"
        if last_seen < cutoff:
            expired += 1
            continue
        carried_over += 1
        companies_out.setdefault(slug, {"roles": []})["roles"].append(role)

    if debug:
        print(
            f"[merge] added={added} updated={updated} carried_over={carried_over} "
            f"expired_pruned={expired} (cutoff {cutoff})",
            file=sys.stderr,
        )

    return {
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "companies": companies_out,
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
    print(
        f"[scrape] {len(combos)} total combos ({len(SEARCH_TERMS)} terms x {len(LOCATIONS)} locations), "
        f"{COMBOS_PER_RUN}/run -> {total_chunks} chunks -> full cycle ~{cycle_hours}h (~{cycle_hours / 24:.1f} days)"
    )
    print(f"[scrape] this run: chunk {chunk_index + 1}/{total_chunks} "
          f"({len(this_chunk)} combos x 2 sites = up to {len(this_chunk) * 2} requests)")

    index = build_index(COMPANIES, ALIASES)
    rows = list(run_searches(this_chunk, debug=debug))
    li_count = sum(1 for source, _ in rows if source == "li")
    indeed_count = sum(1 for source, _ in rows if source == "indeed")
    print(f"[scrape] {len(rows)} raw results this run ({li_count} li, {indeed_count} indeed)")

    today_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    fresh_roles = build_fresh_roles(rows, index, today_iso, debug=debug)
    existing = load_existing_snapshot()
    snapshot = merge_and_prune(existing, fresh_roles, today_iso, debug=debug)

    if debug:
        print(f"\n[debug] {len(snapshot['companies'])} companies, "
              f"{sum(len(c['roles']) for c in snapshot['companies'].values())} roles total — "
              f"not written to {OUTPUT_PATH} (--debug mode)", file=sys.stderr)
        return

    with open(OUTPUT_PATH, "w") as f:
        json.dump(snapshot, f, indent=2)
        f.write("\n")
    total_roles = sum(len(c["roles"]) for c in snapshot["companies"].values())
    print(f"[scrape] wrote {OUTPUT_PATH}: {len(snapshot['companies'])} companies, {total_roles} roles")


if __name__ == "__main__":
    main()
