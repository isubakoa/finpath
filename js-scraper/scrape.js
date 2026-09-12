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

// Ported from index.html's isRoleRelevant() — keep these three regexes
// byte-for-byte in sync with that function if it ever changes (same
// convention li-scraper/match.py already follows for its own copy).
//
// Added 2026-09: this file used to write every href matching a company's
// linkPattern straight to snapshot.json, unfiltered by title, on the theory
// that check.php/index.html would filter it on the way in anyway. That was
// true, but it meant snapshot.json carried every open role at every scraped
// company regardless of relevance — Atlassian's "all jobs" page alone was
// contributing 230 raw entries for ~1-2 that were ever actually Design/UX/
// Product-relevant, and Netflix/Google's broad search pages threatened to
// make that worse. Filtering here, at the source, keeps the file down to
// what could plausibly ever be shown, with no change in what the tracker
// actually displays (the same filter was always applied downstream).
const ALWAYS_ALLOW = /(ux engineer|ui engineer|design engineer|design technologist|creative technologist|product marketing|marketing manager)/i;
const POSITIVE = /(design|\bux\b|\bui\b|user experience|\bproduct\b|strategist|strategy|(user|customer|product) research|research (lead|manager|strategist))/i;
const NEGATIVE = /(engineer|developer|dev\b|qa\b|quality assurance|sales|marketing|legal|counsel|finance|accounting|account manager|recruit|talent acquisition|\bhr\b|human resources|data scientist|analyst|logistics|warehouse|driver|technician)/i;
function isRoleRelevant(title) {
  const t = title || "";
  if (ALWAYS_ALLOW.test(t)) return true;
  return POSITIVE.test(t) && !NEGATIVE.test(t);
}

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
    // See the settleDelayMs comment in scrapeOneUrl — this tenant's job tiles
    // render with a dead placeholder href first, then swap to the real URL.
    settleDelayMs: 2000,
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
    slug: "national-australia-bank-nab",
    // NAB's own careers page (nab.com.au/about-us/careers) links straight to
    // this same Eightfold instance, just filtered to the "nab" microsite
    // instead of "bnz" — same platform, same card/title markup, so this is
    // BNZ's entry with the microsite param swapped. The site's previous note
    // ("PageUp board") was stale; NAB moved to Eightfold at some point and
    // this is the real, current board.
    urls: ["https://nab.eightfold.ai/careers?microsite=nab&query=design"],
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
  {
    slug: "kiwibank",
    // Kiwibank's careers portal runs on parent-independent Cornerstone
    // OnDemand (kiwibankpeople.csod.com) — a genuinely JS-only board (the
    // raw HTML response is a near-empty shell). Job cards render as real
    // anchor links once the page's own JS runs, with clean title text
    // directly in the link, so no titleSelector is needed here. Only the
    // first ~18 of the site's 33 listed openings render without further
    // scrolling/interaction; a known, acceptable coverage gap.
    urls: ["https://kiwibankpeople.csod.com/ux/ats/careersite/1/home?c=kiwibankpeople"],
    linkPattern: /\/requisition\/\d+/,
    waitForSelector: 'a[href*="requisition"]',
  },
  {
    slug: "american-express",
    // careers.americanexpress.com runs on Oracle Fusion Recruiting Cloud
    // (Candidate Experience / "CX_1" site) but is wrapped in heavy
    // client-side bot-protection scripting, and unlike other companies on
    // this platform (e.g. CIMB), the raw HTML response contains no job
    // data at all — it's rendered entirely from an API call this file's
    // simple GET can't replicate, so it needs a real browser. Each job
    // card's anchor is empty (title lives in a same-card
    // <search-result-item-header>/.job-tile__title element referenced via
    // aria-labelledby rather than DOM nesting), so this reuses the
    // ancestor-selector approach already built for CIMB/ABN AMRO.
    urls: ["https://careers.americanexpress.com/en/sites/CX_1/jobs?keyword=design"],
    linkPattern: /\/en\/sites\/CX_1\/job\/\d+/,
    waitForSelector: 'a[href*="/en/sites/CX_1/job/"]',
    titleAncestorSelector: ".job-tile",
    titleAncestorTitleSelector: ".job-tile__title",
  },
  {
    slug: "standard-chartered",
    // jobs.standardchartered.com runs the modern SAP SuccessFactors Career
    // Site Builder 2.0 (a full client-rendered SPA — the raw HTML has no
    // job data, unlike the older SuccessFactors template several other
    // companies in this project turned out to be on). Once rendered, job
    // cards are plain, clean anchor links with the title as their own
    // text — no titleSelector needed.
    urls: ["https://jobs.standardchartered.com/search/?q=design"],
    linkPattern: /\/job\/[^/]+\/\d+-/,
    waitForSelector: 'a[href^="/job/"]',
  },
  {
    slug: "netflix",
    // ATS confirmed as Eightfold.ai (2026-09 research) — same platform as
    // NAB/BNZ above, just on Netflix's own vanity domain rather than the
    // shared eightfold.ai one. netflix.eightfold.ai redirects here. Real
    // per-role URLs are confirmed live (explore.jobs.netflix.net/careers/
    // job/<id>), and the search page returns embedded JSON with those same
    // IDs even though the rendered DOM needs JS. titleSelector borrowed
    // from NAB/BNZ's Eightfold instance on the assumption Eightfold reuses
    // the same generated CSS-module class scheme across deployments — that
    // assumption is UNVERIFIED for this specific tenant; check the Actions
    // log after the first real run rather than trusting this blindly.
    urls: ["https://explore.jobs.netflix.net/careers?query=Design&domain=netflix.com&sort_by=relevance"],
    linkPattern: /\/careers\/job\/\d+/,
    waitForSelector: 'a[href*="/careers/job/"]',
    titleSelector: '[class^="title-"]',
  },
  {
    slug: "google",
    // careers.google.com / google.com's own careers search (2026-09
    // research) confirmed JS-rendered with no working href on direct fetch.
    // URL, wait selector and linkPattern below are sourced from a
    // documented third-party Playwright scraper (not independently
    // rendered/verified here, since this environment can't reach Google's
    // site either) — that same source flags Google's careers site as
    // actively resistant to automated scraping. Best-effort: worth checking
    // the Actions log specifically for this one after the first real run,
    // since it's meaningfully more likely to fail than the rest of this file.
    urls: ["https://www.google.com/about/careers/applications/jobs/results?q=UX"],
    linkPattern: /\/jobs\/results\/\d+-[a-z0-9-]+/i,
    waitForSelector: "li.zE6MFb",
    titleSelector: "h2.p1N2lc",
  },
  {
    slug: "ericsson",
    // ATS confirmed as an Eightfold AI front end (2026-09 research) —
    // jobs.ericsson.com/careers, same generated platform as NAB/BNZ/Netflix
    // above. Ericsson's actual apply-flow redirects into SAP SuccessFactors
    // (career2.successfactors.eu) on submission, but that backend split
    // doesn't matter here: this scrapes Eightfold's own real, browsable
    // listing/detail pages, not SuccessFactors directly, so it isn't the
    // kind of bespoke SuccessFactors integration this project has ruled out
    // — same reasoning as Klarna's Deel-hosted board above. A target-tier
    // Principal UX/UI Designer (Bangalore) role was confirmed live at
    // research time.
    urls: ["https://jobs.ericsson.com/careers?query=Design&domain=ericsson.com&sort_by=relevance"],
    linkPattern: /\/careers\/job\/\d+/,
    waitForSelector: 'a[href*="/careers/job/"]',
    titleSelector: '[class^="title-"]',
  },
  {
    slug: "vodafone",
    // ATS confirmed as Eightfold AI (2026-09 research) — jobs.vodafone.com/careers.
    // A legacy SAP SuccessFactors board (opportunities.vodafone.com) still
    // resolves but appears to hold only closed/archived postings; SuccessFactors
    // itself is deliberately unsupported for direct integration regardless, so
    // this scrapes the current Eightfold board only, same pattern as Netflix/
    // NAB/BNZ above.
    urls: ["https://jobs.vodafone.com/careers?query=Design&domain=vodafone.com&sort_by=relevance"],
    linkPattern: /\/careers\/job\/\d+/,
    waitForSelector: 'a[href*="/careers/job/"]',
    titleSelector: '[class^="title-"]',
  },
  {
    slug: "deutsche-telekom",
    // ATS confirmed as Eightfold AI (2026-09 research) — careers.telekom.com/en,
    // evidenced by an embedded telekom-growthhub.eightfold.ai reference. Unlike
    // the other Eightfold sites in this file, job URLs here follow a
    // "/en/jobs/<slug>-<numeric-id>" pattern rather than "/careers/job/<id>" —
    // a differently-configured Eightfold deployment. titleSelector borrowed
    // from NAB/BNZ/Netflix's instance on the same unverified assumption noted
    // there — check the Actions log after the first real run.
    urls: ["https://careers.telekom.com/en/jobs?search=Design"],
    linkPattern: /\/en\/jobs\/[a-z0-9-]+-\d{6,}$/i,
    waitForSelector: 'a[href*="/en/jobs/"]',
    titleSelector: '[class^="title-"]',
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
  //
  // UBS was investigated as part of the "enterprise platforms" backlog
  // (jobs.ubs.com runs IBM/Kenexa BrassRing, confirmed via its page's own
  // meta tags) and turned out to be a different kind of dead end: it's
  // genuinely session-state-dependent rather than architecturally
  // unreachable. A fresh page load sometimes renders real job cards (real
  // anchor links, clean titles) and sometimes renders a JSON preload blob
  // with an empty job array, with no reliable way from the outside to tell
  // which one a given request will get — repeated fresh loads (no reused
  // cookies) came back empty far more often than not. A scheduled scraper
  // hitting a coin-flip page isn't worth wiring in; left out of this batch.
];

