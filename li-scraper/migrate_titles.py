"""
PHASE 1.5 MIGRATION — ONE-TIME. Re-normalizes every role already accumulated
in li-snapshot.json using the same normalize_scraped_title() rules
build_fresh_roles() now applies to newly-scraped results (CTA-suffix
stripping, trailing-location recovery, whitespace collapse), and replaces
any literal "Not specified" location (the old placeholder, written by every
run before this phase shipped) with "" — index.html's existing
isUnknownLocation()/locationLabel() already render "" as an em dash, so no
placeholder string is needed going forward.

Without this, only *newly scraped* roles get the cleaned-up text; anything
carried over from before 1.5 (via merge_and_prune()'s EXPIRY_DAYS=14
lifecycle, so potentially sitting in the snapshot for up to two weeks) would
keep its old "Not specified"/un-normalized title until it happens to be
re-confirmed by a later run. This closes that gap immediately instead of
waiting on it.

Idempotent — safe to run more than once (a role whose title/location is
already normalized is simply left unchanged, not "changed" a second time).

Usage (run once, from li-scraper/, against a checkout that has the real
li-snapshot.json — this repo's own git history/CI, not this script, is
responsible for actually running it once against the live file and
committing the result):
    cd li-scraper && python3 migrate_titles.py
    cd li-scraper && python3 migrate_titles.py --dry-run   # report only, no write
"""

import json
import sys

from match import normalize_scraped_title
from scrape import OUTPUT_PATH


def migrate(path=OUTPUT_PATH, dry_run=False):
    with open(path) as f:
        data = json.load(f)

    changed = 0
    examples = []
    for slug, entry in data.get("companies", {}).items():
        for role in entry.get("roles", []):
            old_title = role.get("title", "")
            old_location = role.get("location", "")
            # The old placeholder — treat it the same as "no location" so
            # normalize_scraped_title() can still attempt trailing-location
            # recovery from the title text, same as a freshly-scraped empty
            # location would get.
            loc_for_norm = "" if old_location == "Not specified" else old_location
            new_title, new_location = normalize_scraped_title(old_title, loc_for_norm)
            if new_title != old_title or new_location != old_location:
                changed += 1
                if len(examples) < 10:
                    examples.append((slug, old_title, old_location, new_title, new_location))
                if not dry_run:
                    role["title"] = new_title
                    role["location"] = new_location

    print(f"[migrate] {'would update' if dry_run else 'updated'} {changed} role(s)")
    for slug, ot, ol, nt, nl in examples:
        print(f"  [{slug}] {ot!r} @ {ol!r}  ->  {nt!r} @ {nl!r}")
    if changed > len(examples):
        print(f"  ... and {changed - len(examples)} more")

    if not dry_run and changed:
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        print(f"[migrate] wrote {path}")


if __name__ == "__main__":
    migrate(dry_run="--dry-run" in sys.argv)
