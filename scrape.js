// scrape.js — run on a schedule by GitHub Actions (see workflow.yml in this folder).
//
// For each company below, this opens its careers page in a real (headless)
// browser, waits for the page's own JavaScript to finish rendering the job
// list, then pulls out every link matching that company's `linkPattern` —
// the same idea as check.php's "html" adapter (PHP/php-ftp/check.php), just
// with an actual browser doing the rendering step first, which is the one
// thing a plain PHP curl request can never do.
//
// Output is snapshot.json, in exactly the shape check.php's SNAPSHOT_URL
// feature expects:
//   { "generatedAt": "...", "companies": { "<slug>": { "ok": true, "roles": [...] } } }
// check.php fetches that file and merges each company's roles in, the same
// as any other live-checked company.

import { chromium } from "playwright";
import { writeFileSync } from "fs";

// ---- Companies to scrape -------------------------------------------------
//
// Each entry needs a `url` (the page that actually lists jobs — not always
// the top-level careers page; some sites need a "see all openings" sub-page)
// and a `linkPattern` (a JS regex matching that company's real job-posting
// URLs, confirmed by hand against the live site — see "Adding a company"
// below). Get this wrong and you'll silently get zero roles back, not an
// error, so always verify a new pattern with `node scrape.js --debug <slug>`
// before relying on it.
const COMPANIES = [
  {
    slug: "adyen",
    url: "https://careers.adyen.com/vacancies",
    linkPattern: /\/vacancies\/\d+-/,
    waitForSelector: 'a[href*="/vacancies/"]',
  },
  // Still need a confirmed pattern (see README "Companies not yet wired up"):
  // klarna, trade-republic, wefox — and any of the other JavaScript-only
  // companies from the tracker's "Needs manual check" list you want covered.
];

const TIMEOUT_MS = 30000;
const USER_AGENT =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36";

async function scrapeCompany(browser, company, { debug = false } = {}) {
  const page = await browser.newPage({ userAgent: USER_AGENT });
  try {
    await page.goto(company.url, { waitUntil: "networkidle", timeout: TIMEOUT_MS });
    if (company.waitForSelector) {
      // Best-effort: if the selector never shows up (page structure changed,
      // or genuinely zero roles right now), fall through and scrape whatever
      // did render rather than failing the whole company.
      await page.waitForSelector(company.waitForSelector, { timeout: TIMEOUT_MS }).catch(() => {});
    }

    const roles = await page.evaluate((patternSource) => {
      const pattern = new RegExp(patternSource);
      const seen = new Set();
      const out = [];
      document.querySelectorAll("a[href]").forEach((a) => {
        const href = a.getAttribute("href") || "";
        let abs;
        try {
          abs = new URL(href, location.href).href;
        } catch {
          return;
        }
        if (!pattern.test(abs) || seen.has(abs)) return;
        const title = (a.textContent || "").replace(/\s+/g, " ").trim();
        if (title.length < 3) return;
        seen.add(abs);
        out.push({ title, url: abs });
      });
      return out;
    }, company.linkPattern.source);

    if (debug) {
      console.log(`[${company.slug}] ${roles.length} matching links found:`);
      roles.forEach((r) => console.log(`  - ${r.title}  ->  ${r.url}`));
    }

    await page.close();
    return {
      ok: true,
      roles: roles.map((r) => ({ ...r, location: "", postedDate: null })),
    };
  } catch (err) {
    await page.close().catch(() => {});
    return { ok: false, error: String((err && err.message) || err) };
  }
}

async function main() {
  const args = process.argv.slice(2);
  const debug = args.includes("--debug");
  const onlySlug = debug ? args[args.indexOf("--debug") + 1] : null;
  const targets = onlySlug ? COMPANIES.filter((c) => c.slug === onlySlug) : COMPANIES;

  if (!targets.length) {
    console.error(onlySlug ? `No company configured with slug "${onlySlug}".` : "No companies configured.");
    process.exit(1);
  }

  const browser = await chromium.launch();
  const companies = {};
  for (const company of targets) {
    console.log(`Scraping ${company.slug}...`);
    companies[company.slug] = await scrapeCompany(browser, company, { debug });
    const r = companies[company.slug];
    console.log(r.ok ? `  ok — ${r.roles.length} role(s)` : `  failed — ${r.error}`);
  }
  await browser.close();

  if (!debug) {
    const snapshot = { generatedAt: new Date().toISOString(), companies };
    writeFileSync("snapshot.json", JSON.stringify(snapshot, null, 2));
    console.log(`\nWrote snapshot.json (${Object.keys(companies).length} compan${Object.keys(companies).length === 1 ? "y" : "ies"}).`);
  }
}

main();
