import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "li"))

from companies import ALIASES, COMPANIES
from match import build_index
from registry import HUB_IDS, hubs_off, run_talent_hubs
from roles import (EXTRA_MARKETS, SEARCH_TERMS, build_fresh_roles, load_snapshot, merge_and_prune,
                   result_urls, set_hub_order, write_snapshot)

OUTPUT_PATH = os.path.normpath(os.path.join(HERE, "..", "data", "hb-snapshot.json"))
SCHEDULE_INTERVAL_HOURS = 2

set_hub_order(HUB_IDS)


def main():
    debug = "--debug" in sys.argv
    checked_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    existing = load_snapshot(OUTPUT_PATH)
    off = hubs_off()
    print(f"[hb-scrape] {len(HUB_IDS) - len(off)} of {len(HUB_IDS)} hubs on" + (f" (off: {', '.join(sorted(off))})" if off else ""))

    rows, report = run_talent_hubs(SEARCH_TERMS, off=off, debug=debug)
    counts = {}
    for source, _ in rows:
        counts[source] = counts.get(source, 0) + 1
    print(f"[hb-scrape] {len(rows)} raw results (" + ", ".join(f"{counts.get(h, 0)} {h}" for h in HUB_IDS) + ")")

    today_iso = checked_at[:10]
    fresh_roles, fresh_open_market_roles = build_fresh_roles(rows, build_index(COMPANIES, ALIASES), today_iso, debug=debug)
    snapshot = merge_and_prune(existing, fresh_roles, today_iso, fresh_open_market_roles=fresh_open_market_roles,
                               debug=debug, keep_sources=set(HUB_IDS), seen_urls=result_urls(rows))
    snapshot["checkedAt"] = checked_at
    snapshot["openMarket"].update({"talentHubs": report, "hubOnlyMarkets": list(EXTRA_MARKETS)})

    tracked = sum(len(c["roles"]) for c in snapshot["companies"].values())
    summary = f"{len(snapshot['companies'])} companies, {tracked} roles, {len(snapshot['openMarket']['roles'])} open-market roles"
    if debug:
        print(f"[debug] {summary} — not written (--debug mode)", file=sys.stderr)
        return
    write_snapshot(OUTPUT_PATH, snapshot)
    print(f"[hb-scrape] wrote {OUTPUT_PATH}: {summary}")


if __name__ == "__main__":
    main()
