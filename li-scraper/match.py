"""
Matching logic shared by scrape.py — kept in its own file so it can be
unit-tested in isolation (see test_match.py) without pulling in JobSpy or
network code.

Three jobs:
  1. is_role_relevant(title)  — the exact same Design/UX/Product/Strategy
     title filter as index.html's isRoleRelevant(), ported line-for-line so
     a role that would be filtered out in the tracker is filtered out here
     too, and nothing slips through that the tracker would've hidden anyway.
  2. fit_tier(title) — the same seniority tiering as index.html's
     fitTierFromTitle(), used only to decide which roles are worth the
     (rate-limit-sensitive) LI request budget — see scrape.py.
  3. match_company(employer_name, companies) — given a LI posting's
     employer name, find which (if any) of the 143 tracked companies it is,
     so postings can be filed under the right slug in li-snapshot.json.
"""

import re

# ---- Ported from index.html's isRoleRelevant() — keep these three regexes
# ---- byte-for-byte in sync with that function if it ever changes. ----
ALWAYS_ALLOW = re.compile(
    r"(ux engineer|ui engineer|design engineer|design technologist|"
    r"creative technologist|product marketing|marketing manager)",
    re.IGNORECASE,
)
POSITIVE = re.compile(
    r"(design|\bux\b|\bui\b|user experience|\bproduct\b|strategist|strategy|"
    r"(user|customer|product) research|research (lead|manager|strategist))",
    re.IGNORECASE,
)
NEGATIVE = re.compile(
    r"(engineer|developer|dev\b|qa\b|quality assurance|sales|marketing|legal|"
    r"counsel|finance|accounting|account manager|recruit|talent acquisition|"
    r"\bhr\b|human resources|data scientist|analyst|logistics|warehouse|"
    r"driver|technician)",
    re.IGNORECASE,
)

# ---- Ported from index.html's fitTierFromTitle() ----
TARGET_TIER = re.compile(
    r"(director|head of|\bvp\b|vice president|principal|staff|\blead\b|\bgroup\b|chief)",
    re.IGNORECASE,
)
BELOW_TIER = re.compile(r"(intern|internship|graduate|junior|associate)", re.IGNORECASE)


def is_role_relevant(title):
    t = title or ""
    if ALWAYS_ALLOW.search(t):
        return True
    return bool(POSITIVE.search(t)) and not NEGATIVE.search(t)


def fit_tier(title):
    t = title or ""
    if TARGET_TIER.search(t):
        return "target"
    return "below"  # BELOW_TIER match or no seniority signal at all — both non-target


# ---- Company-name matching ----

# Stripped as whole words only (case-insensitive), so real brand words that
# happen to contain these letters (e.g. "Grab") are untouched.
# Deliberately narrow — only generic corporate-form suffixes, never a word
# that could be part of what actually distinguishes one tracked company's
# name from another (e.g. "International", "Investments", "Digital" are
# left alone: stripping those turned "Network International" into the
# dangerously generic "network" during testing, so anything not a clear
# legal/corporate suffix stays in the name).
_LEGAL_SUFFIXES = re.compile(
    r"\b(inc|incorporated|ltd|limited|llc|llp|plc|corp|corporation|co|company|"
    r"group|holdings?|pte|pty|gmbh|ag|nv|n\.v|sa|s\.a|bhd|berhad|bank|banking)\b\.?",
    re.IGNORECASE,
)
_PARENS = re.compile(r"\(([^)]*)\)")
_PUNCT = re.compile(r"[^\w\s]")
_WS = re.compile(r"\s+")

# Below this normalized length, only an exact match counts — short common
# words ("Wise", "Moss", "Alan", "Boost") are too likely to collide with an
# unrelated company's name as a mere substring.
_MIN_CONTAINMENT_LEN = 5


def _normalize(name):
    name = name or ""
    name = _PARENS.sub(" ", name)
    name = _PUNCT.sub(" ", name)
    name = _LEGAL_SUFFIXES.sub(" ", name)
    name = _WS.sub(" ", name).strip().lower()
    return name


def _aliases_for(name):
    """Main name plus anything found in parentheses, split on '/' — e.g.
    "Zepz (WorldRemit / Sendwave)" -> ["Zepz", "WorldRemit", "Sendwave"]."""
    out = [name]
    m = _PARENS.search(name)
    if m:
        for part in m.group(1).split("/"):
            part = part.strip()
            if part:
                out.append(part)
    return out


def build_index(companies, aliases_by_slug=None):
    """Pre-compute normalized alias -> slug lookups once per run, instead of
    re-normalizing all 143 names for every LI result."""
    aliases_by_slug = aliases_by_slug or {}
    exact = {}   # normalized name -> slug
    fuzzy = []   # (normalized name, slug) for containment matching
    for c in companies:
        names = _aliases_for(c["name"]) + aliases_by_slug.get(c["slug"], [])
        for n in names:
            norm = _normalize(n)
            if not norm:
                continue
            exact[norm] = c["slug"]
            if len(norm) >= _MIN_CONTAINMENT_LEN:
                fuzzy.append((norm, c["slug"]))
    # Longest-first so a more specific alias wins over a shorter one that
    # happens to be a substring of it.
    fuzzy.sort(key=lambda pair: -len(pair[0]))
    return {"exact": exact, "fuzzy": fuzzy}


def match_company(employer_name, index):
    norm = _normalize(employer_name)
    if not norm:
        return None
    if norm in index["exact"]:
        return index["exact"][norm]
    for alias_norm, slug in index["fuzzy"]:
        if alias_norm in norm or norm in alias_norm:
            return slug
    return None
