import re

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
SENIOR_QUALIFIER_RE = re.compile(r"\b(avp|vp|vice[\s-]?president|director)\b", re.IGNORECASE)
_ASSOCIATE_RE = re.compile(r"\bassociate\b", re.IGNORECASE)


def match_negative_filters(title):
    t = title or ""
    hits = [label for pattern, label in NEGATIVE_TITLE_TERMS if pattern.search(t)]
    if _ASSOCIATE_RE.search(t) and not SENIOR_QUALIFIER_RE.search(t):
        hits.append("associate (without AVP/VP/Director)")
    return hits


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
    if match_negative_filters(title):
        return "excluded"
    sen, dom = seniority_tier(title), domain_tier(title)
    return sen if TIER_RANK[sen] <= TIER_RANK[dom] else dom


def open_market_gate(title, employer):
    if not is_role_relevant(title):
        return False
    if fit_tier(title) not in ("target", "below"):
        return False
    return True


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


_IDENTITY_PUNCT_RE = re.compile(r"[^\w\s]")


def _normalize_identity_text(s):
    s = collapse_whitespace(s)
    s = _IDENTITY_PUNCT_RE.sub(" ", s)
    return _MULTI_WS_RE.sub(" ", s).strip().lower()


def normalize_employer_name(name):
    return _normalize(name)


_GENDER_MARKER_RE = re.compile(
    r"\(\s*(?:all\s+genders?|gn|[mwfdxh](?:\s*[/|,*]\s*(?:[mwfdxh]|div|divers|diverse))+)\s*\)"
    r"|\b[mwfdx]\s*/\s*[mwfdx](?:\s*/\s*(?:[mwfdx]|div|divers|diverse))?\b"
    r"|\ball\s+genders?\b",
    re.IGNORECASE,
)
_IDENTITY_LEGAL_TOKENS = {
    "oü", "ou", "as", "asa", "ab", "aktiebolag", "oy", "oyj", "aps", "a", "s", "se", "sarl", "r", "l", "bv", "b", "v", "n",
    "kg", "srl", "spa", "p", "sro", "uab", "ag", "nv", "sa", "lda", "kft", "plc", "ltd", "limited", "gmbh", "inc",
    "technology", "technologies",
}


def _identity_title(title):
    return _normalize_identity_text(_GENDER_MARKER_RE.sub(" ", collapse_whitespace(title or "")))


def _identity_employer(employer_key):
    tokens = str(employer_key or "").split()
    while len(tokens) > 1 and tokens[-1] in _IDENTITY_LEGAL_TOKENS:
        tokens.pop()
    while len(tokens) > 1 and tokens[0] in _IDENTITY_LEGAL_TOKENS:
        tokens.pop(0)
    return " ".join(tokens)


def role_identity(employer_key, title, location):
    return (_identity_employer(employer_key), _identity_title(title), _normalize_identity_text(location))


_LEGAL_SUFFIXES = re.compile(
    r"\b(inc|incorporated|ltd|limited|llc|llp|plc|corp|corporation|co|company|"
    r"group|holdings?|pte|pty|gmbh|ag|nv|n\.v|sa|s\.a|bhd|berhad|bank|banking)\b\.?",
    re.IGNORECASE,
)
_PARENS = re.compile(r"\(([^)]*)\)")
_PUNCT = re.compile(r"[^\w\s]")
_WS = re.compile(r"\s+")

_MIN_CONTAINMENT_LEN = 5


def _normalize(name):
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
    out = [name]
    m = _PARENS.search(name)
    if m:
        for part in m.group(1).split("/"):
            part = part.strip()
            if part:
                out.append(part)
    return out


def build_index(companies, aliases_by_slug=None):
    aliases_by_slug = aliases_by_slug or {}
    exact = {}
    fuzzy = []
    excluded = {}
    for c in companies:
        names = _aliases_for(c["name"]) + aliases_by_slug.get(c["slug"], [])
        for n in names:
            norm = _normalize(n)
            if not norm:
                continue
            exact[norm] = c["slug"]
            if len(norm) >= _MIN_CONTAINMENT_LEN:
                fuzzy.append((norm, c["slug"]))
        blocked = {_normalize(n) for n in c.get("exclude") or []} - {""}
        if blocked:
            excluded[c["slug"]] = blocked
    fuzzy.sort(key=lambda pair: -len(pair[0]))
    return {"exact": exact, "fuzzy": fuzzy, "excluded": excluded}


def _contains_words(longer, shorter):
    return f" {shorter} " in f" {longer} "


def match_company(employer_name, index):
    norm = _normalize(employer_name)
    if not norm:
        return None
    if norm in index["exact"]:
        return index["exact"][norm]
    for alias_norm, slug in index["fuzzy"]:
        if norm in index["excluded"].get(slug, ()):
            continue
        if (_contains_words(norm, alias_norm)
                or (len(norm) >= _MIN_CONTAINMENT_LEN and _contains_words(alias_norm, norm))):
            return slug
    return None


def find_collisions(companies, aliases_by_slug=None):
    aliases_by_slug = aliases_by_slug or {}
    claims = {}
    for c in companies:
        names = _aliases_for(c["name"]) + aliases_by_slug.get(c["slug"], [])
        for n in names:
            norm = _normalize(n)
            if not norm:
                continue
            claims.setdefault(norm, set()).add(c["slug"])
    return {norm: sorted(slugs) for norm, slugs in claims.items() if len(slugs) > 1}
