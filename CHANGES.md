# Phase 1 — matcher bug fixes (1.1–1.5)

Date: 2026-09-23

All five Phase 1 items from the backlog, shipped together since they touch
the same functions. Per the backlog's own finding, these are **ports of
index.html's already-working logic** into `match.py`/`scrape.py` — not a
re-derivation from the original spec text — specifically to avoid
regressing behavior `index.html` already had tested in production
(hard-exclusion tiering, the two-axis fit split, and title/location cleanup
all shipped there first). `match.py`/`index.html` are back in sync as of
this round.

## What's in this zip

| File | Destination | What changed |
|---|---|---|
| `li-scraper/match.py` | **git repo** | 1.1/1.2/1.3/1.5 — see below |
| `li-scraper/scrape.py` | **git repo** | 1.4/1.5 — `build_fresh_roles()`/`merge_and_prune()` now dedupe on normalized identity, not URL |
| `li-scraper/test_match.py` | **git repo** | Extended to cover every changed rule — 62/62 passing (was 44/44) |
| `li-scraper/migrate_titles.py` | **git repo, new file** | One-time migration for 1.5 — see "Action needed" below |
| `php-ftp/index.html` | **FTP upload** | 1.1 + 1.3's negative-term-list extension only (see note below) |

## 1.1 — "marketing manager" removed from ALWAYS_ALLOW

It was letting plain marketing-manager titles ("Growth Marketing Manager,
Credit Products") bypass the relevance filter entirely. "product marketing"
is kept — narrow enough phrase, low false-positive risk, and removing it
would've newly excluded "Senior Product Marketing Manager"-style titles the
existing test suite already asserted should stay relevant-but-below-tier.
Judged not worth changing as part of this fix; flagged here as a call made
on your behalf per the backlog's "if wanted."

## 1.2 — Hard exclusion, now a distinct "excluded" tier

Ported `index.html`'s `matchNegativeFilters()` (junior/intern/graduate/
trainee/apprentice/temp-contract, plus "associate" *unless* paired with
AVP/VP/Director) into `match.py`. `is_role_relevant()` now checks this
first, same as `index.html`. `fit_tier()` reports a new `"excluded"` value
for these — distinct from `"stretch"` — mainly useful for diagnostics (the
Phase 0 measurement CSV logs `fit_tier()` for every raw row, kept or not),
since `is_role_relevant()` already drops these before a kept role would
ever reach `fit_tier()` in practice.

## 1.3 — Two-axis fit_tier() + extended hard-exclude list

`fit_tier()` now runs `index.html`'s real `seniorityTier()`/`domainTier()`
split (weaker axis wins) instead of the old single regex — a title needs
**both** real seniority *and* real design/product domain phrasing to score
`"target"`. This is a materially different (stricter) result for some
titles than before — e.g. "VP, Design Strategy" now scores `"below"`, not
`"target"`, because "Strategy" alone is only a broad domain match, not a
core design phrase. This is the exact same pattern the Phase 0 report
flagged in the real SG/NL data (only 10 of 41 old-logic "target" postings
held up under this axis). `test_match.py`'s title cases were updated to
match — see its comments for the full reasoning on each changed case.

The hard-exclude list (shared by 1.2/1.3, both files) is extended to the
full spec list: procurement, logistics, warehouse, facilities, cabin crew,
onboard — added to catering/legal/counsel/변호사/compliance/temp-contract,
which `index.html` already had.

## 1.4 — Cross-site dedupe, keyed on identity not URL

`build_fresh_roles()`/`merge_and_prune()` now dedupe on normalized
(employer, title, location) — not `job_url` — so the same real posting
found via two different sites (or a fresh URL on a later run) collapses
into one role with a `sources` array, instead of two separate rows. Source
precedence for which site's URL becomes canonical: `li > indeed > glassdoor
> google > bayt` (ATS ranked above all of them for forward-compat, though
this scraper doesn't produce ATS-sourced rows itself). Corroboration
accumulates across runs too — a role first found via Bayt that a later run
also finds via LinkedIn gets promoted to LinkedIn's canonical URL, keeping
Bayt in `sources`.

`check.php`'s `mergeLIResults()` is untouched, per the backlog — different,
already-correct URL-based dedupe for a different purpose.

**Known, accepted limitation** (documented in `match.py`): two genuinely
different open reqs at the same company with the literal same title and
location collapse into one row. Judged acceptable given Phase 0 measured
the real cross-site duplicate rate at ~2.6%.

## 1.5 — Title/location cleanup, ported from index.html

Ported `index.html`'s `normalizeScrapedTitle()`/`CTA_SUFFIX_RE`/
`TRAILING_LOCATION_RE` (already shipped and "reused verbatim" there on its
own curated role data) into `match.py`. Strips trailing CTA text ("View
Job", "Apply Now", etc.) from titles, and — only when the site gave no
location of its own — recovers a trailing "City, Country" run-on from the
title text. A perfectly normal comma in a real title (e.g. "Director,
Product Design") is never touched once a real location is already present.

Unknown location now emits `""`, not `"Not specified"` — `index.html`
already renders `""` as an em dash via its existing `isUnknownLocation()`/
`locationLabel()`, so no placeholder string is needed on the scraper side
any more.

### Action needed: run the migration once

Roles already sitting in `li-snapshot.json` from before this round (any
role not yet re-confirmed by today's chunk) still have the old
`"Not specified"` placeholder and un-normalized text. `migrate_titles.py`
re-normalizes everything already in the file — idempotent, safe to run more
than once:

```
cd li-scraper
python3 migrate_titles.py --dry-run   # see what it would change first
python3 migrate_titles.py             # then actually write it
```

Run this once against the real `li-snapshot.json` (locally, or however you
run one-off scripts against the live repo) and commit the result. Without
it, old entries just carry their pre-1.5 text until EXPIRY_DAYS (14 days)
naturally cycles them out — not broken, just not immediately clean.

## index.html — smaller change than the git-side files

`index.html` already had 1.2/1.3/1.5's logic (that's *why* Phase 1 is
mostly a port), so this round's FTP file only carries 1.1's ALWAYS_ALLOW
fix and 1.3's hard-exclude-list extension (both files, kept in sync) — plus
whatever was already in the file from the previous round's 21-new-companies
delivery, since FTP has no way to layer a partial diff. **This file
supersedes the previous `zenpath-new-companies.zip`'s `index.html`
entirely** — upload this one regardless of whether you already uploaded
that one; it contains everything from both rounds.

## Testing

`test_match.py`: 62/62 passing (was 44/44 — 18 new cases covering every
changed rule: 1.1's marketing-manager fix, 1.2's excluded tier and the
AVP/VP/Director associate exception, 1.3's two-axis split and extended
hard-exclude list, 1.4's cross-site merge with source-precedence and
sources-array assertions, 1.5's CTA-stripping and trailing-location
recovery including its one known, documented ambiguity). Also hand-verified
separately (not part of the automated suite, shown here for the record):
`merge_and_prune()` against a synthetic old-shape snapshot (no `sources`
field, a stale `"Not specified"` role) — confirmed cross-run source-
precedence promotion, `sources` union, and expiry pruning all work
together correctly; `migrate_titles.py --dry-run`/real run against a
synthetic snapshot — confirmed it cleans exactly the roles that need it and
is idempotent.

`index.html`'s inline script still parses as valid JS (checked via
`node --check` against the extracted script block).

## Not touched this round

Phase 2 (open-market feed), Phase 3 (`check.php`), Phase 4 (frontend UI) —
all still queued in the backlog, unchanged. `companies.py` — untouched,
still the same 231-company version from the previous round.
