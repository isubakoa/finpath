import json
import os
import sys
from datetime import datetime, timedelta, timezone

from match import (
    is_role_relevant,
    match_company,
    normalize_employer_name,
    normalize_scraped_title,
    open_market_gate,
    role_identity,
)

PRODUCT_TERMS = [
    "Product Manager",
    "Product Owner",
    "Product Lead",
    "Product Strategist",
    "Senior Product Manager",
    "Lead Product Manager",
    "Principal Product Manager",
    "Group Product Manager",
]

DESIGN_TERMS = [
    "Product Design Lead",
    "Senior Product Designer",
    "Senior UX Designer",
    "Senior UX/UI Designer",
    "Experience Designer",
    "User Experience Designer",
    "CX Designer",
    "Lead Product Designer",
    "Principal Product Designer",
    "Staff Product Designer",
    "Design Lead",
    "UX Lead",
    "UX Strategist",
    "UX Consultant",
    "UX Specialist",
    "Senior Design Manager",
    "Senior UX Manager",
    "Design Strategist",
    "Design Thinking Lead",
    "Design Technologist",
    "Creative Technologist",
    "VP of Design",
    "Head of Product Design",
    "Head of Design",
    "Design Director",
    "Associate Design Director",
]

SEARCH_TERMS = PRODUCT_TERMS + DESIGN_TERMS


GENERAL_SOURCES = ["ats", "li", "indeed", "bayt"]
SOURCE_PRECEDENCE = {s: i for i, s in enumerate(GENERAL_SOURCES)}


def set_hub_order(hub_ids):
    SOURCE_PRECEDENCE.clear()
    SOURCE_PRECEDENCE.update({s: i for i, s in enumerate(GENERAL_SOURCES + list(hub_ids))})


def _source_rank(source):
    return SOURCE_PRECEDENCE.get(source, len(SOURCE_PRECEDENCE))


def _merge_role_records(prior, new):
    sources = sorted(
        set(prior.get("sources") or ([prior["source"]] if prior.get("source") else []))
        | set(new.get("sources") or ([new["source"]] if new.get("source") else [])),
        key=_source_rank,
    )
    sponsorship_signal_union = sorted(
        set(prior.get("sponsorshipSignal") or []) | set(new.get("sponsorshipSignal") or [])
    )
    canonical = new if _source_rank(new.get("source")) <= _source_rank(prior.get("source")) else prior
    merged_role = dict(canonical)
    merged_role["sources"] = sources
    merged_role["sponsorshipSignal"] = sponsorship_signal_union
    merged_role["lastSeenAt"] = new.get("lastSeenAt") or prior.get("lastSeenAt")
    merged_role["postedDate"] = new.get("postedDate") or prior.get("postedDate")
    return merged_role


SPONSORSHIP_KEYWORDS = [
    "visa sponsorship",
    "relocation support",
    "international candidates",
    "global talent",
]

_SPONSORSHIP_NEGATION_CUES = (
    "no ", "not ", "without ", "unable to", "cannot ", "can't ", "won't ",
    "does not", "doesn't", "unfortunately",
)
_SPONSORSHIP_NEGATION_WINDOW_CHARS = 40


def _has_nearby_negation(text, match_start):
    prefix = text[max(0, match_start - _SPONSORSHIP_NEGATION_WINDOW_CHARS):match_start]
    return any(cue in prefix for cue in _SPONSORSHIP_NEGATION_CUES)


def sponsorship_signal(description):
    if not description:
        return []
    text = description.lower()
    hits = []
    for keyword in SPONSORSHIP_KEYWORDS:
        idx = text.find(keyword.lower())
        if idx != -1 and not _has_nearby_negation(text, idx):
            hits.append(keyword)
    return hits


SEARCHED_MARKETS = ["Singapore", "Hong Kong", "New Zealand", "Australia", "Netherlands", "Italy", "Germany",
                    "United Kingdom", "Ireland", "Malaysia", "United Arab Emirates"]
EXTRA_MARKETS = ["Finland", "Estonia", "Austria", "Denmark", "Sweden", "Norway", "Belgium", "Luxembourg",
                 "Lithuania", "Malta"]
CANONICAL_MARKETS = SEARCHED_MARKETS + EXTRA_MARKETS

MARKET_ALIASES = {
    "United Arab Emirates": ["uae"],
}

