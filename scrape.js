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
  {
    slug: "atlassian",
    // atlassian.com/company/careers/all-jobs renders its full ~225-role
    // list (every function, every location) directly on the page once its
    // own JS runs — no pagination or infinite scroll to fight, unlike most
    // boards here. Design/Product roles are filtered client-side by the
    // app itself, same as every other company.
    urls: ["https://www.atlassian.com/company/careers/all-jobs"],
    linkPattern: /\/company\/careers\/details\/\d+/,
    waitForSelector: 'a[href*="/company/careers/details/"]',
  },
  {
    slug: "fidelity-international",
    // Fidelity's careers site is a Workday tenant (fil.wd3.myworkdayjobs.com/001)
    // under the hood — confirmed via its own public API — but it's scraped
    // here rather than wired into check.php's existing "workday" adapter,
    // per how this batch of companies was deliberately handled. The search
    // results page renders real per-role links once its JS runs.
    urls: ["https://fil.wd3.myworkdayjobs.com/en-US/001?q=design"],
    linkPattern: /\/en-US\/001\/job\//,
    waitForSelector: 'a[href*="/en-US/001/job/"]',
  },
  {
    slug: "abu-dhabi-investment-authority-adia",
    // ADIA's board is hosted on Workable (jobs.workable.com), under a
    // company-id URL rather than the usual apply.workable.com/<slug>
    // pattern check.php's own "workable" adapter expects — still just a
    // rendered job list once the page loads, so it scrapes fine.
    urls: ["https://jobs.workable.com/company/5pvYKyK1ijbASjzk6Pg7kT/jobs-at-abu-dhabi-investment-authority"],
    linkPattern: /\/view\/[A-Za-z0-9]+\//,
    waitForSelector: 'a[href*="/view/"]',
  },
  {
    slug: "natwest-group",
    // jobs.natwestgroup.com runs on a "Talemetry" recruiting platform (a
    // genuine public JSON API sits underneath, confirmed by network
    // inspection, but not wired in directly per how this batch was
    // handled). The search results page renders real per-role links, but
    // each <a> wraps the whole card — title, location, salary, remote
    // status, req ID and posted-date all concatenated — so titleSelector
    // picks out just the title from its own <p class="job__title">.
    urls: ["https://jobs.natwestgroup.com/search/jobs?q=design"],
    linkPattern: /\/jobs\/\d+-/,
    waitForSelector: 'a[href^="/jobs/"]',
    titleSelector: ".job__title",
  },
  {
    slug: "bank-of-new-zealand-bnz",
    // BNZ's board (nab.eightfold.ai, filtered to the "bnz" microsite) sits
    // on parent NAB's Eightfold instance. Its job cards render as real
    // anchor links, but each card's title lives in a hashed CSS-module div
    // inside the link rather than being the link's own direct text, hence
    // titleSelector — the class always starts with "title-" even though
    // the hash suffix changes per deploy.
    urls: ["https://nab.eightfold.ai/careers?microsite=bnz&query=design"],
    linkPattern: /\/careers\/job\/\d+/,
    waitForSelector: 'a[href*="/careers/job/"]',
    titleSelector: '[class^="title-"]',
  },
  {
    slug: "abn-amro",
    // werkenbijabnamro.nl/en/vacancies. Its keyword-filter query param
    // turned out to be silently ignored server-side (confirmed by network
    // inspection — the same unfiltered call fires regardless of the
    // param), and its pagination is JS-only with nothing reflected in the
    // URL, so this only ever reaches page 1: the 8 most-recently-created
    // vacancies, sorted newest-first (of ~71 total). A known gap, but the
    // freshest postings are what matter most for a tool like this. Each
    // card's title lives in an <h2> a few DOM levels up from its own
    // "Show vacancy" link (the link's own text is just that CTA), so this
    // uses titleAncestorSelector/titleAncestorTitleSelector instead of the
    // usual in-link titleSelector.
    urls: ["https://www.werkenbijabnamro.nl/en/vacancies"],
    linkPattern: /\/en\/vacancy\/\d+/,
    waitForSelector: 'a[href*="/en/vacancy/"]',
    titleAncestorSelector: ".card-body.vacancy",
    titleAncestorTitleSelector: "h2",
  },
  {
    slug: "cimb-group",
    // CIMB's Malaysia board runs on Oracle Fusion Recruiting Cloud
    // (ejox.fa.ap1.oraclecloud.com) — the same platform check.php already
    // has a direct adapter for elsewhere, but scraped here per how this
    // batch was handled. Its own keyword filter works server-side (unlike
    // ABN AMRO's). Each card's title lives in a sibling span next to the
    // link rather than inside it.
    urls: ["https://ejox.fa.ap1.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/jobs?keyword=design"],
    linkPattern: /\/hcmUI\/CandidateExperience\/en\/sites\/CX_1\/job\/\d+/,
    waitForSelector: 'a[href*="/job/"]',
    titleAncestorSelector: ".job-tile",
    titleAncestorTitleSelector: ".job-tile__title",
  },
  {
    slug: "aspire",
    // Aspire's actual live board turned out to be on Revolut People
    // (revolutpeople.com/aspire), reached via an iframe wrapper hosted at
    // people-jobs.com/aspire — not the Greenhouse board this company's own
    // notes previously assumed (that may have been true once; it isn't
    // now). All 35 current openings render on one page. Job cards use
    // CSS-in-JS with hashed class names and no heading tags at all, so the
    // title is picked out as the innermost non-nested <span> in the card
    // (the outer spans repeat the title concatenated with "Featured" and
    // the location, which is why a plain in-link text grab wouldn't work).
    urls: ["https://revolutpeople.com/aspire/public/careers/"],
    linkPattern: /\/aspire\/public\/careers\/position\//,
    waitForSelector: 'a[href*="/position/"]',
    titleSelector: "span:not(:has(span))",
  },
  // Still need a confirmed pattern (see README "Companies not yet wired up"):
  // wefox — its main careers page (careers.wefox.com) is currently broken/
  // unreachable and its company-wide board on join.com shows zero open
  // positions, so there's nothing live to verify a scraper against right
  // now. Trade Republic turned out not to need this file at all — it runs
  // on Greenhouse under the hood, so it's wired directly into check.php's
  // existing "greenhouse" adapter instead (see php-ftp/README.md).
  //
  // Hang Seng Bank and Mubadala Investment Company were both investigated
  // for this same batch and both turned out to have a real platform behind
  // them (HSBC Group's Eightfold-powered careers portal for Hang Seng;
  // Mubadala's own "Takafo" recruiting system) — genuine public JSON search
  // APIs exist for both, confirmed by hand. But neither one's job cards
  // render as real anchor elements: both navigate purely through JS click
  // handlers (a React "position-card" div for Hang Seng, a Vuetify button
  // for Mubadala) with no href or data-id anywhere in the DOM to scrape.
  // This file's href-pattern approach fundamentally can't reach either one
  // without simulating clicks per card, which is a different (much
  // slower, much more fragile) kind of scraper than everything else here.
  // Left out of this batch; a direct check.php adapter would actually be
  // the simpler fix for these two specifically, whenever that's revisited.
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

    const roles = await page.evaluate(({ patternSource, titleSelector, titleAncestorSelector, titleAncestorTitleSelector }) => {
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
        // A few (ABN AMRO, CIMB Group) put the real title text OUTSIDE the
        // link entirely — the link itself is just a "View"/"Show" CTA — in
        // which case titleAncestorSelector finds the enclosing card via
        // a.closest(...) and titleAncestorTitleSelector picks the title out
        // of it instead.
        let title = "";
        if (titleAncestorSelector && titleAncestorTitleSelector) {
          const ancestor = a.closest(titleAncestorSelector);
          const ancestorTitleEl = ancestor ? ancestor.querySelector(titleAncestorTitleSelector) : null;
          title = ancestorTitleEl ? ancestorTitleEl.textContent || "" : "";
        }
        if (!title) {
          const titleEl = titleSelector ? a.querySelector(titleSelector) : null;
          title = (titleEl || a).textContent || "";
        }
        title = title.replace(/\s+/g, " ").trim();
        if (title.length < 3) return;
        seen.add(abs);
        out.push({ title, url: abs });
      });
      return out;
    }, {
      patternSource: company.linkPattern.source,
      titleSelector: company.titleSelector || null,
      titleAncestorSelector: company.titleAncestorSelector || null,
      titleAncestorTitleSelector: company.titleAncestorTitleSelector || null,
    });

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