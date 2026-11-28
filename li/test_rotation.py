from datetime import datetime, timedelta, timezone

from match import normalize_employer_name, role_identity
from roles import EXPIRY_DAYS, merge_and_prune
from scrape import (
    all_combos, rotating_combos, priority_combos, SEARCH_TERMS, LOCATIONS, PRIORITY_LOCATIONS,
    ROTATING_LOCATIONS, COMBOS_PER_RUN, SCHEDULE_INTERVAL_HOURS, next_rotation, observed_run_gap_hours,
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
    return {role_identity(key, title, location): (key, role)}


print("-- combo coverage --")
combos = all_combos()
check("total combo count", len(combos), len(SEARCH_TERMS) * len(LOCATIONS))
check("no duplicate combos", len(set(combos)), len(combos))

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
cycle_days = total_chunks * 8 / 24
print(f"  (info) {total_chunks} chunks x 8h = {cycle_days:.2f}-day full rotation cycle "
      f"for the {len(rotating)} rotating combos ({len(PRIORITY_LOCATIONS)} priority markets swept separately, "
      f"every other run, on top of each chunk)")
check("EXPIRY_DAYS comfortably exceeds 2x rotation cycle", EXPIRY_DAYS > 2 * cycle_days, True)

print("-- next_rotation (stateful, 2026-11-16) --")
state, seen, sweeps = None, [], []
for _ in range(total_chunks * 2):
    chunk, prio = next_rotation(state, total_chunks)
    seen.append(chunk); sweeps.append(prio)
    state = {"chunk": chunk, "priority": prio}
check("every run takes the next chunk, wrapping", seen, list(range(total_chunks)) * 2)
check("priority sweep alternates, starting with a sweep", sweeps, [True, False] * total_chunks)
check("unreadable state starts over", next_rotation({"chunk": "x"}, total_chunks), (0, True))
check("a chunk past the end (fewer chunks now) wraps", next_rotation({"chunk": total_chunks + 3, "priority": False}, total_chunks)[0], (total_chunks + 4) % total_chunks)
check("--chunk / --no-priority override", next_rotation({"chunk": 0, "priority": False}, total_chunks, 2, False), (2 % total_chunks, False))

print("-- observed_run_gap_hours --")
def hist(*hours_apart):
    t = datetime(2026, 11, 1, tzinfo=timezone.utc); out = [{"at": t.strftime("%Y-%m-%dT%H:%M:%SZ")}]
    for h in hours_apart:
        t += timedelta(hours=h); out.append({"at": t.strftime("%Y-%m-%dT%H:%M:%SZ")})
    return out
check("median of the gaps", observed_run_gap_hours(hist(4, 6, 9)), 6)
check("even count: mean of the middle two", observed_run_gap_hours(hist(4, 5, 7, 9)), 6)
check("fewer than 3 gaps: the schedule", observed_run_gap_hours(hist(6, 6)), float(SCHEDULE_INTERVAL_HOURS))
check("bad timestamps skipped", observed_run_gap_hours(hist(5, 6, 7) + [{"at": "nope"}, {}]), 6)

print("-- merge_and_prune --")
today = days_ago(0)

existing = {"companies": {}}
fresh = fresh_entry("acme", "Director of Product Design", "Singapore", {
    "title": "Director of Product Design", "location": "Singapore", "url": "https://li.com/jobs/1",
    "postedDate": today, "source": "li", "lastSeenAt": today,
})
snap = merge_and_prune(existing, fresh, today)
check("Case 1: role present", len(snap["companies"].get("acme", {}).get("roles", [])), 1)

existing = {"companies": {"acme": {"roles": [
    {"title": "Head of Design", "location": "London", "url": "https://li.com/jobs/OLD",
     "postedDate": days_ago(3), "source": "li", "lastSeenAt": days_ago(3)},
]}}}
fresh = {}
snap = merge_and_prune(existing, fresh, today)
check("Case 2: untouched-this-run role carried over", len(snap["companies"]["acme"]["roles"]), 1)
check("Case 2: lastSeenAt unchanged (not falsely refreshed)", snap["companies"]["acme"]["roles"][0]["lastSeenAt"], days_ago(3))

existing = {"companies": {"acme": {"roles": [
    {"title": "Head of Design", "location": "London", "url": "https://li.com/jobs/STALE",
     "postedDate": days_ago(EXPIRY_DAYS + 1), "source": "li", "lastSeenAt": days_ago(EXPIRY_DAYS + 1)},
]}}}
snap = merge_and_prune(existing, {}, today)
check("Case 3: expired role pruned", snap["companies"].get("acme", {}).get("roles", []), [])

existing = {"companies": {"acme": {"roles": [
    {"title": "Head of Design", "location": "London", "url": "https://li.com/jobs/FRESHISH",
     "postedDate": days_ago(EXPIRY_DAYS - 1), "source": "li", "lastSeenAt": days_ago(EXPIRY_DAYS - 1)},
]}}}
snap = merge_and_prune(existing, {}, today)
check("Case 4: not-yet-expired role survives", len(snap["companies"]["acme"]["roles"]), 1)

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
