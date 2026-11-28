import json
from pathlib import Path

COMPANIES_JSON = Path(__file__).resolve().parent.parent / "data" / "companies.json"

with COMPANIES_JSON.open(encoding="utf-8") as _f:
    _ALL = json.load(_f)["companies"]

COMPANIES = [
    {"name": (c.get("match") or {}).get("name") or c["name"], "slug": c["slug"],
     "exclude": (c.get("match") or {}).get("exclude") or []}
    for c in _ALL
]
ALIASES = {
    c["slug"]: list(c["match"]["aliases"])
    for c in _ALL
    if (c.get("match") or {}).get("aliases")
}
