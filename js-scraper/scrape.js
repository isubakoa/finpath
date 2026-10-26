// js-scraper: careers boards that only render with JavaScript. Opens each
// company's page in headless Chromium, collects links matching its
// `linkPattern`, keeps the relevant titles, finds each role's location (see
// "Locations" below), and writes ../data/js-snapshot.json:
//   { "generatedAt": "...", "companies": { "<slug>": { "ok": true, "roles": [...] } } }
// check.php reads it for companies whose ats is {type: "snapshot"}.
// Run by .github/workflows/scrape.yml; locally: node scrape.js [--debug <slug>].

import { chromium } from "playwright";
import { readFileSync, writeFileSync } from "fs";
import { fileURLToPath } from "url";
import { dirname, join } from "path";

// Resolved from this file's location, not the working directory: a bare
// relative path once wrote to the wrong file for weeks while every run reported
// success.
const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const SNAPSHOT_PATH = join(__dirname, "..", "data", "js-snapshot.json");

// Ports of the app's isRoleRelevant() (same as li-scraper/match.py) -- change
// all three together. Filtering here keeps the snapshot to roles the app could
// ever show (Atlassian's all-jobs page alone is ~230 entries).
const ALWAYS_ALLOW = /(ux engineer|ui engineer|design engineer|design technologist|creative technologist|product marketing|marketing manager)/i;
const POSITIVE = /(design|\bux\b|\bui\b|user experience|\bproduct\b|strategist|strategy|(user|customer|product) research|research (lead|manager|strategist))/i;
const NEGATIVE = /(engineer|developer|dev\b|qa\b|quality assurance|sales|marketing|legal|counsel|finance|accounting|account manager|recruit|talent acquisition|\bhr\b|human resources|data scientist|analyst|logistics|warehouse|driver|technician)/i;
function isRoleRelevant(title) {
  const t = title || "";
  if (ALWAYS_ALLOW.test(t)) return true;
  return POSITIVE.test(t) && !NEGATIVE.test(t);
}