const TIMEOUT_MS = 30000;
const USER_AGENT =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36";

async function scrapeOneUrl(browser, url, company) {
  const page = await browser.newPage({ userAgent: USER_AGENT });
  try {
    try {
      await page.goto(url, { waitUntil: "networkidle", timeout: TIMEOUT_MS });
    } catch (gotoErr) {
      // American Express started failing here in production with "Timeout
      // 30000ms exceeded" waiting for networkidle. A real (non-headless,
      // interactive) browser loads the same URL and reaches idle within a
      // few seconds with the job data fully rendered, so the page itself
      // isn't broken — this is almost certainly the bot-protection layer
      // giving GitHub Actions' headless browser a slower/harder challenge
      // than an interactive one gets, not confirmed further than that.
      // Only swallow this specific timeout and fall through to
      // waitForSelector below, which gets its own fresh timeout budget to
      // wait for the job content to show up — a real navigation failure
      // (bad URL, DNS, connection refused) still fails the company loudly.
      if (!/Timeout .*exceeded/i.test(String((gotoErr && gotoErr.message) || gotoErr))) throw gotoErr;
    }
    if (company.waitForSelector) {
      // Best-effort: if the selector never shows up (page structure changed,
      // or genuinely zero roles right now), fall through and scrape whatever
      // did render rather than failing the whole page.
      await page.waitForSelector(company.waitForSelector, { timeout: TIMEOUT_MS }).catch(() => {});
    }
    if (company.settleDelayMs) {
      // Some SPA career sites (Fidelity International's Workday tenant is the
      // known case) render their job-tile <a> elements with a placeholder
      // href — literally https://community.workday.com/invalid-url, Workday's
      // own generic dead-link landing page — for one render pass before their
      // client-side router swaps in the real per-job URL a moment later.
      // waitForSelector above is satisfied the instant the tile exists, which
      // can land right in that placeholder window, so a company that hits
      // this needs one more real wait for the swap to happen before we read
      // hrefs out of the DOM. Left at 0 (skipped) for every other company —
      // most sites don't do this and the extra wait is pure wasted time for
      // them.
      await page.waitForTimeout(company.settleDelayMs);
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
        // Defense in depth against the Workday placeholder-href issue (see the
        // settleDelayMs comment above scrapeOneUrl's waitForSelector call): even
        // with the settle wait, never let this specific known-dead marker through.
        if (/community\.workday\.com\/invalid-url/i.test(abs)) return;
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

  // Title-relevance filter (see isRoleRelevant() above) — applied here,
  // after the debug log above so --debug runs still show every raw match
  // for troubleshooting a linkPattern/selector, but before anything reaches
  // snapshot.json. A company with a broad "all jobs" page (Atlassian) or an
  // unfiltered search (Google) would otherwise write hundreds of irrelevant
  // roles to the file for zero downstream benefit, since check.php/
  // index.html always filtered them right back out on the way in.
  const relevant = roles.filter((r) => isRoleRelevant(r.title));
  if (debug && relevant.length !== roles.length) {
    console.log(`[${company.slug}] ${roles.length - relevant.length} of ${roles.length} dropped as not title-relevant, ${relevant.length} kept`);
  }
  return { ok: true, roles: relevant.map((r) => ({ ...r, location: "", postedDate: null })) };
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