ISO_CODE_TO_MARKET = {
    "sg": "Singapore", "hk": "Hong Kong", "fi": "Finland",
    "nz": "New Zealand", "au": "Australia", "nl": "Netherlands", "it": "Italy",
    "de": "Germany", "gb": "United Kingdom",
    "uk": "United Kingdom", "ie": "Ireland", "my": "Malaysia",
    "ae": "United Arab Emirates", "ee": "Estonia", "at": "Austria", "dk": "Denmark",
    "se": "Sweden", "no": "Norway", "be": "Belgium", "lu": "Luxembourg", "lt": "Lithuania",
    "mt": "Malta",
}

CITY_ALIASES = {
    "amsterdam": "Netherlands", "eindhoven": "Netherlands", "utrecht": "Netherlands",
    "rotterdam": "Netherlands", "the hague": "Netherlands", "den haag": "Netherlands",
    "arnhem": "Netherlands", "den bosch": "Netherlands", "s-hertogenbosch": "Netherlands",
    "hilversum": "Netherlands",
    "haarlem": "Netherlands", "alkmaar": "Netherlands", "weesp": "Netherlands",
    "hoofddorp": "Netherlands", "almere": "Netherlands", "amstelveen": "Netherlands",
    "schiphol": "Netherlands", "zaandam": "Netherlands", "zaanstad": "Netherlands",
    "diemen": "Netherlands", "purmerend": "Netherlands",
    "leiden": "Netherlands", "delft": "Netherlands", "zoetermeer": "Netherlands",
    "rijswijk": "Netherlands", "schiedam": "Netherlands", "dordrecht": "Netherlands",
    "gouda": "Netherlands", "amersfoort": "Netherlands", "nieuwegein": "Netherlands",
    "zeist": "Netherlands", "houten": "Netherlands", "veenendaal": "Netherlands",
    "breda": "Netherlands", "tilburg": "Netherlands", "helmond": "Netherlands",
    "nijmegen": "Netherlands", "apeldoorn": "Netherlands", "wageningen": "Netherlands",
    "zwolle": "Netherlands", "deventer": "Netherlands", "enschede": "Netherlands",
    "hengelo": "Netherlands", "groningen": "Netherlands", "leeuwarden": "Netherlands",
    "maastricht": "Netherlands", "venlo": "Netherlands", "lelystad": "Netherlands",
    "noord-holland": "Netherlands", "north holland": "Netherlands",
    "zuid-holland": "Netherlands", "south holland": "Netherlands",
    "noord-brabant": "Netherlands", "north brabant": "Netherlands",
    "gelderland": "Netherlands", "flevoland": "Netherlands", "overijssel": "Netherlands",
    "sydney": "Australia", "melbourne": "Australia", "brisbane": "Australia",
    "helsinki": "Finland", "espoo": "Finland", "vantaa": "Finland",
    "tallinn": "Estonia", "tartu": "Estonia",
    "vienna": "Austria", "wien": "Austria", "graz": "Austria", "salzburg": "Austria",
    "innsbruck": "Austria",
    "copenhagen": "Denmark", "københavn": "Denmark", "aarhus": "Denmark", "odense": "Denmark",
    "aalborg": "Denmark",
    "stockholm": "Sweden", "gothenburg": "Sweden", "göteborg": "Sweden", "malmö": "Sweden",
    "malmo": "Sweden", "uppsala": "Sweden",
    "oslo": "Norway", "trondheim": "Norway", "stavanger": "Norway",
    "brussel": "Belgium", "bruxelles": "Belgium", "antwerp": "Belgium",
    "ghent": "Belgium", "leuven": "Belgium", "mechelen": "Belgium",
    "vilnius": "Lithuania", "kaunas": "Lithuania", "klaipėda": "Lithuania", "klaipeda": "Lithuania",
    "valletta": "Malta", "sliema": "Malta", "st julian": "Malta", "san giljan": "Malta", "gzira": "Malta",
    "birkirkara": "Malta",
    "munich": "Germany", "hamburg": "Germany", "stuttgart": "Germany",
    "nuremberg": "Germany",
    "milan": "Italy", "padova": "Italy", "padua": "Italy", "vicenza": "Italy",
    "kuala lumpur": "Malaysia",
    "dublin": "Ireland", "cork": "Ireland",
    "auckland": "New Zealand", "wellington": "New Zealand", "christchurch": "New Zealand",
    "blackpool": "United Kingdom",
    "dubai": "United Arab Emirates",
}


