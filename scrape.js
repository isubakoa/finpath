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
// Each entry needs `urls` (one or more pages that actually list jobs — not
// always the top-level careers page) and a `linkPattern` (a JS regex
// matching that company's real job-posting URLs, confirmed by hand against
// the live site — see "Adding a company" below). Get this wrong and you'll
// silently get zero roles back, not an error, so always verify a new
// pattern with `node scrape.js --debug <slug>` before relying on it.
//
// Why more than one URL: a lot of career sites show only a handful of
// "featured" postings on their plain /careers page and load the rest via
// pagination or infinite scroll, which is a pain to automate reliably. Where
// the site has its own filter (a `?team=...` or `?department=...` query
// param, found by using the site's own filter UI once and reading the
// resulting URL), it's both simpler and more targeted to scrape that
// filtered URL directly instead — see Adyen below for a real example.
const COMPANIES = [
  {
    slug: "adyen",
    // careers.adyen.com/vacancies on its own only renders 5 unfiltered
    // "featured" roles out of 225 total, with the rest behind infinite
    // scroll. Using the site's own team filter (found via its filter
    // dropdown, which updates the URL) goes straight to the roles that
    // matter instead of trying to automate scrolling through everything.
    urls: [
      "https://careers.adyen.com/vacancies?team=Product+Management",
      "https://careers.adyen.com/vacancies?team=Strategy+%26+Execution",
    ],
    linkPattern: /\/vacancies\/\d+-/,
    waitForSelector: 'a[href*="/vacancies/"]',
  },
  {
    slug: "klarna",
    // Klarna's careers site (klarna.com/careers) links out to a Deel-hosted
    // job board at jobs.deel.com/klarna. All open roles render in one page
    // (no pagination/infinite-scroll to worry about — confirmed by hand),
    // but the raw server HTML only contains the job *links*, not their
    // titles (those are filled in by client-side React after load), so
    // check.php's plain "html" scraper can't read this one — it needs an
    // actual browser, same as Adyen.
    urls: ["https://jobs.deel.com/klarna"],
    linkPattern: /\/klarna\/job-details\/[a-f0-9-]+\/overview/,
    waitForSelector: 'a[href*="/job-details/"]',
    // Each job card is one big <a> wrapping the title plus location,
    // employment type, and salary all mashed together in its text content —
    // the actual title lives in a single child element, so pull that
    // specifically instead of the whole card's text.
    titleSelector: "p",
  },
  // Still need a confirmed pattern (see README "Companies not yet wired up"):
  // wefox — its main careers page (careers.wefox.com) is currently broken/
  // unreachable and its company-wide board on join.com shows zero open
  // positions, so there's nothing live to verify a scraper against right
  // now. Trade Republic turned out not to need this file at all — it runs
  // on Greenhouse under the hood, so it's wired directly into check.php's
  // existing "greenhouse" adapter instead (see php-ftp/README.md).
];

const TIMEOUT_MS = 30000;
const USER_AGENT =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36";

async function scrapeOneUrl(browser, url, company) {
  const page = await browser.newPage({ userAgent: USER_AGENT });
  try {
    await page.goto(url, { waitUntil: "networkidle", timeout: TIMEOUT_MS });
    if (company.waitForSelector) {
      // Best-effort: if the selector never shows up (page structure changed,
      // or genuinely zero roles right now), fall through and scrape whatever
      // did render rather than failing the whole page.
      await page.waitForSelector(company.waitForSelector, { timeout: TIMEOUT_MS }).catch(() => {});
    }

    const roles = await page.evaluate(({ patternSource, titleSelector }) => {
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
        // Most sites' job links are plain text, so the whole anchor's text
        // is the title. Some (Klarna's Deel-hosted board, for one) wrap a
        // whole card — title, location, salary — in one <a>, in which case
        // titleSelector picks out just the title from a child element.
        const titleEl = titleSelector ? a.querySelector(titleSelector) : null;
        const title = ((titleEl || a).textContent || "").replace(/\s+/g, " ").trim();
        if (title.length < 3) return;
        seen.add(abs);
        out.push({ title, url: abs });
      });
      return out;
    }, { patternSource: company.linkPattern.source, titleSelector: company.titleSelector || null });

    await page.close();
    return roles;
  } catch (err) {
    await page.close().catch(() => {});
    throw err;
  }
}

async function scrapeCompany(browser, company, { debug = false } = {}) {
  const urls = company.urls || (company.url ? [company.url] : []);
  const seen = new Set();
  const roles = [];
  const errors = [];

  for (const url of urls) {
    try {
      const found = await scrapeOneUrl(browser, url, company);
      found.forEach((r) => {
        if (seen.has(r.url)) return;
        seen.add(r.url);
        roles.push(r);
      });
    } catch (err) {
      errors.push(`${url}: ${String((err && err.message) || err)}`);
    }
  }

  if (debug) {
    console.log(`[${company.slug}] ${roles.length} matching link(s) found across ${urls.length} URL(s):`);
    roles.forEach((r) => console.log(`  - ${r.title}  ->  ${r.url}`));
    if (errors.length) errors.forEach((e) => console.log(`  ! ${e}`));
  }

  // A company only fails outright if every one of its URLs failed — a
  // partial failure (one filtered URL down, another fine) still returns
  // whatever roles were found rather than throwing the good ones away.
  if (roles.length === 0 && errors.length === urls.length && urls.length > 0) {
    return { ok: false, error: errors.join("; ") };
  }
  return { ok: true, roles: roles.map((r) => ({ ...r, location: "", postedDate: null })) };
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
