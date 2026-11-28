import { chromium } from "playwright";
import { mkdirSync, readFileSync, writeFileSync } from "fs";
import { fileURLToPath } from "url";
import { dirname, join } from "path";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const SNAPSHOT_PATH = join(__dirname, "..", "data", "js-snapshot.json");
const DEBUG_DIR = join(__dirname, "debug");

const ALWAYS_ALLOW = /(ux engineer|ui engineer|design engineer|design technologist|creative technologist|product marketing|marketing manager)/i;
const POSITIVE = /(design|\bux\b|\bui\b|user experience|\bproduct\b|strategist|strategy|(user|customer|product) research|research (lead|manager|strategist))/i;
const NEGATIVE = /(engineer|developer|dev\b|qa\b|quality assurance|sales|marketing|legal|counsel|finance|accounting|account manager|recruit|talent acquisition|\bhr\b|human resources|data scientist|analyst|logistics|warehouse|driver|technician)/i;
function isRoleRelevant(title) {
  const t = title || "";
  if (ALWAYS_ALLOW.test(t)) return true;
  return POSITIVE.test(t) && !NEGATIVE.test(t);
}

const COMPANIES = [
  {
    slug: "adyen",
    urls: [
      "https://careers.adyen.com/vacancies?team=Product+Management",
      "https://careers.adyen.com/vacancies?team=Strategy+%26+Execution",
    ],
    linkPattern: /\/vacancies\/\d+-/,
    waitForSelector: 'a[href*="/vacancies/"]',
    locationAncestorSelector: "li",
    locationSelector: ".vacancies-list-item > :nth-child(3)",
  },
  {
    slug: "klarna",
    urls: ["https://jobs.deel.com/klarna"],
    linkPattern: /\/klarna\/job-details\/[a-f0-9-]+\/overview/,
    waitForSelector: 'a[href*="/job-details/"]',
    titleSelector: "p",
  },
  {
    slug: "atlassian",
    urls: ["https://www.atlassian.com/company/careers/all-jobs"],
    linkPattern: /\/company\/careers\/details\/\d+/,
    waitForSelector: 'a[href*="/company/careers/details/"]',
    locationAncestorSelector: "tr",
    locationSelector: "td:nth-child(2)",
  },
  {
    slug: "fidelity-international",
    urls: ["https://fil.wd3.myworkdayjobs.com/en-US/001?q=design"],
    linkPattern: /\/en-US\/001\/job\//,
    waitForSelector: 'a[href*="/en-US/001/job/"]',
    settleDelayMs: 2000,
  },
  {
    slug: "abu-dhabi-investment-authority-adia",
    urls: ["https://jobs.workable.com/company/5pvYKyK1ijbASjzk6Pg7kT/jobs-at-abu-dhabi-investment-authority"],
    linkPattern: /\/view\/[A-Za-z0-9]+\//,
    waitForSelector: 'a[href*="/view/"]',
  },

  {
    slug: "bank-of-new-zealand-bnz",
    urls: ["https://nab.eightfold.ai/careers?microsite=bnz&query=design"],
    linkPattern: /\/careers\/job\/\d+/,
    waitForSelector: 'a[href*="/careers/job/"]',
    titleSelector: '[class^="title-"]',
  },
  {
    slug: "national-australia-bank-nab",
    urls: ["https://nab.eightfold.ai/careers?microsite=nab&query=design"],
    linkPattern: /\/careers\/job\/\d+/,
    waitForSelector: 'a[href*="/careers/job/"]',
    titleSelector: '[class^="title-"]',
  },
  {
    slug: "abn-amro",
    urls: ["https://www.werkenbijabnamro.nl/en/vacancies"],
    linkPattern: /\/en\/vacancy\/\d+/,
    waitForSelector: 'a[href*="/en/vacancy/"]',
    titleAncestorSelector: ".card-body.vacancy",
    titleAncestorTitleSelector: "h2",
  },
  {
    slug: "cimb-group",
    urls: ["https://ejox.fa.ap1.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/jobs?keyword=design"],
    linkPattern: /\/hcmUI\/CandidateExperience\/en\/sites\/CX_1\/job\/\d+/,
    waitForSelector: 'a[href*="/job/"]',
    titleAncestorSelector: ".job-tile",
    titleAncestorTitleSelector: ".job-tile__title",
  },

  {
    slug: "kiwibank",
    urls: ["https://kiwibankpeople.csod.com/ux/ats/careersite/1/home?c=kiwibankpeople"],
    linkPattern: /\/requisition\/\d+/,
    waitForSelector: 'a[href*="requisition"]',
  },
  {
    slug: "american-express",
    urls: ["https://careers.americanexpress.com/en/sites/CX_1/jobs?keyword=design"],
    linkPattern: /\/en\/sites\/CX_1\/job\/\d+/,
    waitForSelector: 'a[href*="/en/sites/CX_1/job/"]',
    titleAncestorSelector: ".job-tile",
    titleAncestorTitleSelector: ".job-tile__title",
  },
  {
    slug: "standard-chartered",
    urls: ["https://jobs.standardchartered.com/search/?q=design"],
    linkPattern: /\/job\/[^/]+\/\d+-/,
    waitForSelector: 'a[href^="/job/"]',
  },
  {
    slug: "bmw-group",
    urls: ["https://jobs.bmwgroup.com/search?q=design"],
    linkPattern: /\/job\/[^/]+\/\d+-/,
    waitForSelector: 'a[href^="/job/"]',
  },

  {
    slug: "google",
    urls: ["https://www.google.com/about/careers/applications/jobs/results?q=UX"],
    linkPattern: /\/jobs\/results\/\d+-[a-z0-9-]+/i,
    waitForSelector: 'a[href*="jobs/results/"]',
    titleAncestorSelector: "li",
    titleAncestorTitleSelector: "h3",
  },
  {
    slug: "ericsson",
    urls: ["https://jobs.ericsson.com/careers?query=Design&domain=ericsson.com&sort_by=relevance"],
    linkPattern: /\/careers\/job\/\d+/,
    waitForSelector: 'a[href*="/careers/job/"]',
    titleSelector: '[class^="title-"]',
  },
  {
    slug: "vodafone",
    urls: ["https://jobs.vodafone.com/careers?query=Design&domain=vodafone.com&sort_by=relevance"],
    linkPattern: /\/careers\/job\/\d+/,
    waitForSelector: 'a[href*="/careers/job/"]',
    titleSelector: '[class^="title-"]',
  },
  {
    slug: "meta",
    urls: ["https://www.metacareers.com/jobs?q=design"],
    linkPattern: /\/profile\/job_details\/\d+/,
    waitForSelector: 'a[href*="/profile/job_details/"]',
    titleSelector: "h3",
  },
  {
    slug: "citibank",
    urls: ["https://citi.eightfold.ai/careers?query=design&domain=citi.com&sort_by=relevance"],
    linkPattern: /\/careers\/job\/\d+/,
    waitForSelector: 'a[href*="/careers/job/"]',
    titleSelector: '[class^="title-"]',
  },
  {
    slug: "heineken",
    urls: [0, 1, 2, 3, 4, 5].map(
      (n) => `https://careers.theheinekencompany.com/job-listing?job_functions%5B0%5D=211&page=0%2C0%2C${n}`
    ),
    linkPattern: /\/job\/[^/]+\/[^/]+\/[^/]+$/i,
    waitForSelector: 'a[href*="/job/"]',
  },
  {
    slug: "telenor",
    urls: [1, 2, 3, 4].map((n) => `https://careers.telenor.com/jobs?page=${n}`),
    linkPattern: /\/jobs\/\d+-[^/?#]+$/,
    waitForSelector: 'a[href*="/jobs/"]',
  },
  {
    slug: "triodos-bank",
    urls: ["https://careers.triodos.com/search/?q=&locationsearch=&searchResultView=LIST"],
    linkPattern: /\/job\/[^/]+\/\d+-/,
    waitForSelector: "a.jobCardTitle",
  },
  {
    slug: "backbase",
    urls: [1, 2, 3, 4, 5, 6].map((n) => `https://www.backbase.com/careers/jobs?b158f050_page=${n}`),
    linkPattern: /\/careers\/jobs\/\d+-[^/?#]+$/,
    waitForSelector: 'a[href*="/careers/jobs/"]',
  },
  {
    slug: "euronext",
    urls: [0, 1, 2, 3, 4].map((n) => `https://www.euronext.com/en/about/careers/job-offers?page=${n}`),
    linkPattern: /\/about\/careers\/job-offers\/r\d+-/,
    waitForSelector: 'a[href*="/about/careers/job-offers/"]',
  },
  {
    slug: "nn-group",
    urls: ["https://www.nn-careers.com/en/vacancies"],
    linkPattern: /\/en\/vacancy\/\d+\//,
    waitForSelector: 'a[href*="/en/vacancy/"] h2',
    titleSelector: "h2",
    titleStrip: /^Vacancy:\s*|\s*-\s*View vacancy$/g,
  },
  {
    slug: "aegon",
    urls: [0, 1, 2, 3, 4, 5, 6, 7, 8].map((n) => `https://www.aegon.com/careers/vacancies?page=${n}`),
    linkPattern: /\/careers\/vacancies\/[^/]+\/[^/]+\/[^/]+\/[^/?#]+$/,
    waitForSelector: 'a[href*="/careers/vacancies/"]',
    titleAncestorSelector: "li",
    titleAncestorTitleSelector: ".molecule--teaser-card-row--title",
  },
  {
    slug: "goldman-sachs",
    urls: [1, 2, 3].map((n) => `https://higher.gs.com/results?page=${n}&search=design&sort=RELEVANCE`),
    linkPattern: /\/roles\/\d+$/,
    waitForSelector: 'a[href^="/roles/"]',
    titleSelector: "span.gs-text",
  },
  {
    slug: "morgan-stanley",
    urls: ["https://morganstanley.eightfold.ai/careers?query=design&domain=morganstanley.com&sort_by=relevance"],
    linkPattern: /\/careers\/job\/\d+/,
    waitForSelector: 'a[href*="/careers/job/"]',
    titleSelector: '[class^="title-"]',
  },
  {
    slug: "unilever",
    urls: ["https://careers.unilever.com/en/search-jobs/design"],
    linkPattern: /\/en\/job\/[^/]+\/[^/]+\/\d+\/\d+$/i,
    waitForSelector: 'a[href*="/en/job/"]',
    titleSelector: "h2.global-job-list__title",
  },
  {
    slug: "transavia",
    urls: ["https://werkenbijtransavia.com/vacatures"],
    linkPattern: /\/o\/[a-z0-9-]+$/i,
    waitForSelector: 'a[href^="/o/"]',
  },
  {
    slug: "vanderlande",
    urls: ["https://careers.vanderlande.com/all-jobs/?vacancy_keyword=design"],
    linkPattern: /\/all-jobs\/[a-z0-9-]+\/?$/i,
    waitForSelector: "a.new-project",
    titleSelector: "h3",
  },
  {
    slug: "tomtom",
    urls: ["https://www.tomtom.com/careers/joboverview/"],
    linkPattern: /\/careers\/jobdetails\/[a-f0-9-]+\/[a-z0-9-]+\/?$/i,
    waitForSelector: 'a[href*="/careers/jobdetails/"]',
    titleSelector: "p.headline3",
  },
  {
    slug: "kpmg",
    urls: ["https://www.werkenbijkpmg.nl/vacatures"],
    linkPattern: /\/vacature\/[a-z0-9-]+$/i,
    waitForSelector: 'a[href^="/vacature/"]',
    titleSelector: "h3",
  },
  {
    slug: "bunq",
    urls: ["https://careers.bunq.com/positions"],
    linkPattern: /\/positions\/[a-z0-9-]+$/i,
    waitForSelector: 'a[href*="/positions/"]',
    titleSelector: 'h3[data-framer-name="Title"]',
  },
  {
    slug: "vodafoneziggo",
    urls: [1, 2, 3, 4, 5, 6].map((n) => `https://careers.vodafoneziggo.com/vacatures/filters/sort/date:desc?page=${n}`),
    linkPattern: /\/vacatures\/[a-z0-9-]+-\d+$/,
    waitForSelector: 'a[href*="/vacatures/"]',
  },
  {
    slug: "odido",
    urls: ["corporate-support-1", "marketing-en-communicatie-1", "sales-1", "finance-2"].map(
      (f) => `https://werkenbij.odido.nl/vacatures/vakgebied-1/${f}`,
    ),
    linkPattern: /\/vacature\/\d+\/[a-z0-9-]+$/,
    waitForSelector: 'a[href*="/vacature/"]',
  },
  {
    slug: "sky",
    urls: ["design", "product", "UX", "research"].map((q) => `https://careers.sky.com/jobs?search=${q}`),
    linkPattern: /\/jobs\/t-R\d+$/,
    waitForSelector: 'a[href*="/jobs/t-"]',
    titleSelector: '[class^="jobTitle_"]',
  },
  {
    slug: "xero",
    urls: ["https://careers.xero.com/jobs/"],
    linkPattern: /\/jobs\/[a-f0-9-]{36}\//,
    waitForSelector: 'a[href*="/jobs/"]',
  },
  {
    slug: "grab-grab-financial-group",
    urls: ["https://www.grab.careers/en/teams/ux-and-design/"],
    linkPattern: /\/en\/jobs\/\d+\//,
    waitForSelector: 'a[href*="/en/jobs/"]',
  },
  {
    slug: "rabobank",
    urls: ["https://rabobank.jobs/en/search/?q=design"],
    linkPattern: /\/en\/job\/[^/]+\/JR_\d+\//i,
    waitForSelector: 'a[href*="/en/job/"]',
  },
  {
    slug: "optus",
    urls: Array.from({ length: 15 }, (_, i) => `https://careers.optus.com.au/jobs/page/${i + 1}`),
    linkPattern: /careers\.optus\.com\.au\/[a-z0-9-]+\/job\/\d+$/,
    waitForSelector: 'a[href*="/job/"]',
  },
  {
    slug: "lloyds-banking-group",
    urls: ["https://www.lloydsbankinggroup.com/careers/job-search.html?t=design"],
    linkPattern: /\/careers\/job-search\/workday-job\.\d+\.html/,
    waitForSelector: 'a[href*="workday-job."] .job-title',
    titleSelector: ".job-title",
    locationSelector: ".data-location .value",
  },
  {
    slug: "siemens",
    urls: ["design", "UX", "product+manager"].map((q) => `https://jobs.siemens.com/en_US/externaljobs/SearchJobs/?search=${q}`),
    linkPattern: /\/externaljobs\/JobDetail\/\d+$/,
    waitForSelector: 'a[href*="/JobDetail/"]',
  },
  {
    slug: "virgin-media-o2",
    urls: Array.from({ length: 16 }, (_, i) => `https://jobs.virginmediao2.co.uk/en_US/careersmarketplace/SearchJobs?search=design&jobOffset=${i * 8}`),
    linkPattern: /\/careersmarketplace\/JobDetail\/[^/]+\/\d+$/,
    waitForSelector: 'a[href*="/JobDetail/"]',
  },
  {
    slug: "viasat",
    urls: ["design", "product"].flatMap((q) => ["Singapore", "United Kingdom"].map((l) =>
      `https://careers.viasat.com/jobs?keywords=${q}&location=${encodeURIComponent(l)}&page=1`)),
    linkPattern: /careers\.viasat\.com\/jobs\/\d+\?lang=/,
    waitForSelector: 'a[href*="/jobs/"][href*="lang="]',
  },
  {
    slug: "lebara",
    urls: ["https://www.lebara.de/en/ueber-lebara/stellenangebote.html"],
    linkPattern: /api\.occupop\.com\/job\/application\/[a-z0-9-]+/,
    waitForSelector: 'a[href*="occupop.com/job/application/"]',
  },
  {
    slug: "revolut",
    urls: ["https://www.revolut.com/careers/"],
    pageData: (data) => {
      const positions = (data && data.props && data.props.pageProps && data.props.pageProps.positions) || [];
      const slug = (t) => t.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
      return positions.filter((p) => p && p.id && p.text).map((p) => ({
        title: p.text.trim(),
        url: `https://www.revolut.com/careers/position/${slug(p.text)}-${p.id}/`,
        location: [...new Set((p.locations || []).map((l) =>
          l.type === "remote" ? `Remote, ${l.country || ""}`.replace(/, $/, "") : [l.name, l.country].filter(Boolean).join(", ")))].join("; "),
      }));
    },
  },
  {
    slug: "hyperoptic",
    urls: ["https://careers.hyperoptic.com/jobs/home/"],
    clickSelector: 'a[href*="posbrowser_resetto/?pagestamp="]',
    linkPattern: /careers\.hyperoptic\.com\/jobs\/vacancy\/[^/]+\/\d+\/description\//,
    waitForSelector: 'a[href*="/description/"]',
  },
  {
    slug: "mercari",
    urls: ["https://careers.mercari.com/en/jobs/"],
    linkPattern: /mercari\.workable\.com\/jobs\/\d+/,
    waitForSelector: 'a[href*="mercari.workable.com/jobs/"]',
    fixedLocation: "Tokyo, Japan",
  },
];

const TIMEOUT_MS = 30000;
const USER_AGENT =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36";

const MAX_POSTING_LOOKUPS = 80;
const POSTING_MISSES_BEFORE_GIVING_UP = 3;
const POSTING_SETTLE_MS = 1500;
const regionNames = new Intl.DisplayNames(["en"], { type: "region" });

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
    return {};
  }
}

const BLOCK_TITLE = /just a moment|security check|attention required|access denied|are you a robot|pardon our interruption/i;

const collectLinks = ({ patternSource, titleSelector, titleAncestorSelector, titleAncestorTitleSelector, locationSelector, locationAncestorSelector }) => {
  const pattern = new RegExp(patternSource);
  const absolute = (a) => {
    try {
      return new URL(a.getAttribute("href") || "", document.baseURI).href;
    } catch {
      return "";
    }
  };
  const clean = (t) => (t || "").replace(/\s+/g, " ").trim();
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
    if (/community\.workday\.com\/invalid-url/i.test(abs)) return;
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
};

async function saveDebug(page, company, index, info) {
  try {
    mkdirSync(DEBUG_DIR, { recursive: true });
    const base = join(DEBUG_DIR, `${company.slug}-${index + 1}`);
    await page.screenshot({ path: `${base}.png`, fullPage: false }).catch(() => {});
    writeFileSync(`${base}.json`, JSON.stringify(info, null, 2));
  } catch {
  }
}

async function scrapeOneUrl(browser, url, company, index = 0) {
  const page = await browser.newPage({ userAgent: USER_AGENT });
  let status = null;
  page.on("response", (r) => {
    if (r.request().isNavigationRequest() && r.frame() === page.mainFrame()) status = r.status();
  });
  const facts = async (extra) => ({ url, finalUrl: page.url(), status, title: await page.title().catch(() => ""), ...extra });
  try {
    try {
      await page.goto(url, { waitUntil: "networkidle", timeout: TIMEOUT_MS });
    } catch (gotoErr) {
      if (!/Timeout .*exceeded/i.test(String((gotoErr && gotoErr.message) || gotoErr))) throw gotoErr;
    }
    if (company.clickSelector) {
      await page.waitForSelector(company.clickSelector, { timeout: TIMEOUT_MS });
      await Promise.all([
        page.waitForLoadState("domcontentloaded", { timeout: TIMEOUT_MS }).catch(() => {}),
        page.waitForURL((u) => u.href !== url, { timeout: TIMEOUT_MS }).catch(() => {}),
        page.click(company.clickSelector),
      ]);
    }
    if (company.waitForSelector) {
      await page.waitForSelector(company.waitForSelector, { timeout: TIMEOUT_MS }).catch(() => {});
    }
    if (company.settleDelayMs) {
      await page.waitForTimeout(company.settleDelayMs);
    }
    const blocked = async () => {
      const f = await facts();
      return BLOCK_TITLE.test(f.title) || (status && status >= 400) ? f : null;
    };
    const describe = (f) => `HTTP ${f.status || "?"}, page "${f.title}"`;
    if (company.pageData) {
      const data = await page.evaluate(() => {
        const el = document.getElementById("__NEXT_DATA__");
        try {
          return el ? JSON.parse(el.textContent) : null;
        } catch {
          return null;
        }
      });
      if (!data) {
        const f = await facts();
        await saveDebug(page, company, index, f);
        await page.close();
        throw new Error(BLOCK_TITLE.test(f.title) || (status && status >= 400)
          ? `page blocked or unavailable (${describe(f)})` : `no __NEXT_DATA__ page data (${describe(f)})`);
      }
      await page.close();
      return company.pageData(data, url);
    }

    const args = {
      patternSource: company.linkPattern.source,
      titleSelector: company.titleSelector || null,
      titleAncestorSelector: company.titleAncestorSelector || null,
      titleAncestorTitleSelector: company.titleAncestorTitleSelector || null,
      locationSelector: company.locationSelector || null,
      locationAncestorSelector: company.locationAncestorSelector || null,
    };
    const roles = await page.evaluate(collectLinks, args);

    if (!roles.length) {
      const f = await blocked();
      await saveDebug(page, company, index, f || (await facts({ note: "page loaded, no matching links" })));
      if (f) {
        await page.close();
        throw new Error(`page blocked or unavailable (${describe(f)})`);
      }
    }
    await page.close();
    return roles;
  } catch (err) {
    await page.close().catch(() => {});
    throw err;
  }
}

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
        }
      });
      if (places.length) return { places };
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

  for (const [index, url] of urls.entries()) {
    try {
      const found = await scrapeOneUrl(browser, url, company, index);
      found.forEach((r) => {
        if (seen.has(r.url)) return;
        seen.add(r.url);
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

  if (roles.length === 0 && errors.length === urls.length && urls.length > 0) {
    return { ok: false, error: errors.join("; ") };
  }

  const relevant = roles.filter((r) => isRoleRelevant(r.title));
  if (debug && relevant.length !== roles.length) {
    console.log(`[${company.slug}] ${roles.length - relevant.length} of ${roles.length} dropped as not title-relevant, ${relevant.length} kept`);
  }
  return { ok: true, found: roles.length, roles: relevant.map((r) => ({ title: r.title, url: r.url, location: cleanLocation(r.location) || company.fixedLocation || "", postedDate: null })) };
}

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
