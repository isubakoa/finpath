"""
Offline sanity checks for scrape.py's rotation/accumulation logic — no
network, no JobSpy dependency. Run with `python3 test_rotation.py`.

This is the part of the September 2026 scope increase that most needs its
own verification: with 38 title terms x 25 locations = 950 combinations,
each searched against both LI and Indeed, no single run can cover them
all (see scrape.py's module docstring), so results have to accumulate
across runs and expire old entries instead of being overwritten wholesale
each time. These tests check that merge logic in isolation — it's agnostic
to which site a role's `source` says it came from — since the real thing
can't be run against live LI/Indeed data in this environment (see
README.md's "Not yet live-tested" note).

ZENPATH Phase 4 — every `fresh`/`fresh_open_market` dict below was rewritten
to key on role_identity(slug_or_employer_key, title, location), matching how
build_fresh_roles() actually keys them in production since Phase 1.4 (see
scrape.py's module docstring and merge_and_prune()'s own docstring). Before
this fix, every case here keyed its synthetic `fresh` dicts by job URL
instead — a leftover from before 1.4 introduced identity-based (not
URL-based) deduping. Most cases still happened to pass anyway (nothing in
them ever needed the fresh-role key to actually MATCH an existing one — see
Cases 1/3/4/6, which either have no prior entry to match against or no
fresh entry to match with), which is exactly how this went unnoticed: Case
5 was the only one actually exercising "does a fresh role get correctly
recognized as the SAME role as an existing one," and it was failing on
every run. Since `_merge_identity_roles()` computes each EXISTING role's
identity internally but takes each FRESH role's identity directly from its
dict key (matching build_fresh_roles()'s real contract — see
merge_and_prune()'s docstring), a URL-keyed fresh dict here could never
match anything, silently. Because this file's exit code gates the
"Run scraper"/"Commit updated snapshot" steps in
.github/workflows/scrape-li.yml, this one failing case meant the scheduled
workflow was failing at this step on every run — never reaching the scraper
at all — since whichever push first drifted this file out of sync with the
real keying scheme.
"""

from datetime import datetime, timedelta, timezone

from scrape import (
    all_combos, merge_and_prune, role_identity, normalize_employer_name,
    SEARCH_TERMS, LOCATIONS, COMBOS_PER_RUN, EXPIRY_DAYS, SCHEDULE_INTERVAL_HOURS,
)

failures = 0


def check(label, actual, expected):
    global failures
    ok = actual == expected
    failures += 0 if ok else 1
    print(f"  {'OK ' if ok else 'FAIL'}  {label}")
    if not ok:
        print(f"    actual:   {actual!r}\n    expected: {expected!r}")


def days_ago(n):
    return (datetime.now(timezone.utc) - timedelta(days=n)).strftime("%Y-%m-%d")


def fresh_entry(key, title, location, role):
    """Builds one {identity: (key, role)} entry the same way
    build_fresh_roles() does in production — identity is role_identity(key,
    title, location), not the role's job_url. See this file's own module
    docstring for why that distinction is exactly what Case 5 below is
    checking."""
    return {role_identity(key, title, location): (key, role)}


print("-- combo coverage --")
combos = all_combos()
check("total combo count", len(combos), len(SEARCH_TERMS) * len(LOCATIONS))
check("no duplicate combos", len(set(combos)), len(combos))
import math
total_chunks = math.ceil(len(combos) / COMBOS_PER_RUN)
cycle_days = total_chunks * SCHEDULE_INTERVAL_HOURS / 24
print(f"  (info) {total_chunks} chunks x {SCHEDULE_INTERVAL_HOURS}h = {cycle_days:.2f}-day full rotation cycle")
check("EXPIRY_DAYS comfortably exceeds 2x rotation cycle", EXPIRY_DAYS > 2 * cycle_days, True)

print("-- merge_and_prune --")
today = days_ago(0)

# Case 1: fresh snapshot (no prior file) — fresh roles just get written.
existing = {"companies": {}}
fresh = fresh_entry("acme", "Director of Product Design", "Singapore", {
    "title": "Director of Product Design", "location": "Singapore", "url": "https://li.com/jobs/1",
    "postedDate": today, "source": "li", "lastSeenAt": today,
})
snap = merge_and_prune(existing, fresh, today)
check("Case 1: role present", len(snap["companies"].get("acme", {}).get("roles", [])), 1)

# Case 2: a role from a PRIOR run (different combo, not re-queried this run) survives —
# this is the core "don't lose coverage between rotation chunks" behavior.
existing = {"companies": {"acme": {"roles": [
    {"title": "Head of Design", "location": "London", "url": "https://li.com/jobs/OLD",
     "postedDate": days_ago(3), "source": "li", "lastSeenAt": days_ago(3)},
]}}}
fresh = {}  # this run's chunk didn't touch acme's terms/location at all
snap = merge_and_prune(existing, fresh, today)
check("Case 2: untouched-this-run role carried over", len(snap["companies"]["acme"]["roles"]), 1)
check("Case 2: lastSeenAt unchanged (not falsely refreshed)", snap["companies"]["acme"]["roles"][0]["lastSeenAt"], days_ago(3))

