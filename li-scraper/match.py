"""
Matching logic shared by scrape.py — kept in its own file so it can be
unit-tested in isolation (see test_match.py) without pulling in JobSpy or
network code.

Jobs:
  1. is_role_relevant(title)  — the exact same Design/UX/Product/Strategy
     title filter as index.html's isRoleRelevant(), ported line-for-line so
     a role that would be filtered out in the tracker is filtered out here
     too, and nothing slips through that the tracker would've hidden anyway.
  2. fit_tier(title) — index.html's two-axis computeFit() (seniorityTier x
     domainTier, weaker axis wins), used to decide which roles are worth the
     (rate-limit-sensitive) LI request budget — see scrape.py — and, once
     Phase 2 lands, to gate the open-market feed.
  3. normalize_scraped_title(title, location) — index.html's
     normalizeScrapedTitle(): strips CTA suffix text a raw scrape sometimes
     drags in ("View Job", "Apply Now", ...) and, only when location came
     back empty/unknown, recovers a trailing "City, Region" run-on from the
     title text itself.
  4. role_identity(slug, title, location) — the normalized (employer, title,
     location) key scrape.py's build_fresh_roles() dedupes on (Phase 1.4),
     so the same real posting found via two different sites (or re-posted
     under a fresh URL later) collapses into one role instead of two.
  5. match_company(employer_name, companies) — given a posting's employer
     name, find which (if any) of the tracked companies it is, so postings
     can be filed under the right slug in li-snapshot.json.

PHASE 1 NOTE (Sep 2026): #1/#2/#3 below were, before this phase, a byte-for-
-byte-in-sync port of index.html's own logic. Over time index.html moved
ahead on its own (the hard-exclusion tier, the two-axis fit split, and the
title/location cleanup all shipped there first and were battle-tested on
real curated/live-checked role data before this file caught up) — Phase 1
is that catch-up: everything below is now ported from index.html's *current*
behavior, not re-derived from the original spec text, specifically to avoid
regressing logic index.html already had working in production. Keep it in
sync with index.html's equivalents (CTA_SUFFIX_RE/TRAILING_LOCATION_RE,
NEGATIVE_TITLE_TERMS, the seniority/domain regexes, alwaysAllow) going
forward.
"""

import re

