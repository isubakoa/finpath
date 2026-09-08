# FinPath — JS-only career site scraper (scheduled, via GitHub Actions)

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