def market_for_location(location):
    loc = (location or "").strip()
    if not loc:
        return None
    loc_lower = loc.lower()
    if loc_lower in ISO_CODE_TO_MARKET:
        return ISO_CODE_TO_MARKET[loc_lower]
    for market in CANONICAL_MARKETS:
        needles = [market.lower()] + MARKET_ALIASES.get(market, [])
        if any(needle in loc_lower for needle in needles):
            return market
    parts = [p.strip().lower() for p in loc.split(",") if p.strip()]
    if parts and parts[-1] in ISO_CODE_TO_MARKET:
        return ISO_CODE_TO_MARKET[parts[-1]]
    for city, market in CITY_ALIASES.items():
        if city in loc_lower:
            return market
    return None


def is_known_market(location):
    return market_for_location(location) is not None


EXPIRY_DAYS = 14


def normalize_posted_date(value):
    if value is None:
        return None
    s = str(value)
    if not s or s.lower() in ("nat", "none", "nan"):
        return None
    return s[:10]


def _clean_str(value):
    if value is None or (isinstance(value, float) and value != value):
        return ""
    return str(value)


def duplicate_key(key, title, location):
    return role_identity(key, title, market_for_location(location) or location)


def build_fresh_roles(rows, index, today_iso, debug=False):
    fresh = {}
    fresh_open_market = {}
    seen_urls = set()
    kept = dropped_company = dropped_title = duplicate = merged_cross_site = 0
    kept_open_market = dropped_open_market_strict = merged_cross_site_open_market = 0
    dropped_off_market = 0

    for source, row in rows:
        url = _clean_str(row.get("job_url"))
        if not url or (source, url) in seen_urls:
            duplicate += 1
            continue
        seen_urls.add((source, url))

        employer = _clean_str(row.get("company"))
        title, location = normalize_scraped_title(_clean_str(row.get("title")), _clean_str(row.get("location")))
        slug = match_company(employer, index)

        if not slug:
            dropped_company += 1
            if debug:
                print(f"[match] no company match: {employer!r} — {row.get('title')!r}", file=sys.stderr)
            if not is_known_market(location):
                dropped_off_market += 1
                if debug:
                    print(f"[open-market] off-market location: {title!r} @ {employer!r} ({location!r})", file=sys.stderr)
                continue
            market = market_for_location(location)
            if employer and open_market_gate(title, employer):
                kept_open_market_this_row = True
            else:
                kept_open_market_this_row = False
                dropped_open_market_strict += 1
                if debug:
                    print(f"[open-market] failed gate: {title!r} @ {employer!r} ({market})", file=sys.stderr)
            if not kept_open_market_this_row:
                continue

            employer_key = normalize_employer_name(employer)
            identity = duplicate_key(employer_key, title, location)
            candidate_role = {
                "employer": employer,
                "market": market,
                "title": title,
                "location": location,
                "url": url,
                "postedDate": normalize_posted_date(row.get("date_posted")),
                "source": source,
                "sources": [source],
                "sponsorshipSignal": sponsorship_signal(_clean_str(row.get("description"))),
                "lastSeenAt": today_iso,
            }
            if identity in fresh_open_market:
                merged_cross_site_open_market += 1
                _, prior_role = fresh_open_market[identity]
                fresh_open_market[identity] = (employer_key, _merge_role_records(prior_role, candidate_role))
            else:
                kept_open_market += 1
                fresh_open_market[identity] = (employer_key, candidate_role)
            continue

        if not is_role_relevant(title):
            dropped_title += 1
            if debug:
                print(f"[match] title filtered out: {title!r} @ {employer!r}", file=sys.stderr)
            continue

        identity = duplicate_key(slug, title, location)
        candidate_role = {
            "title": title,
            "location": location,
            "url": url,
            "postedDate": normalize_posted_date(row.get("date_posted")),
            "source": source,
            "sources": [source],
            "sponsorshipSignal": sponsorship_signal(_clean_str(row.get("description"))),
            "lastSeenAt": today_iso,
        }

        if identity in fresh:
            merged_cross_site += 1
            _, prior_role = fresh[identity]
            fresh[identity] = (slug, _merge_role_records(prior_role, candidate_role))
            continue

        kept += 1
        fresh[identity] = (slug, candidate_role)

    if debug:
        print(
            f"[match] kept={kept} dropped_no_company_match={dropped_company} "
            f"dropped_title_filter={dropped_title} duplicate_urls={duplicate} "
            f"merged_cross_site_identities={merged_cross_site}",
            file=sys.stderr,
        )
        print(
            f"[open-market] kept={kept_open_market} dropped_strict_gate={dropped_open_market_strict} "
            f"dropped_off_market={dropped_off_market} "
            f"merged_cross_site_identities={merged_cross_site_open_market} "
            f"(of the {dropped_company} with no company match)",
            file=sys.stderr,
        )
    return fresh, fresh_open_market