// ---- Companies ----
// Each entry: `slug` (= the company's ats.slug in data/companies.json), `urls`
// (pages that list jobs; prefer the site's own filtered URLs, e.g. ?team=...,
// over fighting pagination), and `linkPattern` (a regex for its real job URLs).
// A wrong pattern returns zero roles, not an error -- verify with
// `node scrape.js --debug <slug>`. Optional: waitForSelector, settleDelayMs,
// titleSelector (title is a child of the link), titleAncestorSelector +
// titleAncestorTitleSelector (title sits outside the link), titleStrip (a regex
// removed from each title, e.g. screen-reader text), locationSelector (+
// locationAncestorSelector, the card to search; default the link) when the
// listing shows the location in an element the generic card check misses.
const COMPANIES = [
  {
    slug: "adyen",
    // The plain vacancies page shows 5 of ~225 roles (infinite scroll); the team
    // filter URLs go straight to the relevant ones.
    urls: [
      "https://careers.adyen.com/vacancies?team=Product+Management",
      "https://careers.adyen.com/vacancies?team=Strategy+%26+Execution",
    ],
    linkPattern: /\/vacancies\/\d+-/,
    waitForSelector: 'a[href*="/vacancies/"]',
    // Card columns: title link, team, city.
    locationAncestorSelector: "li",
    locationSelector: ".vacancies-list-item > :nth-child(3)",
  },
  {
    slug: "klarna",
    // Deel-hosted board; titles are filled in client-side, so check.php's plain
    // HTML adapter can't read it.
    urls: ["https://jobs.deel.com/klarna"],
    linkPattern: /\/klarna\/job-details\/[a-f0-9-]+\/overview/,
    waitForSelector: 'a[href*="/job-details/"]',
    // The <a> wraps the whole card; the title is the <p>.
    titleSelector: "p",
  },
  {
    slug: "atlassian",
    // The full role list renders on one page; relevance filtering does the rest.
    urls: ["https://www.atlassian.com/company/careers/all-jobs"],
    linkPattern: /\/company\/careers\/details\/\d+/,
    waitForSelector: 'a[href*="/company/careers/details/"]',
    // A table: title cell, then "City or Remote".
    locationAncestorSelector: "tr",
    locationSelector: "td:nth-child(2)",
  },
  {
    slug: "fidelity-international",
    // A Workday tenant (fil.wd3), scraped rather than wired into check.php's
    // workday adapter.
    urls: ["https://fil.wd3.myworkdayjobs.com/en-US/001?q=design"],
    linkPattern: /\/en-US\/001\/job\//,
    waitForSelector: 'a[href*="/en-US/001/job/"]',
    // Workday renders a placeholder href first -- see settleDelayMs in scrapeOneUrl.
    settleDelayMs: 2000,
  },
  {
    slug: "abu-dhabi-investment-authority-adia",
    // Workable, but under a company-id URL that check.php's workable adapter doesn't use.
    urls: ["https://jobs.workable.com/company/5pvYKyK1ijbASjzk6Pg7kT/jobs-at-abu-dhabi-investment-authority"],
    linkPattern: /\/view\/[A-Za-z0-9]+\//,
    waitForSelector: 'a[href*="/view/"]',
  },
  {
    slug: "natwest-group",
    // Talemetry platform; each <a> wraps the whole card, title in p.job__title.
    urls: ["https://jobs.natwestgroup.com/search/jobs?q=design"],
    linkPattern: /\/jobs\/\d+-/,
    waitForSelector: 'a[href^="/jobs/"]',
    titleSelector: ".job__title",
  },
  {
    slug: "bank-of-new-zealand-bnz",
    // Parent NAB's Eightfold instance (bnz microsite). Title in a hashed
    // "title-..." CSS-module div inside the link.
    urls: ["https://nab.eightfold.ai/careers?microsite=bnz&query=design"],
    linkPattern: /\/careers\/job\/\d+/,
    waitForSelector: 'a[href*="/careers/job/"]',
    titleSelector: '[class^="title-"]',
  },
  {
    slug: "national-australia-bank-nab",
    // Same Eightfold instance as BNZ, nab microsite.
    urls: ["https://nab.eightfold.ai/careers?microsite=nab&query=design"],
    linkPattern: /\/careers\/job\/\d+/,
    waitForSelector: 'a[href*="/careers/job/"]',
    titleSelector: '[class^="title-"]',
  },
  {
    slug: "abn-amro",
    // The keyword filter is ignored server-side and pagination is JS-only, so this
    // only reaches page 1 (the 8 newest of ~71). The link text is just "Show
    // vacancy"; the title is an <h2> in the enclosing card.
    urls: ["https://www.werkenbijabnamro.nl/en/vacancies"],
    linkPattern: /\/en\/vacancy\/\d+/,
    waitForSelector: 'a[href*="/en/vacancy/"]',
    titleAncestorSelector: ".card-body.vacancy",
    titleAncestorTitleSelector: "h2",
  },
  {
    slug: "cimb-group",
    // Oracle Recruiting Cloud; the keyword filter works server-side. Title is a
    // sibling span of the link.
    urls: ["https://ejox.fa.ap1.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/jobs?keyword=design"],
    linkPattern: /\/hcmUI\/CandidateExperience\/en\/sites\/CX_1\/job\/\d+/,
    waitForSelector: 'a[href*="/job/"]',
    titleAncestorSelector: ".job-tile",
    titleAncestorTitleSelector: ".job-tile__title",
  },
  {
    slug: "aspire",
    // The live board is on Revolut People (via an iframe at people-jobs.com).
    // Hashed CSS-in-JS classes, no headings: the title is the innermost <span>.
    urls: ["https://revolutpeople.com/aspire/public/careers/"],
    linkPattern: /\/aspire\/public\/careers\/position\//,
    waitForSelector: 'a[href*="/position/"]',
    titleSelector: "span:not(:has(span))",
  },
  {
    slug: "kiwibank",
    // Cornerstone OnDemand, JS-only. Only the first ~18 of ~33 openings render
    // without scrolling -- accepted gap.
    urls: ["https://kiwibankpeople.csod.com/ux/ats/careersite/1/home?c=kiwibankpeople"],
    linkPattern: /\/requisition\/\d+/,
    waitForSelector: 'a[href*="requisition"]',
  },
  {
    slug: "american-express",
    // Oracle Recruiting Cloud behind bot-protection; the raw HTML has no job data.
    // Anchors are empty -- the title sits in the card, found via the ancestor
    // selectors.
    urls: ["https://careers.americanexpress.com/en/sites/CX_1/jobs?keyword=design"],
    linkPattern: /\/en\/sites\/CX_1\/job\/\d+/,
    waitForSelector: 'a[href*="/en/sites/CX_1/job/"]',
    titleAncestorSelector: ".job-tile",
    titleAncestorTitleSelector: ".job-tile__title",
  },
  {
    slug: "standard-chartered",
    // SAP SuccessFactors Career Site Builder (client-rendered). Clean anchor text.
    urls: ["https://jobs.standardchartered.com/search/?q=design"],
    linkPattern: /\/job\/[^/]+\/\d+-/,
    waitForSelector: 'a[href^="/job/"]',
  },
  {
    slug: "bmw-group",
    // Same SuccessFactors Career Site Builder as Standard Chartered. "Design" here
    // mostly means automotive/IT roles; the relevance filter handles it.
    urls: ["https://jobs.bmwgroup.com/search?q=design"],
    linkPattern: /\/job\/[^/]+\/\d+-/,
    waitForSelector: 'a[href^="/job/"]',
  },
  {
    slug: "netflix",
    // Eightfold on Netflix's own domain. titleSelector borrowed from NAB/BNZ's
    // Eightfold instance (assumed same CSS scheme -- check the Actions log).
    urls: ["https://explore.jobs.netflix.net/careers?query=Design&domain=netflix.com&sort_by=relevance"],
    linkPattern: /\/careers\/job\/\d+/,
    waitForSelector: 'a[href*="/careers/job/"]',
    titleSelector: '[class^="title-"]',
  },
  {
    slug: "google",
    // Best-effort: URL/selector from a third-party Playwright scraper, not verified
    // here, and Google resists automated scraping. Watch the Actions log.
    urls: ["https://www.google.com/about/careers/applications/jobs/results?q=UX"],
    linkPattern: /\/jobs\/results\/\d+-[a-z0-9-]+/i,
    waitForSelector: "li.zE6MFb",
    titleSelector: "h2.p1N2lc",
  },
  {
    slug: "ericsson",
    // Eightfold front end (apply flow goes to SuccessFactors, irrelevant here).
    urls: ["https://jobs.ericsson.com/careers?query=Design&domain=ericsson.com&sort_by=relevance"],
    linkPattern: /\/careers\/job\/\d+/,
    waitForSelector: 'a[href*="/careers/job/"]',
    titleSelector: '[class^="title-"]',
  },
  {
    slug: "vodafone",
    // Eightfold. The legacy SuccessFactors board only holds closed postings.
    urls: ["https://jobs.vodafone.com/careers?query=Design&domain=vodafone.com&sort_by=relevance"],
    linkPattern: /\/careers\/job\/\d+/,
    waitForSelector: 'a[href*="/careers/job/"]',
    titleSelector: '[class^="title-"]',
  },
  // Deutsche Telekom moved to check.php's `telekom` adapter (first-party JSON API,
  // also covers T-Systems).
  {
    slug: "meta",
    // Plain fetches get 429s, but a real browser loads it fine. Class names are
    // generated atomic CSS, so select the stable <h3> inside each job link.
    urls: ["https://www.metacareers.com/jobs?q=design"],
    linkPattern: /\/profile\/job_details\/\d+/,
    waitForSelector: 'a[href*="/profile/job_details/"]',
    titleSelector: "h3",
  },
  {
    slug: "citibank",
    // jobs.citi.com fronts a separate Eightfold tenant whose API shape check.php's
    // eightfold adapter doesn't speak, so the rendered page is scraped. A broad
    // "design" query brings some dev-role noise; the relevance filter handles it.
    urls: ["https://citi.eightfold.ai/careers?query=design&domain=citi.com&sort_by=relevance"],
    linkPattern: /\/careers\/job\/\d+/,
    waitForSelector: 'a[href*="/careers/job/"]',
    titleSelector: '[class^="title-"]',
  },
  {
    slug: "heineken",
    // Drupal; the keyword box is ignored, but the Job Functions facet works:
    // job_functions[0]=211 = Digital & Technology (~32 roles, 10 per page). Drupal's
    // pager param is page=0,0,N; each page is server-rendered, so the URLs are listed
    // explicitly (six pages = room for 60 roles; empty pages are harmless). Empty
    // duplicate anchors are dropped by the minimum-title-length filter.
    urls: [0, 1, 2, 3, 4, 5].map(
      (n) => `https://careers.theheinekencompany.com/job-listing?job_functions%5B0%5D=211&page=0%2C0%2C${n}`
    ),
    linkPattern: /\/job\/[^/]+\/[^/]+\/[^/]+$/i,
    waitForSelector: 'a[href*="/job/"]',
  },
  {
    slug: "telenor",
    // Telenor left Workday (its old tenant now redirects to an invalid-url page). The
    // group board aggregates every subsidiary's Teamtailor site, 20 jobs per server-
    // rendered page; links point at each subsidiary's own domain. Four pages = room
    // for 80 (43 open on 2026-10-24). End-anchored to skip /applications/new links.
    urls: [1, 2, 3, 4].map((n) => `https://careers.telenor.com/jobs?page=${n}`),
    linkPattern: /\/jobs\/\d+-[^/?#]+$/,
    waitForSelector: 'a[href*="/jobs/"]',
  },
  {
    slug: "triodos-bank",
    // SuccessFactors Career Site Builder, browser-rendered; clean title links.
    urls: ["https://careers.triodos.com/search/?q=&locationsearch=&searchResultView=LIST"],
    linkPattern: /\/job\/[^/]+\/\d+-/,
    waitForSelector: "a.jobCardTitle",
  },
  {
    slug: "backbase",
    // Webflow page fed by Teamtailor, 20 per page; Webflow's pager param is
    // b158f050_page (?page is ignored). Six pages = room for 120 (68 on 2026-10-24).
    urls: [1, 2, 3, 4, 5, 6].map((n) => `https://www.backbase.com/careers/jobs?b158f050_page=${n}`),
    linkPattern: /\/careers\/jobs\/\d+-[^/?#]+$/,
    waitForSelector: 'a[href*="/careers/jobs/"]',
  },
  {
    slug: "euronext",
    // Server-rendered job-offers list, 50 per page from page=0 (153 on 2026-10-24).
    urls: [0, 1, 2, 3, 4].map((n) => `https://www.euronext.com/en/about/careers/job-offers?page=${n}`),
    linkPattern: /\/about\/careers\/job-offers\/r\d+-/,
    waitForSelector: 'a[href*="/about/careers/job-offers/"]',
  },
  {
    slug: "nn-group",
    // English vacancies render from an API that rejects paging params; the page shows
    // the newest 10 (13 on 2026-10-24). Each card has an empty overlay link (dropped by
    // the title-length check) and a titled one whose h2 carries screen-reader text.
    urls: ["https://www.nn-careers.com/en/vacancies"],
    linkPattern: /\/en\/vacancy\/\d+\//,
    waitForSelector: 'a[href*="/en/vacancy/"] h2',
    titleSelector: "h2",
    titleStrip: /^Vacancy:\s*|\s*-\s*View vacancy$/g,
  },
  {
    slug: "aegon",
    // Drupal list, ~21 per page from page=0 (157 on 2026-10-24); pages come back empty
    // when fetched too fast outside a browser. The link wraps a logo; the title is the
    // card's h3.
    urls: [0, 1, 2, 3, 4, 5, 6, 7, 8].map((n) => `https://www.aegon.com/careers/vacancies?page=${n}`),
    linkPattern: /\/careers\/vacancies\/[^/]+\/[^/]+\/[^/]+\/[^/?#]+$/,
    waitForSelector: 'a[href*="/careers/vacancies/"]',
    titleAncestorSelector: "li",
    titleAncestorTitleSelector: ".molecule--teaser-card-row--title",
  },
  {
    slug: "goldman-sachs",
    // higher.gs.com, browser-rendered over GraphQL; 20 per page, relevance-sorted.
    // The link holds title + location spans; the first span is the title.
    urls: [1, 2, 3].map((n) => `https://higher.gs.com/results?page=${n}&search=design&sort=RELEVANCE`),
    linkPattern: /\/roles\/\d+$/,
    waitForSelector: 'a[href^="/roles/"]',
    titleSelector: "span.gs-text",
  },
  {
    slug: "morgan-stanley",
    // Eightfold; its API 403s outside the page (even in a browser), so the rendered
    // list is read like Ericsson/Vodafone.
    urls: ["https://morganstanley.eightfold.ai/careers?query=design&domain=morganstanley.com&sort_by=relevance"],
    linkPattern: /\/careers\/job\/\d+/,
    waitForSelector: 'a[href*="/careers/job/"]',
    titleSelector: '[class^="title-"]',
  },
  {
    slug: "unilever",
    // Oracle Taleo (not given a direct adapter, by policy). The keyword filter works
    // server-side; "design" returns packaging/engineering roles. Title is an
    // <h2 class="global-job-list__title"> inside the link.
    urls: ["https://careers.unilever.com/en/search-jobs/design"],
    linkPattern: /\/en\/job\/[^/]+\/[^/]+\/\d+\/\d+$/i,
    waitForSelector: 'a[href*="/en/job/"]',
    titleSelector: "h2.global-job-list__title",
  },
  {
    slug: "transavia",
    // White-labeled Recruitee board (no check.php adapter). Each card has several
    // /o/<slug> links; the first carries the title and this scraper keeps the first
    // match per URL. The pattern is end-anchored to skip the locale-switch links
    // (they have a query string).
    urls: ["https://werkenbijtransavia.com/vacatures"],
    linkPattern: /\/o\/[a-z0-9-]+$/i,
    waitForSelector: 'a[href^="/o/"]',
  },
  {
    slug: "vanderlande",
    // WordPress with a careers API that wasn't reachable by plain fetch; the
    // rendered page works. ?vacancy_keyword= filters server-side. Job cards share a
    // wrapper class with blog cards, hence the /all-jobs/ anchor; title in <h3>.
    urls: ["https://careers.vanderlande.com/all-jobs/?vacancy_keyword=design"],
    linkPattern: /\/all-jobs\/[a-z0-9-]+\/?$/i,
    waitForSelector: "a.new-project",
    titleSelector: "h3",
  },
  {
    slug: "tomtom",
    // TomTom's own careers API (no adapter type for it); monitored via the rendered
    // page. Title in p.headline3.
    urls: ["https://www.tomtom.com/careers/joboverview/"],
    linkPattern: /\/careers\/jobdetails\/[a-f0-9-]+\/[a-z0-9-]+\/?$/i,
    waitForSelector: 'a[href*="/careers/jobdetails/"]',
    titleSelector: "p.headline3",
  },
  {
    slug: "kpmg",
    // KPMG Netherlands (werkenbijkpmg.nl). The ?s= filter is ignored; the full
    // vacancy list is public at /_lunr/vacancies, which showed no product/UX roles
    // (2026-10-22). Monitored via the rendered page; title in <h3>.
    urls: ["https://www.werkenbijkpmg.nl/vacatures"],
    linkPattern: /\/vacature\/[a-z0-9-]+$/i,
    waitForSelector: 'a[href^="/vacature/"]',
    titleSelector: "h3",
  },
  {
    slug: "bunq",
    // Framer site with the full list in the raw HTML. Each <a> wraps an <article>;
    // the title is <h3 data-framer-name="Title">.
    urls: ["https://careers.bunq.com/positions"],
    linkPattern: /\/positions\/[a-z0-9-]+$/i,
    waitForSelector: 'a[href*="/positions/"]',
    titleSelector: 'h3[data-framer-name="Title"]',
  },
  {
    slug: "vodafoneziggo",
    // Server-rendered list, 8 per page (38 roles on 2026-10-24); ?page=N pages it.
    // Each card has a plain title link.
    urls: [1, 2, 3, 4, 5, 6].map((n) => `https://careers.vodafoneziggo.com/vacatures/filters/sort/date:desc?page=${n}`),
    linkPattern: /\/vacatures\/[a-z0-9-]+-\d+$/,
    waitForSelector: 'a[href*="/vacatures/"]',
  },
  {
    slug: "odido",
    // Serena CMS, rendered from its own API, 10 per page with no URL paging. 36 of
    // ~59 roles are shop jobs, so read the other fields, each of which fits on one
    // page. The title link comes before the "Bekijk vacature" link to the same url.
    urls: ["corporate-support-1", "marketing-en-communicatie-1", "sales-1", "finance-2"].map(
      (f) => `https://werkenbij.odido.nl/vacatures/vakgebied-1/${f}`,
    ),
    linkPattern: /\/vacature\/\d+\/[a-z0-9-]+$/,
    waitForSelector: 'a[href*="/vacature/"]',
  },
  {
    slug: "sky",
    // careers.sky.com renders its Workday jobs client-side; each search shows every
    // match. The link wraps title, team and location; the title div's class is hashed.
    urls: ["design", "product", "UX", "research"].map((q) => `https://careers.sky.com/jobs?search=${q}`),
    linkPattern: /\/jobs\/t-R\d+$/,
    waitForSelector: 'a[href*="/jobs/t-"]',
    titleSelector: '[class^="jobTitle_"]',
  },
  // Not scraped:
  //   - wefox: careers site broken, no open roles on its join.com board.
  //   - Hang Seng Bank, Mubadala: job cards are JS click handlers with no href to
  //     collect; a direct check.php adapter (both have public JSON APIs) would be
  //     the better fix.
  //   - UBS: BrassRing board that randomly renders empty -- not worth scheduling.
];

const TIMEOUT_MS = 30000;
const USER_AGENT =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36";

// ---- Locations ----
// The app filters roles by location, so a role without one can't be filtered
// out. Each role's location comes from, in order:
//   1. the listing: locationSelector, else any element in the job's card whose
//      class/id/itemprop/data-* says "location" (as check.php's html adapter);
//   2. the previous snapshot, for a url already resolved on an earlier run;
//   3. the posting page itself: its schema.org JobPosting data (Eightfold, Meta,
//      Teamtailor, Workday...), else a "Location: ..." line in its text.
// Step 3 opens one page per new role, at most MAX_POSTING_LOOKUPS per run (the
// rest wait for the next run), and stops early for a company whose postings
// keep showing no location.
const MAX_POSTING_LOOKUPS = 80;
const POSTING_MISSES_BEFORE_GIVING_UP = 3;
const POSTING_SETTLE_MS = 1500;
const regionNames = new Intl.DisplayNames(["en"], { type: "region" });

// "NO" -> "Norway", so the app's country matching works; anything else as is.
function countryName(value) {
  const v = String(value || "").trim();
  if (/^[A-Z]{2}$/.test(v)) {
    try {
      return regionNames.of(v) || v;
    } catch {
      return v;
    }
  }
  return v;
}

// What some cards show in place of a location ("Hybrid", "All locations"): treated
// as none, so the posting page is read instead.
const PLACELESS = /^(fully\s+)?(remote|hybrid|on-?site|in office|flexible|all locations|multiple locations|various locations)$/i;

function cleanLocation(text) {
  const t = String(text || "").replace(/\s+/g, " ").replace(/^locations?\s*:?\s*/i, "").trim();
  return PLACELESS.test(t) ? "" : t;
}

function previousLocations() {
  try {
    const previous = JSON.parse(readFileSync(SNAPSHOT_PATH, "utf8"));
    const byUrl = {};
    Object.values(previous.companies || {}).forEach((c) => {
      (c.roles || []).forEach((r) => {
        if (r.url && cleanLocation(r.location)) byUrl[r.url] = r.location;
      });
    });
    return byUrl;
  } catch {
    return {}; // first run, or an unreadable file: everything is looked up
  }
}

async function scrapeOneUrl(browser, url, company) {
  const page = await browser.newPage({ userAgent: USER_AGENT });
  try {
    try {
      await page.goto(url, { waitUntil: "networkidle", timeout: TIMEOUT_MS });
    } catch (gotoErr) {
      // Swallow only the networkidle timeout (bot protection makes headless loads
      // slow; Amex did this in production) and let waitForSelector below wait for the
      // content. Real navigation failures still fail the company.
      if (!/Timeout .*exceeded/i.test(String((gotoErr && gotoErr.message) || gotoErr))) throw gotoErr;
    }
    if (company.waitForSelector) {
      // Best-effort: if the selector never appears, scrape whatever rendered.
      await page.waitForSelector(company.waitForSelector, { timeout: TIMEOUT_MS }).catch(() => {});
    }
    if (company.settleDelayMs) {
      // Some SPAs (Fidelity's Workday) render job links with a placeholder href
      // (community.workday.com/invalid-url) before swapping in the real URL; give
      // those companies a moment before reading hrefs. 0 (skipped) for everyone else.
      await page.waitForTimeout(company.settleDelayMs);
    }

    const roles = await page.evaluate(({ patternSource, titleSelector, titleAncestorSelector, titleAncestorTitleSelector, locationSelector, locationAncestorSelector }) => {
      const pattern = new RegExp(patternSource);
      const absolute = (a) => {
        try {
          return new URL(a.getAttribute("href") || "", location.href).href;
        } catch {
          return "";
        }
      };
      const clean = (t) => (t || "").replace(/\s+/g, " ").trim();
      // The job's card: the largest ancestor of the link holding no other job link.
      const cardOf = (a, abs) => {
        let card = a;
        for (let depth = 0; depth < 8; depth++) {
          const parent = card.parentElement;
          if (!parent || parent === document.body) break;
          const other = [...parent.querySelectorAll("a[href]")].some((x) => {
            const h = absolute(x);
            return h !== abs && pattern.test(h);
          });
          if (other) break;
          card = parent;
        }
        return card;
      };
      const cardLocation = (card, title) => {
        for (const el of card.querySelectorAll("*")) {
          const marker = [...el.attributes]
            .filter((at) => ["class", "id", "itemprop"].includes(at.name) || at.name.startsWith("data-"))
            .map((at) => `${at.name} ${at.value}`)
            .join(" ");
          if (!/location/i.test(marker) || /relocation/i.test(marker)) continue;
          const text = clean(el.textContent).replace(/^locations?\s*:?\s*/i, "");
          if (text.length >= 2 && text.length <= 120 && text !== title) return text;
        }
        return "";
      };
      const seen = new Set();
      const out = [];
      document.querySelectorAll("a[href]").forEach((a) => {
        const abs = absolute(a);
        if (!abs || !pattern.test(abs) || seen.has(abs)) return;
        // Never let the Workday placeholder through, even after the settle wait.
        if (/community\.workday\.com\/invalid-url/i.test(abs)) return;
        // Title: the link's own text by default; titleSelector for a child element
        // when the link wraps a whole card; titleAncestorSelector +
        // titleAncestorTitleSelector when the link is just a CTA and the title lives in
        // the enclosing card.
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
        title = clean(title);
        if (title.length < 3) return;
        let loc = "";
        if (locationSelector) {
          const scope = locationAncestorSelector ? a.closest(locationAncestorSelector) : a;
          const el = scope ? scope.querySelector(locationSelector) : null;
          loc = el ? clean(el.textContent) : "";
        } else {
          loc = cardLocation(cardOf(a, abs), title);
        }
        seen.add(abs);
        out.push({ title, url: abs, location: loc });
      });
      return out;
    }, {
      patternSource: company.linkPattern.source,
      titleSelector: company.titleSelector || null,
      titleAncestorSelector: company.titleAncestorSelector || null,
      titleAncestorTitleSelector: company.titleAncestorTitleSelector || null,
      locationSelector: company.locationSelector || null,
      locationAncestorSelector: company.locationAncestorSelector || null,
    });

    await page.close();
    return roles;
  } catch (err) {
    await page.close().catch(() => {});
    throw err;
  }
}

// Step 3 of "Locations": the location a posting page states, or "".
async function postingLocation(browser, url) {
  const page = await browser.newPage({ userAgent: USER_AGENT });
  try {
    await page.goto(url, { waitUntil: "domcontentloaded", timeout: TIMEOUT_MS });
    await page
      .waitForFunction(() => document.querySelector('script[type="application/ld+json"]') || document.body.innerText.length > 800, null, { timeout: 10000 })
      .catch(() => {});
    await page.waitForTimeout(POSTING_SETTLE_MS);
    const found = await page.evaluate(() => {
      const places = [];
      const visit = (node) => {
        if (!node || typeof node !== "object") return;
        if (Array.isArray(node)) return node.forEach(visit);
        if ([].concat(node["@type"] || []).includes("JobPosting")) {
          [].concat(node.jobLocation || []).forEach((place) => {
            const address = place && place.address;
            if (typeof address === "string") return places.push(address);
            if (!address) return;
            const country = address.addressCountry && typeof address.addressCountry === "object" ? address.addressCountry.name : address.addressCountry;
            places.push({ city: address.addressLocality || "", country: country || "" });
          });
          if (!places.length && /TELECOMMUTE/i.test(String(node.jobLocationType || ""))) places.push("Remote");
        }
        if (node["@graph"]) visit(node["@graph"]);
      };
      document.querySelectorAll('script[type="application/ld+json"]').forEach((s) => {
        try {
          visit(JSON.parse(s.textContent));
        } catch {
          // malformed JSON-LD: ignore that block
        }
      });
      if (places.length) return { places };
      // A labelled line: "Location: Amsterdam" / "Job Location (Long): ..." (the value
      // may sit on the next line), "Location London", or Material's "location_on" icon
      // text followed by the value.
      const text = (document.querySelector("main") || document.body).innerText;
      const patterns = [
        /^[ \t]*(?:job\s+|office\s+)?location(?:s|\(s\))?(?:\s*\(long\))?[ \t]*:\s*([^\n]{2,100})/im,
        /^[ \t]*(?:job\s+)?location[ \t]+([^\n]{2,100})$/im,
        /^[ \t]*location_on[ \t]*\n\s*([^\n]{2,100})/im,
      ];
      for (const re of patterns) {
        const m = text.match(re);
        if (m) return { text: m[1] };
      }
      return {};
    });
    await page.close();
    if (found.places) {
      const labels = found.places.map((p) =>
        typeof p === "string" ? cleanLocation(p) : [cleanLocation(p.city), countryName(p.country)].filter(Boolean).join(", "),
      );
      return [...new Set(labels.filter(Boolean))].join("; ");
    }
    return found.text ? cleanLocation(found.text) : "";
  } catch {
    await page.close().catch(() => {});
    return "";
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
        // Optional per-company cleanup of boilerplate around the title.
        if (company.titleStrip) r.title = r.title.replace(company.titleStrip, "").trim();
        roles.push(r);
      });
    } catch (err) {
      errors.push(`${url}: ${String((err && err.message) || err)}`);
    }
  }

  if (debug) {
    console.log(`[${company.slug}] ${roles.length} matching link(s) found across ${urls.length} URL(s):`);
    roles.forEach((r) => console.log(`  - ${r.title}  [${r.location || "no location on the listing"}]  ->  ${r.url}`));
    if (errors.length) errors.forEach((e) => console.log(`  ! ${e}`));
  }

  // Fail a company only if every one of its URLs failed; keep partial results.
  if (roles.length === 0 && errors.length === urls.length && urls.length > 0) {
    return { ok: false, error: errors.join("; ") };
  }

  // Relevance filter after the debug log (so --debug shows every raw match) and
  // before the snapshot is written.
  const relevant = roles.filter((r) => isRoleRelevant(r.title));
  if (debug && relevant.length !== roles.length) {
    console.log(`[${company.slug}] ${roles.length - relevant.length} of ${roles.length} dropped as not title-relevant, ${relevant.length} kept`);
  }
  return { ok: true, roles: relevant.map((r) => ({ title: r.title, url: r.url, location: cleanLocation(r.location), postedDate: null })) };
}

