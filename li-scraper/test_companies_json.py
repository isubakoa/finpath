"""Guards companies.json, ZenPath's single list of tracked companies.

the app (index.php + app.js), li-scraper and js-scraper all depend on this file, and
a bad entry fails quietly in the app (a company that's never checked, a
drawer that won't open), so this test fails loudly instead -- in CI before the
scraper runs, or locally:  python test_companies_json.py

Checks: required fields and types, unique slugs/names, allowed enum values,
each ats.type's required config keys, html linkPatterns that compile, the
optional `match` block's shape, unique openRoles ids, and that every
`snapshot`-type company has a js-scraper/scrape.js entry (and vice versa).

What it can't check: whether check.php (FTP-only, not in this repo) supports
an ats.type. That list lives in check.php's buildRequest() and app.js's
LIVE_CHECK_ATS -- keep those two in step by hand. Unknown types below are
reported here as a reminder, not silently accepted.
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMPANIES_JSON = ROOT / "data" / "companies.json"
SCRAPE_JS = ROOT / "js-scraper" / "scrape.js"

REQUIRED = {
    "region": str, "name": str, "slug": str, "category": str, "hq": str,
    "founded": int, "asia": str, "asiaNote": str, "sponsorship": str,
    "sponsorshipNote": str, "note": str, "url": str, "openStatus": str,
    "openRoles": list, "openNote": str, "ats": dict,
}
ENUMS = {
    "asia": {"strong", "some", "limited"},
    "sponsorship": {"likely", "uncertain"},
    "openStatus": {"match", "below-target", "none", "uncertain"},
}
# Config keys check.php needs for each ats.type. Types that aren't checked
# live ("unknown", "other") only need a type.
ATS_REQUIRED = {
    "greenhouse": {"slug"}, "lever": {"slug"}, "ashby": {"slug"},
    "smartrecruiters": {"slug"}, "workable": {"slug"}, "pinpoint": {"slug"},
    "bamboohr": {"slug"}, "workday": {"slug", "wdNum"},
    "oraclecloud": {"host", "site"}, "html": {"url", "linkPattern"},
    "hibob": {"host"}, "eightfold": {"host", "domain"}, "revolutpeople": {"slug"}, "phenom": {"url"},
    "taleo": {"host", "section", "portal"}, "mokahr": {"orgId", "siteId"}, "jibe": {"host", "locations"}, "brassring": {"host", "partnerId", "siteId"},
    "snapshot": {"slug"},
    "unknown": set(), "other": set(),
    # one-off, company-specific adapters in check.php
    "nordea": set(), "dassault": set(), "amazon": set(),
    "telekom": set(), "microsoft": set(), "emirates": set(), "line": set(),
    "bt": set(), "fujitsu": set(), "capgemini": set(), "klm": set(),
    "lufthansa": set(), "tiktok": set(), "antgroup": {"bgCode", "nameMatch"},
    "dynatrace": set(), "ibm": set(), "mercedes": set(), "personio": set(),
}
ROLE_REQUIRED = {"id", "title", "url"}
MATCH_KEYS = {"name", "aliases", "note"}
SLUG_RE = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")


def check():
    errors = []
    err = errors.append

    data = json.loads(COMPANIES_JSON.read_text(encoding="utf-8"))
    companies = data.get("companies")
    if not isinstance(companies, list) or not companies:
        return ["companies.json has no non-empty top-level \"companies\" list"]

    for i, c in enumerate(companies):
        where = f"#{i} {c.get('slug', '?')}"
        for key, typ in REQUIRED.items():
            if key not in c:
                err(f"{where}: missing '{key}'")
            elif not isinstance(c[key], typ) or (typ is int and isinstance(c[key], bool)):
                err(f"{where}: '{key}' should be {typ.__name__}")
        extra = set(c) - set(REQUIRED) - {"match"}
        if extra:
            err(f"{where}: unexpected field(s) {sorted(extra)}")
        if isinstance(c.get("slug"), str) and not SLUG_RE.fullmatch(c["slug"]):
            err(f"{where}: slug must be lowercase-kebab-case")
        for key, allowed in ENUMS.items():
            if key in c and c[key] not in allowed:
                err(f"{where}: {key}={c[key]!r} not one of {sorted(allowed)}")

        ats = c.get("ats") or {}
        t = ats.get("type")
        if t not in ATS_REQUIRED:
            err(f"{where}: ats.type {t!r} isn't known -- if check.php supports it, add it to "
                f"ATS_REQUIRED here AND to app.js's LIVE_CHECK_ATS")
        else:
            missing = {k for k in ATS_REQUIRED[t] if not ats.get(k)}
            if missing:
                err(f"{where}: ats.type {t!r} needs {sorted(missing)}")
        if t == "oraclecloud" and "queries" in ats:
            q = ats["queries"]
            if not (isinstance(q, list) and q and all(isinstance(x, dict) and (x.get("facet") or x.get("keyword")) for x in q)):
                err(f"{where}: ats.queries must be a non-empty list of {{facet, keyword}} objects")
        if t == "html" and ats.get("linkPattern"):
            m = re.fullmatch(r"#(.*)#([a-z]*)", ats["linkPattern"], re.S)
            if not m:
                err(f"{where}: linkPattern must be a #...# PHP regex")
            else:
                try:
                    re.compile(m.group(1))
                except re.error as e:
                    err(f"{where}: linkPattern doesn't compile ({e})")

        for j, r in enumerate(c.get("openRoles") or []):
            missing = ROLE_REQUIRED - set(r)
            if missing:
                err(f"{where}: openRoles[{j}] missing {sorted(missing)}")

        if "match" in c:
            m = c["match"]
            if not isinstance(m, dict) or not m or set(m) - MATCH_KEYS:
                err(f"{where}: match must be an object with only {sorted(MATCH_KEYS)}")
            else:
                if "name" in m and not (isinstance(m["name"], str) and m["name"].strip()):
                    err(f"{where}: match.name must be a non-empty string")
                if "aliases" in m and not (isinstance(m["aliases"], list) and m["aliases"]
                                           and all(isinstance(a, str) and a.strip() for a in m["aliases"])):
                    err(f"{where}: match.aliases must be a non-empty list of strings")
                if "note" in m and not isinstance(m["note"], str):
                    err(f"{where}: match.note must be a string")

    for label, values in (
        ("slug", [c.get("slug") for c in companies]),
        ("name", [c.get("name") for c in companies]),
        ("openRoles id", [r.get("id") for c in companies for r in c.get("openRoles") or []]),
    ):
        dups = sorted(v for v, n in Counter(values).items() if n > 1)
        if dups:
            err(f"duplicate {label}(s): {dups}")

    js_slugs = set(re.findall(r'^\s*slug:\s*"([^"]+)"', SCRAPE_JS.read_text(encoding="utf-8"), re.M))
    snap = {c["ats"]["slug"] for c in companies
            if (c.get("ats") or {}).get("type") == "snapshot" and c["ats"].get("slug")}
    for s in sorted(snap - js_slugs):
        err(f"snapshot company '{s}' has no entry in js-scraper/scrape.js (it will never get data)")
    for s in sorted(js_slugs - snap):
        err(f"js-scraper/scrape.js scrapes '{s}', but no snapshot-type company uses it (wasted run)")

    return errors


if __name__ == "__main__":
    problems = check()
    n = len(json.loads(COMPANIES_JSON.read_text(encoding="utf-8")).get("companies") or [])
    if problems:
        print(f"companies.json: {len(problems)} problem(s) across {n} companies")
        for p in problems:
            print("  FAIL ", p)
        sys.exit(1)
    print(f"companies.json OK -- {n} companies, all checks passed")
