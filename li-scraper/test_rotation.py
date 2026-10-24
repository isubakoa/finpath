"""
Offline checks for scrape.py's rotation and accumulation: chunks cover the grid
exactly, results merge across runs instead of being overwritten, and roles
expire after EXPIRY_DAYS. No network, no JobSpy. Run: python3 test_rotation.py

Fresh-role dicts are keyed by role_identity(key, title, location), exactly as
build_fresh_roles() keys them; keying them by URL instead makes every
"same role seen again" case silently fail to match (Case 5 guards this).
This file gates the scraper in CI, so a failure here stops the scheduled run.
"""

from datetime import datetime, timedelta, timezone

from scrape import (
    all_combos, rotating_combos, priority_combos, merge_and_prune, role_identity,
    normalize_employer_name, SEARCH_TERMS, LOCATIONS, PRIORITY_LOCATIONS,
    ROTATING_LOCATIONS, COMBOS_PER_RUN, EXPIRY_DAYS, SCHEDULE_INTERVAL_HOURS,
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
    """One {identity: (key, role)} entry, keyed the way build_fresh_roles() keys
        them (role_identity, not job_url) -- see the module docstring.
    """
    return {role_identity(key, title, location): (key, role)}


print("-- combo coverage --")
combos = all_combos()
check("total combo count", len(combos), len(SEARCH_TERMS) * len(LOCATIONS))
check("no duplicate combos", len(set(combos)), len(combos))

# PRIORITY_LOCATIONS get their own sweep; COMBOS_PER_RUN chunks only the
# rotating pool. Check the two pools partition the grid exactly and the cycle
# math uses the smaller pool.
rotating = rotating_combos()
priority = priority_combos()
check("rotating combo count", len(rotating), len(SEARCH_TERMS) * len(ROTATING_LOCATIONS))
check("priority combo count", len(priority), len(SEARCH_TERMS) * len(PRIORITY_LOCATIONS))
check("rotating + priority combos partition all_combos() exactly (same multiset, no gaps/overlap)",
      sorted(rotating + priority), sorted(combos))
check("rotating and priority combo sets are disjoint",
      set(rotating) & set(priority), set())

import math
total_chunks = math.ceil(len(rotating) / COMBOS_PER_RUN)
cycle_days = total_chunks * SCHEDULE_INTERVAL_HOURS / 24
print(f"  (info) {total_chunks} chunks x {SCHEDULE_INTERVAL_HOURS}h = {cycle_days:.2f}-day full rotation cycle "
      f"for the {len(rotating)} rotating combos ({len(PRIORITY_LOCATIONS)} priority markets swept separately, "
      f"every other run, on top of each chunk)")
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
# Case 7: same refresh-on-re-seen behaviour as Case 5, on the open-market side
# (keyed by normalize_employer_name(employer) instead of a slug).
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