# ---- Ported from index.html's isRoleRelevant() ----
# 1.1: "marketing manager" removed — it was matching plain marketing-manager
# titles like "Growth Marketing Manager, Credit Products" and letting them
# bypass the NEGATIVE check entirely (the actual bug: NEGATIVE already
# catches bare "marketing", so removing this bypass is the whole fix, no
# other change needed). "product marketing" is kept: it's a narrow enough
# phrase (a title has to literally contain those two words together) that
# the false-positive risk is low, and removing it would newly exclude titles
# like "Senior Product Marketing Manager" that TITLE_CASES has long asserted
# should stay relevant-but-below-tier — judged not worth changing as part of
# this fix. Re-ordered so the hybrid design/engineering titles lead and
# "product marketing" reads as the one deliberately-kept exception.
ALWAYS_ALLOW = re.compile(
    r"(ux engineer|ui engineer|design engineer|design technologist|"
    r"creative technologist|product marketing)",
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

# ---- 1.2/1.3: ported from index.html's NEGATIVE_TITLE_TERMS +
# ---- matchNegativeFilters()/SENIOR_QUALIFIER_RE. A hard exclusion — unlike
# ---- NEGATIVE above (which only blocks ALWAYS_ALLOW/POSITIVE from making a
# ---- title relevant in the first place), a match_negative_filters() hit
# ---- means "actively below what we're looking for", checked first by both
# ---- is_role_relevant() and domain_tier(). Extended here (both this file
# ---- and index.html, 1.3) with the full spec list: procurement, logistics,
# ---- warehouse, facilities, cabin crew, onboard — index.html previously
# ---- only had junior/intern/graduate/trainee/apprentice/catering/legal/
# ---- 변호사/compliance/temp-contract.
NEGATIVE_TITLE_TERMS = [
    (re.compile(r"\bjunior\b", re.IGNORECASE), "junior"),
    (re.compile(r"\bintern(ship)?\b", re.IGNORECASE), "intern"),
    (re.compile(r"\bgraduate\b", re.IGNORECASE), "graduate"),
    (re.compile(r"\btrainee\b", re.IGNORECASE), "trainee"),
    (re.compile(r"\bapprentice\b", re.IGNORECASE), "apprentice"),
    (re.compile(r"\bcatering\b", re.IGNORECASE), "catering"),
    (re.compile(r"\b(legal|counsel)\b", re.IGNORECASE), "legal / counsel"),
    (re.compile(r"변호사"), "변호사 (in-house lawyer)"),
    (re.compile(r"\bcompliance\b", re.IGNORECASE), "compliance"),
    (re.compile(r"temp(orary)?\s*contract", re.IGNORECASE), "temp contract"),
    (re.compile(r"\bprocurement\b", re.IGNORECASE), "procurement"),
    (re.compile(r"\blogistics\b", re.IGNORECASE), "logistics"),
    (re.compile(r"\bwarehouse\b", re.IGNORECASE), "warehouse"),
    (re.compile(r"\bfacilities\b", re.IGNORECASE), "facilities"),
    (re.compile(r"cabin\s*crew", re.IGNORECASE), "cabin crew"),
    (re.compile(r"\bonboard\b", re.IGNORECASE), "onboard"),
]
# "Associate" alone reads junior; "Associate/AVP, Product Experience" or
# "Associate Director" doesn't — matches index.html's SENIOR_QUALIFIER_RE
# exception exactly.
SENIOR_QUALIFIER_RE = re.compile(r"\b(avp|vp|vice[\s-]?president|director)\b", re.IGNORECASE)
_ASSOCIATE_RE = re.compile(r"\bassociate\b", re.IGNORECASE)


def match_negative_filters(title):
    """Every hard-exclusion reason this title matches (empty list = none).
    Ported from index.html's matchNegativeFilters() — its per-user
    learnedExclusions() step is frontend/state-specific and has no
    equivalent here."""
    t = title or ""
    hits = [label for pattern, label in NEGATIVE_TITLE_TERMS if pattern.search(t)]
    if _ASSOCIATE_RE.search(t) and not SENIOR_QUALIFIER_RE.search(t):
        hits.append("associate (without AVP/VP/Director)")
    return hits


# ---- 1.3: ported from index.html's seniorityTier()/domainTier()/
# ---- computeFit() — the two-axis split ("target" only if BOTH the
# ---- seniority word AND the domain phrasing clear the bar; the weaker axis
# ---- decides) replacing the old single-regex fit_tier(). `\bavp\b` added to
# ---- the seniority regex to match index.html (this file's old TARGET_TIER
# ---- didn't have it). The old BELOW_TIER regex is gone — it was dead code
# ---- (defined but never actually checked; fit_tier() just fell through to
# ---- "below" for anything that didn't match TARGET_TIER) and is properly
# ---- superseded by match_negative_filters()/domain_tier() now anyway.
TARGET_TIER = re.compile(
    r"(director|head of|\bvp\b|vice president|principal|staff|\blead\b|\bgroup\b|chief|\bavp\b)",
    re.IGNORECASE,
)
DOMAIN_CORE = re.compile(
    r"(product design|design lead|ux research|user experience|design strategist|"
    r"design system|head of design|vp of design|design director|\bux\b|\bui\b|"
    r"design technologist|creative technologist)",
    re.IGNORECASE,
)
DOMAIN_BROADER = re.compile(
    r"(\bproduct\b|strategist|strategy|research|marketing manager)",
    re.IGNORECASE,
)
TIER_RANK = {"excluded": -1, "stretch": 0, "below": 1, "target": 2}


def seniority_tier(title):
    t = title or ""
    return "target" if TARGET_TIER.search(t) else "below"


def domain_tier(title):
    if match_negative_filters(title):
        return "stretch"
    t = title or ""
    if DOMAIN_CORE.search(t):
        return "target"
    if DOMAIN_BROADER.search(t):
        return "below"
    return "stretch"


def is_role_relevant(title):
    t = title or ""
    if match_negative_filters(t):
        return False
    if ALWAYS_ALLOW.search(t):
        return True
    return bool(POSITIVE.search(t)) and not NEGATIVE.search(t)


def fit_tier(title):
    """1.2: a hard-excluded title (junior/intern/associate-without-
    qualifier/etc.) reports its own "excluded" tier rather than falling
    through to seniority_tier()/domain_tier()'s "stretch" — in practice
    is_role_relevant() already drops these before a kept role ever reaches
    fit_tier(), so this only shows up in diagnostics (Phase 0's measurement
    CSV logs fit_tier() for every raw row, kept or not) and any future
    caller that wants to distinguish "genuinely below-tier" from "shouldn't
    be in the running at all". seniority_tier()/domain_tier() stay faithful,
    byte-for-byte ports of index.html's own functions (including index.html's
    "stretch" — not "excluded" — for a hard-excluded title on that axis), so
    a standalone caller mirroring index.html's fitReasons()-style breakdown
    still gets index.html's exact three-tier answer."""
    if match_negative_filters(title):
        return "excluded"
    sen, dom = seniority_tier(title), domain_tier(title)
    return sen if TIER_RANK[sen] <= TIER_RANK[dom] else dom


# ---- 1.5: ported from index.html's CTA_SUFFIX_RE/TRAILING_LOCATION_RE/
# ---- isUnknownLocation()/normalizeScrapedTitle() — already applied there to
# ---- index.html's own curated openRoles (see index.html's "reused verbatim"
# ---- comment). A raw scrape sometimes drags trailing UI-button text into
# ---- the title ("Head of Design View Job"), or — when the site gave no
# ---- separate location field — runs the location straight into the title
# ---- text with nothing but a comma between them; this recovers both,
# ---- conservatively: the trailing-location recovery only ever fires when
# ---- the location field came back empty/unknown in the first place, so a
# ---- perfectly normal comma in a real title (e.g. "Director, Product
# ---- Design") is never touched once a real location is present.
CTA_SUFFIX_RE = re.compile(
    r"\s*[·|:\-–—]?\s*(view job|apply now|apply here|apply today|learn more|see job|read more|apply)\s*$",
    re.IGNORECASE,
)
TRAILING_LOCATION_RE = re.compile(
    r"([A-ZÀ-Ý][\wÀ-ÿ'.-]*(?:\s+[A-ZÀ-Ý][\wÀ-ÿ'.-]*){0,3},"
    r"\s*[A-ZÀ-Ý][\wÀ-ÿ'.-]*(?:\s+[A-ZÀ-Ý][\wÀ-ÿ'.-]*){0,3})\s*$"
)
_UNKNOWN_LOCATION_RE = re.compile(r"^(not specified\b.*|unspecified|not confirmed\b.*|unknown|n/a)$", re.IGNORECASE)
_MULTI_WS_RE = re.compile(r"\s+")
_TRAILING_SEP_RE = re.compile(r"[\s,·|–—-]+$")


def collapse_whitespace(s):
    return _MULTI_WS_RE.sub(" ", "" if s is None else str(s)).strip()


def is_unknown_location(loc):
    t = collapse_whitespace(loc)
    if not t:
        return True
    return bool(_UNKNOWN_LOCATION_RE.match(t))


def normalize_scraped_title(raw_title, raw_location):
    """Returns (title, location) — see the module docstring's #3. Emits ""
    (never "Not specified") for a still-unknown location once this runs;
    index.html's existing isUnknownLocation()/locationLabel() already render
    "" as an em dash, so scrape.py doesn't need its own placeholder string
    any more (1.5)."""
    title = collapse_whitespace(raw_title)
    location = collapse_whitespace(raw_location)
    changed = True
    while changed:
        before = title
        title = collapse_whitespace(CTA_SUFFIX_RE.sub("", title))
        changed = title != before
    if is_unknown_location(location):
        m = TRAILING_LOCATION_RE.search(title)
        if m:
            candidate = m.group(1)
            remainder = _TRAILING_SEP_RE.sub("", title[: len(title) - len(candidate)])
            if len(collapse_whitespace(remainder)) >= 3:
                title = collapse_whitespace(remainder)
                location = collapse_whitespace(candidate)
    return title, location


# ---- 1.4: cross-site duplicate identity ----
_IDENTITY_PUNCT_RE = re.compile(r"[^\w\s]")


def _normalize_identity_text(s):
    s = collapse_whitespace(s)
    s = _IDENTITY_PUNCT_RE.sub(" ", s)
    return _MULTI_WS_RE.sub(" ", s).strip().lower()


def role_identity(slug, title, location):
    """The (employer, title, location) key build_fresh_roles() dedupes
    postings on, regardless of which site found them or what URL they're
    at — see scrape.py's SOURCE_PRECEDENCE for how a conflict between two
    sites reporting "the same" identity is resolved. Uses the already-
    resolved company slug rather than re-normalizing the raw employer
    string, since that's already the more canonical, collision-checked form
    (see find_collisions() below). Known, accepted limitation: two genuinely
    different open reqs at the same company with the literal same title and
    location (not unheard of for a large employer running two identical-
    titled searches) collapse into one row here — the same class of
    trade-off as the Boost/Volvo company-name collisions documented further
    down, judged acceptable given Phase 0 measured the real cross-site
    duplicate rate at low single digits."""
    return (slug, _normalize_identity_text(title), _normalize_identity_text(location))


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
    # `name or ""` alone doesn't catch a raw pandas NaN (a float — truthy in
    # Python, so it sails past an `or` check) landing here from a caller that
    # didn't already sanitize it (see scrape.py's _clean_str for the same
    # issue at the source) — guard directly rather than relying solely on
    # every caller remembering to pre-clean.
    if name is None or (isinstance(name, float) and name != name):
        name = ""
    else:
        name = str(name)
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


def find_collisions(companies, aliases_by_slug=None):
    """Diagnostic, not used by scrape.py itself: every normalized alias that
    two or more *different* companies would both register as an exact-match
    key. build_index()'s `exact` dict is a plain last-write-wins assignment,
    so before this existed, a collision like this was invisible -- whichever
    company happened to be declared later in COMPANIES silently won, and
    every LI/Indeed posting for the other company got filed under the wrong
    slug with no error, no warning, nothing (found 2026-09 two different
    ways: "Boost Bank"/"Boost" both normalize to "boost" once "Bank" is
    stripped as a legal suffix, and separately "du"'s own alias list used to
    contain a phrase starting with "Emirates" that was shadowing the
    "Emirates Airline" entry added in the same batch).

    Returns {normalized_key: [slug, slug, ...]} (sorted) for every such
    case. Some of these are genuine, irreducible ambiguities -- two real
    companies whose names become identical text after normalization, not
    something a smarter matching algorithm can fix (Boost/Boost Bank
    literally share the same careers site) -- and are expected to stay
    reviewed-and-accepted rather than "fixed." test_match.py asserts this
    function's output against that reviewed allowlist, so a genuinely NEW,
    undeclared collision fails the test suite immediately instead of
    silently misfiling roles the way the Emirates/du one did before being
    caught by hand.
    """
    aliases_by_slug = aliases_by_slug or {}
    claims = {}  # normalized key -> set of slugs that registered it
    for c in companies:
        names = _aliases_for(c["name"]) + aliases_by_slug.get(c["slug"], [])
        for n in names:
            norm = _normalize(n)
            if not norm:
                continue
            claims.setdefault(norm, set()).add(c["slug"])
    return {norm: sorted(slugs) for norm, slugs in claims.items() if len(slugs) > 1}
