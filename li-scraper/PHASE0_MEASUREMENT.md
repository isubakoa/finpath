# Phase 0 measurement (temporary)

Part of the ZENPATH open-market feed work. Phase 0 exists to answer, with
real numbers, how many roles `build_fresh_roles()` is dropping today because
`match_company()` returns `None` — specifically for Singapore and
Netherlands — before any Phase 1/2 code gets written. Nothing here changes
production behavior: `li-snapshot.json` is written exactly as before.

## What this is

- `scrape.py`: `build_fresh_roles()` takes an optional `measure_csv_path`
  keyword arg. When set, it appends one row per **raw** result this run saw
  (matched or not, kept or not) to that CSV: `date, source, employer, title,
  location, matched_slug, is_role_relevant, fit_tier, job_url`.
  `matched_slug` is empty for unmatched rows. Left unset (the default), this
  parameter has zero effect — confirmed against the existing test suites
  (`test_match.py` 44/44, `test_rotation.py` all passed) before and after
  this change.
- `main()` reads the CSV path from the `MEASURE_UNMATCHED_CSV` env var.
- `.github/workflows/scrape-li.yml`: sets that env var to
  `phase0-unmatched.csv` for the "Run scraper" step, and adds that file
  alongside `li-snapshot.json` in the commit step, so it accumulates one
  run's worth of rows every hour, riding the existing cron — no new
  infrastructure.

## How to compute the Phase 0 numbers once enough rows have accumulated

From `li-scraper/phase0-unmatched.csv` (after `git pull`):

- unmatched/day, and the SG+NL subset: filter `matched_slug == ""`, group by
  `date` (and by `date` + `location in {Singapore, Netherlands}`).
- relevance pass rate among those: `is_role_relevant == "True"`.
- target-tier rate among those: `fit_tier == "target"` (note: pre-1.3, this
  column reflects today's single-axis `fit_tier()`, not the two-axis version
  Phase 1.3 will introduce — read the number with that in mind).
- top 40 unmatched employers by frequency: group `employer` where
  `matched_slug == ""`, sort by count.
- duplicate rate: group ALL rows (matched or not) by normalized
  `(title, employer, location)` identity; an identity with more than one
  distinct `job_url` is a cross-site (or same-site re-scrape) duplicate.

## Removal checklist (once Phase 0 numbers are collected and reported)

1. Delete `MEASURE_UNMATCHED_CSV` env var from `scrape-li.yml`'s "Run
   scraper" step, and drop `phase0-unmatched.csv` from the commit step's
   `git add`.
2. Revert `build_fresh_roles()`'s `measure_csv_path` parameter and the
   `_append_measurement_csv()` function in `scrape.py`, and the
   `measure_csv_path = os.environ.get(...)` line in `main()`.
3. Delete `li-scraper/phase0-unmatched.csv` from the repo (or leave it as a
   one-time historical artifact — your call).
4. Delete this file.
