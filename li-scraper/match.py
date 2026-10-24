"""
Matching logic for scrape.py, kept separate so it can be tested without JobSpy
or the network (test_match.py).

  is_role_relevant(title)        the app's isRoleRelevant() title filter, so the
                                 scraper keeps exactly what the app would show
  fit_tier(title)                the app's two-axis computeFit(): seniority x
                                 domain, the weaker axis wins
  normalize_scraped_title(t, l)  the app's normalizeScrapedTitle(): strip
                                 CTA text ("Apply Now"...) and, only when the
                                 location is unknown, recover a trailing
                                 "City, Region" from the title
  role_identity(key, t, l)       the (employer, title, location) key used to
                                 dedupe the same posting across sites
  match_company(name, index)     which tracked company (if any) an employer
                                 name belongs to

The first three are ports of app.js's logic (NEGATIVE_TITLE_TERMS,
SENIOR_QUALIFIER_RE, the seniority/domain regexes, CTA_SUFFIX_RE /
TRAILING_LOCATION_RE, alwaysAllow). Change both sides together.
"""

import re

# ---- Ported from the app's isRoleRelevant() ----
# ALWAYS_ALLOW lets a title through even if NEGATIVE would block it. Bare
# "marketing manager" is deliberately absent (it let plain marketing roles in);
# "product marketing" stays because it's narrow and TITLE_CASES expects it.
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

# ---- Hard exclusions (the app's NEGATIVE_TITLE_TERMS / matchNegativeFilters) ----
# Unlike NEGATIVE above (which only stops ALWAYS_ALLOW/POSITIVE from making a
# title relevant), a match here means "below what we're looking for" and is
# checked first by is_role_relevant() and domain_tier().
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
# "Associate" alone reads junior; "Associate/AVP ..." or "Associate Director"
# doesn't. Same exception as the app's SENIOR_QUALIFIER_RE.
SENIOR_QUALIFIER_RE = re.compile(r"\b(avp|vp|vice[\s-]?president|director)\b", re.IGNORECASE)
_ASSOCIATE_RE = re.compile(r"\bassociate\b", re.IGNORECASE)


def match_negative_filters(title):
    """Every hard-exclusion reason this title matches ([] = none). The app's
        per-user learned exclusions have no equivalent here.
    """
    t = title or ""
    hits = [label for pattern, label in NEGATIVE_TITLE_TERMS if pattern.search(t)]
    if _ASSOCIATE_RE.search(t) and not SENIOR_QUALIFIER_RE.search(t):
        hits.append("associate (without AVP/VP/Director)")
    return hits


# ---- Fit tiers (the app's seniorityTier/domainTier/computeFit) ----
# "target" only if BOTH the seniority word and the domain phrasing clear the
# bar; the weaker axis decides.
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
    """Like the app's computeFit(), except a hard-excluded title reports "excluded"
        instead of "stretch" (is_role_relevant() drops those before they get here
        anyway). seniority_tier()/domain_tier() stay exact ports of the app's.
    """
    if match_negative_filters(title):
        return "excluded"
    sen, dom = seniority_tier(title), domain_tier(title)
    return sen if TIER_RANK[sen] <= TIER_RANK[dom] else dom


def open_market_gate(title, employer):
    """Whether an untracked employer's posting enters the open-market feed. The
        only eligibility gate (scrape.py separately requires a searched market):
          - is_role_relevant(title), and
          - fit_tier(title) is "target" or "below" -- never "stretch" or "excluded".
        "below" is included because most real postings land there, and tracked
        companies show every tier; target-only made open market look empty.
        Staffing agencies are included on purpose (since 2026-09-28).
        Per-viewer hides ("Not relevant", learned exclusions) happen in the app.
    """
    if not is_role_relevant(title):
        return False
    if fit_tier(title) not in ("target", "below"):
        return False
    return True


# ---- Title/location cleanup (the app's normalizeScrapedTitle) ----
# Scrapes sometimes drag button text into the title ("Head of Design View Job")
# or run the location into it when there's no location field. The trailing-
# location recovery only fires when the location is empty/unknown, so a normal
# comma in a title ("Director, Product Design") is never touched.
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
    """Returns (title, location). An unknown location becomes "" (the app renders
        it as an em dash).
    """
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


# ---- Cross-site duplicate identity ----
_IDENTITY_PUNCT_RE = re.compile(r"[^\w\s]")


def _normalize_identity_text(s):
    s = collapse_whitespace(s)
    s = _IDENTITY_PUNCT_RE.sub(" ", s)
    return _MULTI_WS_RE.sub(" ", s).strip().lower()


def normalize_employer_name(name):
    """Public wrapper around _normalize() for callers outside this module -- an
        open-market posting has no slug, so its role_identity() key is the
        normalized employer name.
    """
    return _normalize(name)


def role_identity(employer_key, title, location):
    """The (employer, title, location) key build_fresh_roles() dedupes on, whatever
        site or URL a posting came from (conflicts resolved by scrape.py's
        SOURCE_PRECEDENCE). employer_key is the tracked slug, or the normalized
        employer name for open-market postings. Accepted limitation: two
        genuinely different reqs with identical title and location at the same
        employer collapse into one row.
    """
    return (employer_key, _normalize_identity_text(title), _normalize_identity_text(location))


# ---- Company-name matching ----

# Stripped as whole words only, so brand words containing these letters
# ("Grab") are untouched. Deliberately narrow: words like "International" or
# "Digital" stay, because stripping them made names dangerously generic
# ("Network International" -> "network").
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
    # A pandas NaN is a float and truthy, so `name or ""` doesn't catch it.
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
    re-normalizing every tracked name for every LI result."""
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
    """Every normalized alias that two or more different companies would register
        as an exact-match key. build_index() is last-write-wins, so a collision
        silently files one company's postings under the other (it happened with
        du/Emirates). test_match.py asserts this against a reviewed allowlist
        (e.g. Boost / Boost Bank, which genuinely normalize to the same text), so
        any new collision fails the tests.
    
        Returns {normalized_key: [slug, ...]}.
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