def load_snapshot(path):
    if not os.path.exists(path):
        return {"companies": {}}
    try:
        with open(path) as f:
            data = json.load(f)
        if not isinstance(data, dict) or not isinstance(data.get("companies"), dict):
            return {"companies": {}}
        return data
    except (OSError, json.JSONDecodeError) as e:
        print(f"[merge] couldn't read existing {path} ({e}) — starting fresh", file=sys.stderr)
        return {"companies": {}}


def write_snapshot(path, snapshot):
    with open(path, "w") as f:
        json.dump(snapshot, f, indent=2)
        f.write("\n")


def _merge_identity_roles(existing_items, fresh_roles, cutoff):
    merged = {}
    for key, role in existing_items:
        identity = duplicate_key(key, role.get("title", ""), role.get("location", ""))
        if "sources" not in role or "sponsorshipSignal" not in role:
            role = dict(role)
            if "sources" not in role:
                role["sources"] = [role["source"]] if role.get("source") else []
            if "sponsorshipSignal" not in role:
                role["sponsorshipSignal"] = []
        if identity in merged:
            role = _merge_role_records(merged[identity][1], role)
        merged[identity] = (key, role)

    stats = {"added": 0, "updated": 0, "carried_over": 0, "expired": 0}
    for identity, (key, role) in fresh_roles.items():
        if identity in merged:
            stats["updated"] += 1
            _, prior_role = merged[identity]
            role = _merge_role_records(prior_role, role)
        else:
            stats["added"] += 1
        merged[identity] = (key, role)

    kept_items = []
    for identity, (key, role) in merged.items():
        if identity in fresh_roles:
            kept_items.append((key, role))
            continue
        last_seen = role.get("lastSeenAt") or "1970-01-01"
        if last_seen < cutoff:
            stats["expired"] += 1
            continue
        kept_items.append((key, role))

    return kept_items, stats


def _from_sources(role, keep_sources):
    if keep_sources is None:
        return True
    sources = role.get("sources") or ([role["source"]] if role.get("source") else [])
    return any(s in keep_sources for s in sources)


def result_urls(rows):
    return {url for url in (_clean_str(row.get("job_url")) for _, row in rows) if url}


def merge_and_prune(existing, fresh_roles, today_iso, fresh_open_market_roles=None, debug=False, keep_sources=None,
                    seen_urls=None):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=EXPIRY_DAYS)).strftime("%Y-%m-%d")
    fresh_open_market_roles = fresh_open_market_roles or {}
    seen_urls = seen_urls or set()
    placed = {(key, role.get("url")) for key, role in list(fresh_roles.values()) + list(fresh_open_market_roles.values())}

    def _refiled(key, role):
        url = role.get("url")
        return url in seen_urls and (key, url) not in placed

    existing_tracked_items = (
        (slug, role)
        for slug, entry in existing.get("companies", {}).items()
        for role in entry.get("roles", [])
        if _from_sources(role, keep_sources) and not _refiled(slug, role)
    )
    kept_items, stats = _merge_identity_roles(existing_tracked_items, fresh_roles, cutoff)
    companies_out = {}
    for slug, role in kept_items:
        companies_out.setdefault(slug, {"roles": []})["roles"].append(role)

    existing_open_market_items = (
        (key, dict(role, market=market_for_location(role.get("location", ""))))
        for key, role in ((normalize_employer_name(r.get("employer", "")), r) for r in existing.get("openMarket", {}).get("roles", []))
        if is_known_market(role.get("location", "")) and _from_sources(role, keep_sources) and not _refiled(key, role)
    )
    kept_open_market_items, om_stats = _merge_identity_roles(
        existing_open_market_items, fresh_open_market_roles, cutoff
    )
    open_market_roles_out = [role for _, role in kept_open_market_items]
    open_market_roles_out.sort(key=lambda r: (r.get("postedDate") or "", r.get("lastSeenAt") or ""), reverse=True)

    if debug:
        print(
            f"[merge] tracked: added={stats['added']} updated={stats['updated']} "
            f"carried_over={stats['carried_over']} expired_pruned={stats['expired']} (cutoff {cutoff})",
            file=sys.stderr,
        )
        print(
            f"[merge] open-market: added={om_stats['added']} updated={om_stats['updated']} "
            f"carried_over={om_stats['carried_over']} expired_pruned={om_stats['expired']}",
            file=sys.stderr,
        )

    return {
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "companies": companies_out,
        "openMarket": {"roles": open_market_roles_out},
    }
