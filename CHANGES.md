# ZENPATH — Phase 0 delivery (measurement instrumentation)

Date: 2026-09-22

## What's in this zip

Only the files that actually changed this round. Paths inside the zip match
their location in the `isubakoa/finpath` repo exactly, under `li-scraper/`.

| File | Destination | What changed |
|---|---|---|
| `li-scraper/scrape.py` | **git repo** | `build_fresh_roles()` gained an optional `measure_csv_path` arg that logs every raw result (matched or not) to a CSV, purely as a side effect. Left unset — the default — this is byte-for-byte the same function as before. `main()` now reads the CSV path from a `MEASURE_UNMATCHED_CSV` env var. No change to what gets written to `li-snapshot.json`. |
| `li-scraper/.github/workflows/scrape-li.yml` | **git repo** | Sets `MEASURE_UNMATCHED_CSV=phase0-unmatched.csv` for the scraper step and commits that file alongside `li-snapshot.json` each hourly run, so measurement data accumulates on the existing cron — no new infrastructure. |
| `li-scraper/PHASE0_MEASUREMENT.md` | **git repo** (new file) | How to compute the Phase 0 numbers from the CSV once it has data, and a checklist for removing this instrumentation once Phase 0 is done. |

**FTP (`php-ftp/`) files: none this round.** `check.php` and `index.html`
are untouched — Phase 1–4 (the matcher fixes, the open-market feed, and the
frontend work) are gated behind Phase 0's numbers per the spec, so there's
nothing to deploy to the live site yet.

## Before merging

Tested locally against the existing suites before and after this change,
both still fully green:
- `test_match.py`: 44/44 passed
- `test_rotation.py`: ALL PASSED

These three files were **not** committed or pushed from my side — the repo
is mid-reconciliation (diverged local/origin history), which you're handling
yourself. Drop these into your checkout at the paths above once `main` is
where you want it, commit, and push; the existing hourly cron picks the
measurement up automatically from there.

## Going forward

Each round of fixes will come as a zip like this one, containing only the
files that changed, each labeled with its destination (git repo vs. FTP
upload to `php-ftp/`) and a one-line description of what changed and why.
