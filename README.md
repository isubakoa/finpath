# FinPath — JS-only career site scraper (scheduled, via GitHub Actions)

This is the fix for the companies the main tool can never see into on its
own: careers pages that render their job list entirely in JavaScript, so a
plain server-side request (what `check.php` uses for everything else) only
ever sees an empty page shell. The only real fix is something that behaves
like an actual browser — loads the page, runs its JavaScript, waits for the
listings to appear, then reads them. That's what this does, on a schedule,
for free, using [Playwright](https://playwright.dev) and
[GitHub Actions](https://docs.github.com/actions).

**How it fits together:** this folder runs on its own, independent of your
web host — GitHub runs it, not your PHP hosting. Every few hours it visits
each configured company's careers page with a real headless browser, pulls
out job titles and links, and writes the result to `snapshot.json`, which it
commits back into this repo. `check.php` (in `php-ftp/`) then just fetches
that file's raw URL on GitHub and merges the results in — the same as any
other live-checked company, just refreshed every few hours instead of
instantly. There's also a real-time alternative to this (`cf-browser-worker/`
in this package, which renders on-demand instead of on a schedule) — both
produce the exact same JSON shape, so `check.php` doesn't need to know or
care which one you're using.

## Setup (about 10 minutes, one time)

1. **Create a GitHub account** if you don't have one (free — [github.com/join](https://github.com/join)).
2. **Create a new repository** — can be public or private; public is simpler
   (no token needed for `check.php` to read the result) and there's nothing
   sensitive in `snapshot.json` (just public job titles and links), so public
   is what these instructions assume.
3. **Push the contents of this folder** to that repo — `scrape.js`,
   `package.json`, and `.github/workflows/scrape.yml`. If you're comfortable
   with git:
   ```
   cd js-scraper
   git init
   git add .
   git commit -m "Set up FinPath JS scraper"
   git branch -M main
   git remote add origin https://github.com/<you>/<repo>.git
   git push -u origin main
   ```
   If you'd rather not use git directly, GitHub's web uploader (drag files
   into the repo page) works fine too — just recreate the
   `.github/workflows/scrape.yml` path exactly, GitHub Actions only looks
   there.
4. **That's it.** The workflow (`.github/workflows/scrape.yml`) is already
   set to run automatically every 3 hours, and once on every push to
   `scrape.js` so you can confirm a change works right away. You can also
   trigger it manually any time from the repo's **Actions** tab → "Scrape
   JS-only career sites" → **Run workflow**.
5. **Wire it into `check.php`**: once the first run has completed (check the
   Actions tab for a green checkmark, and confirm `snapshot.json` now exists
   in the repo), set in `check.php`:
   ```php
   const SNAPSHOT_URL = 'https://raw.githubusercontent.com/<you>/<repo>/main/snapshot.json';
   ```
   and in `index.html`, add `"snapshot"` to `LIVE_CHECK_ATS_TYPES`, and set
   each covered company's `ats` field to `{ type: "snapshot", slug: "adyen" }`
   (matching the slug used in `scrape.js`). I can do this last step for you
   once you've confirmed the repo is live — just let me know.

## Adding a company

Only one company (Adyen) ships pre-configured and verified. To add another:

1. Open the company's careers/job-listing page in a normal browser and view
   its page source *after* it's finished loading (right-click → Inspect →
   Elements tab shows the rendered DOM, not "View Source" which shows the
   pre-JavaScript HTML and won't help here).
2. Find a real job posting link and note its URL shape — most sites use a
   consistent pattern (`/vacancies/12345-job-title`, `/jobs/some-id`, etc.).
3. Add an entry to `COMPANIES` in `scrape.js`:
   ```js
   {
     slug: "company-slug",
     url: "https://company.com/careers",   // the page that actually lists jobs
     linkPattern: /\/careers\/[a-z0-9-]+-\d+/,  // matches that company's job URLs
     waitForSelector: 'a[href*="/careers/"]',    // optional: something to wait for before scraping
   }
   ```
4. **Verify it before trusting it**: run
   ```
   npm install
   node scrape.js --debug company-slug
   ```
   This prints every matching link and title it found without writing
   `snapshot.json` — confirm the results look right (real job titles, not
   nav links or "See all openings" buttons) before committing.
5. Push the change — the workflow runs automatically on any push to
   `scrape.js`, so you'll see the result in the Actions tab within a minute
   or two.

## Companies not yet wired up

From the batch of JavaScript-only companies found so far: **Klarna**,
**Trade Republic**, and **wefox** still need a confirmed `linkPattern` (Adyen
is the only one verified end-to-end). Trade Republic in particular doesn't
appear to expose a normal job-listing page at all right now — worth
rechecking, some companies route job listings through a different path
entirely (a separate careers subdomain, a modal that loads jobs via a
background request, etc.).

## Limitations, honestly

- **A company can break silently.** If a company redesigns its careers page,
  `linkPattern` can stop matching anything, and that company will just
  return zero roles rather than an error. There's no way around this for any
  approach that depends on a specific site's markup — it's the same
  trade-off `check.php`'s own `html` adapter makes. Worth spot-checking the
  Actions tab occasionally, or re-running `--debug` on a company if it's
  gone quiet for a while.
- **No posted-date, generally.** Most career-page listings don't show a
  posting date without opening each individual job, which would multiply
  the number of page loads substantially. Roles from this pipeline will
  usually have `postedDate: null`, meaning they won't appear in the Today
  tab — same behavior as the `html`-scraped companies in `check.php`.
- **Freshness is "every few hours," not instant.** If that's not close
  enough and you'd rather have this check live on every page load instead,
  see `cf-browser-worker/` — same output, different timing, different
  trade-offs (a free Cloudflare account and a daily rendering-time cap,
  instead of a GitHub account and a few hours of latency).
