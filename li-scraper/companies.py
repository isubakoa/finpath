"""Tracked companies for li-scraper, loaded from ../data/companies.json.

companies.json is ZenPath's single list of tracked companies -- the app
(index.php), this scraper and the validation test all read it. Don't add
companies here; edit companies.json. This module only reshapes it into the
two structures match.py already expects:

  COMPANIES  [{"name": ..., "slug": ...}]  -- `match.name` if set, else `name`
  ALIASES    {slug: [alias, ...]}          -- from each company's `match.aliases`

match.py normalizes each name (drops legal suffixes like "Group"/"Bank",
splits parenthetical alternate names into aliases, e.g. "Zepz (WorldRemit /
Sendwave)") before comparing it with a posting's employer name. If a real
posting isn't being matched, add the employer string it appears under to that
company's `match.aliases` in companies.json -- see README.md's "Fixing a missed
match" section. The reasoning behind non-obvious match names/aliases lives in
each company's `match.note`.
"""

import json
from pathlib import Path

COMPANIES_JSON = Path(__file__).resolve().parent.parent / "data" / "companies.json"

with COMPANIES_JSON.open(encoding="utf-8") as _f:
    _ALL = json.load(_f)["companies"]

COMPANIES = [
    {"name": (c.get("match") or {}).get("name") or c["name"], "slug": c["slug"]}
    for c in _ALL
]
ALIASES = {
    c["slug"]: list(c["match"]["aliases"])
    for c in _ALL
    if (c.get("match") or {}).get("aliases")
}