# Case 3: a role last seen just past EXPIRY_DAYS ago, not re-found this run — pruned.
existing = {"companies": {"acme": {"roles": [
    {"title": "Head of Design", "location": "London", "url": "https://li.com/jobs/STALE",
     "postedDate": days_ago(EXPIRY_DAYS + 1), "source": "li", "lastSeenAt": days_ago(EXPIRY_DAYS + 1)},
]}}}
snap = merge_and_prune(existing, {}, today)
check("Case 3: expired role pruned", snap["companies"].get("acme", {}).get("roles", []), [])

# Case 4: a role just inside the expiry window survives.
existing = {"companies": {"acme": {"roles": [
    {"title": "Head of Design", "location": "London", "url": "https://li.com/jobs/FRESHISH",
     "postedDate": days_ago(EXPIRY_DAYS - 1), "source": "li", "lastSeenAt": days_ago(EXPIRY_DAYS - 1)},
]}}}
snap = merge_and_prune(existing, {}, today)
check("Case 4: not-yet-expired role survives", len(snap["companies"]["acme"]["roles"]), 1)

# Case 5: a role re-found this run gets its lastSeenAt refreshed (resets its expiry clock).
# This is the case that was silently broken — see module docstring.
existing = {"companies": {"acme": {"roles": [
    {"title": "Head of Design", "location": "London", "url": "https://li.com/jobs/REFRESH",
     "postedDate": days_ago(10), "source": "li", "lastSeenAt": days_ago(10)},
]}}}
fresh = fresh_entry("acme", "Head of Design", "London", {
    "title": "Head of Design", "location": "London", "url": "https://li.com/jobs/REFRESH",
    "postedDate": days_ago(10), "source": "li", "lastSeenAt": today,
})
snap = merge_and_prune(existing, fresh, today)
check("Case 5: re-found role's lastSeenAt refreshed", len(snap["companies"]["acme"]["roles"]), 1)
check("Case 5: re-found role's lastSeenAt refreshed (value)", snap["companies"]["acme"]["roles"][0]["lastSeenAt"], today)

# Case 6: roles across multiple companies, mixed fresh/carried/expired, all resolve independently.
existing = {"companies": {
    "acme": {"roles": [{"title": "X", "location": "L", "url": "https://x.com/1", "postedDate": today, "source": "li", "lastSeenAt": days_ago(2)}]},
    "beta": {"roles": [{"title": "Y", "location": "L", "url": "https://x.com/2", "postedDate": today, "source": "li", "lastSeenAt": days_ago(EXPIRY_DAYS + 5)}]},
}}
fresh = fresh_entry("gamma", "Z", "L", {"title": "Z", "location": "L", "url": "https://x.com/3", "postedDate": today, "source": "li", "lastSeenAt": today})
snap = merge_and_prune(existing, fresh, today)
check("Case 6: acme carried over", "acme" in snap["companies"], True)
check("Case 6: beta expired away entirely", "beta" in snap["companies"], False)
check("Case 6: gamma added fresh", "gamma" in snap["companies"], True)

print("-- merge_and_prune: openMarket branch (Phase 2.5) --")
# Case 7: same identity-refresh behavior as Case 5, but on the open-market side —
# fresh_open_market_roles is keyed by normalize_employer_name(employer), not a slug
# (see merge_and_prune()'s own docstring), and this parameter was entirely untested
# in this file before Phase 4 (test_match.py covers it more exhaustively — this is
# just confirming the rotation-across-runs behavior applies identically here too).
existing = {"companies": {}, "openMarket": {"roles": [
    {"employer": "Example Fintech", "market": "Singapore", "title": "Director of Product Design",
     "location": "Singapore", "url": "https://li.com/jobs/OM1", "postedDate": days_ago(10),
     "source": "li", "sources": ["li"], "lastSeenAt": days_ago(10)},
]}}
fresh_om = fresh_entry(normalize_employer_name("Example Fintech"), "Director of Product Design", "Singapore", {
    "employer": "Example Fintech", "market": "Singapore", "title": "Director of Product Design",
    "location": "Singapore", "url": "https://li.com/jobs/OM1", "postedDate": days_ago(10),
    "source": "li", "sources": ["li"], "lastSeenAt": today,
})
snap = merge_and_prune(existing, {}, today, fresh_open_market_roles=fresh_om)
check("Case 7: open-market role count unchanged (matched, not duplicated)", len(snap["openMarket"]["roles"]), 1)
check("Case 7: open-market role's lastSeenAt refreshed", snap["openMarket"]["roles"][0]["lastSeenAt"], today)

print(f"\n{'ALL PASSED' if failures == 0 else f'{failures} FAILED'}")
if failures:
    raise SystemExit(1)
