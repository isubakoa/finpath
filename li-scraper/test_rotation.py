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
"""

from datetime import datetime, timedelta, timezone

from scrape import all_combos, merge_and_prune, SEARCH_TERMS, LOCATIONS, COMBOS_PER_RUN, EXPIRY_DAYS, SCHEDULE_INTERVAL_HOURS

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
fresh = {"https://li.com/jobs/1": ("acme", {
    "title": "Director of Product Design", "location": "Singapore", "url": "https://li.com/jobs/1",
    "postedDate": today, "source": "li", "lastSeenAt": today,
})}
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
existing = {"companies": {"acme": {"roles": [
    {"title": "Head of Design", "location": "London", "url": "https://li.com/jobs/REFRESH",
     "postedDate": days_ago(10), "source": "li", "lastSeenAt": days_ago(10)},
]}}}
fresh = {"https://li.com/jobs/REFRESH": ("acme", {
    "title": "Head of Design", "location": "London", "url": "https://li.com/jobs/REFRESH",
    "postedDate": days_ago(10), "source": "li", "lastSeenAt": today,
})}
snap = merge_and_prune(existing, fresh, today)
check("Case 5: re-found role's lastSeenAt refreshed", snap["companies"]["acme"]["roles"][0]["lastSeenAt"], today)

# Case 6: roles across multiple companies, mixed fresh/carried/expired, all resolve independently.
existing = {"companies": {
    "acme": {"roles": [{"title": "X", "location": "L", "url": "https://x.com/1", "postedDate": today, "source": "li", "lastSeenAt": days_ago(2)}]},
    "beta": {"roles": [{"title": "Y", "location": "L", "url": "https://x.com/2", "postedDate": today, "source": "li", "lastSeenAt": days_ago(EXPIRY_DAYS + 5)}]},
}}
fresh = {"https://x.com/3": ("gamma", {"title": "Z", "location": "L", "url": "https://x.com/3", "postedDate": today, "source": "li", "lastSeenAt": today})}
snap = merge_and_prune(existing, fresh, today)
check("Case 6: acme carried over", "acme" in snap["companies"], True)
check("Case 6: beta expired away entirely", "beta" in snap["companies"], False)
check("Case 6: gamma added fresh", "gamma" in snap["companies"], True)

print(f"\n{'ALL PASSED' if failures == 0 else f'{failures} FAILED'}")
if failures:
    raise SystemExit(1)