// Steps 2 and 3 of "Locations", for roles whose listing showed none.
async function fillLocations(browser, companies, known) {
  let lookups = 0;
  for (const [slug, result] of Object.entries(companies)) {
    if (!result.ok) continue;
    let misses = 0;
    for (const role of result.roles) {
      if (role.location) continue;
      if (known[role.url]) {
        role.location = known[role.url];
        continue;
      }
      if (lookups >= MAX_POSTING_LOOKUPS || misses >= POSTING_MISSES_BEFORE_GIVING_UP) continue;
      lookups++;
      role.location = await postingLocation(browser, role.url);
      misses = role.location ? 0 : misses + 1;
    }
    const located = result.roles.filter((r) => r.location).length;
    if (result.roles.length) console.log(`  ${slug}: location for ${located} of ${result.roles.length} role(s)`);
  }
  console.log(`Posting pages opened for locations: ${lookups} (max ${MAX_POSTING_LOOKUPS} per run).`);
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
  console.log("\nLocations:");
  await fillLocations(browser, companies, debug ? {} : previousLocations());
  if (debug) Object.values(companies).forEach((r) => (r.roles || []).forEach((role) => console.log(`  - ${role.title}  [${role.location || "none found"}]`)));
  await browser.close();

  if (!debug) {
    const snapshot = { generatedAt: new Date().toISOString(), companies };
    writeFileSync(SNAPSHOT_PATH, JSON.stringify(snapshot, null, 2));
    console.log(`\nWrote ${SNAPSHOT_PATH} (${Object.keys(companies).length} compan${Object.keys(companies).length === 1 ? "y" : "ies"}).`);
  }
}

main();
