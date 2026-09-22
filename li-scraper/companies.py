# The same companies tracked in index.html (name + slug), copied here so
# this scraper is self-contained and doesn't need to parse the frontend HTML.
# If you add/rename/remove a company in index.html, mirror the change here —
# there's no automatic sync between the two files. (Last reconciled 2026-09:
# every company in index.html has an entry here, full 1:1 coverage by
# design — see README.md for the "when there's an unknown ATS, add it here
# instead" strategy this was adopted for.)
#
# match.py normalizes each `name` (drops legal suffixes like "Group"/"Bank"/
# "Holdings", strips parenthetical alternate names into their own aliases,
# e.g. "Zepz (WorldRemit / Sendwave)" also matches postings from "WorldRemit"
# or "Sendwave") before comparing it against a LI posting's employer
# name. If a real posting from one of these companies isn't showing up in
# li-snapshot.json, the likely cause is the employer name on LI
# not resembling anything here closely enough — see README.md's "Fixing a
# missed match" section for how to add an explicit alias.

COMPANIES = [
    {"name": "Revolut", "slug": "revolut"},
    {"name": "Wise", "slug": "wise"},
    {"name": "Monzo", "slug": "monzo"},
    {"name": "Starling Bank", "slug": "starling-bank"},
    {"name": "N26", "slug": "n26"},
    {"name": "Adyen", "slug": "adyen"},
    {"name": "Checkout.com", "slug": "checkout-com"},
    {"name": "SumUp", "slug": "sumup"},
    {"name": "Klarna", "slug": "klarna"},
    {"name": "Mollie", "slug": "mollie"},
    {"name": "Qonto", "slug": "qonto"},
    {"name": "Pleo", "slug": "pleo"},
    {"name": "Moss", "slug": "moss"},
    {"name": "Spendesk", "slug": "spendesk"},
    {"name": "Trade Republic", "slug": "trade-republic"},
    {"name": "eToro", "slug": "etoro"},
    {"name": "Scalable Capital", "slug": "scalable-capital"},
    {"name": "Freetrade", "slug": "freetrade"},
    {"name": "IG Group", "slug": "ig-group"},
    {"name": "Alan", "slug": "alan"},
    {"name": "Marshmallow", "slug": "marshmallow"},
    {"name": "wefox", "slug": "wefox"},
    {"name": "Bitpanda", "slug": "bitpanda"},
    {"name": "Blockchain.com", "slug": "blockchain-com"},
    {"name": "Zepz (WorldRemit / Sendwave)", "slug": "zepz-worldremit-sendwave"},
    {"name": "Mambu", "slug": "mambu"},
    {"name": "Solaris (Solarisbank)", "slug": "solaris-solarisbank"},
    {"name": "GoCardless", "slug": "gocardless"},
    {"name": "TrueLayer", "slug": "truelayer"},
    {"name": "Standard Chartered", "slug": "standard-chartered"},
    {"name": "HSBC", "slug": "hsbc"},
    {"name": "Barclays", "slug": "barclays"},
    {"name": "Deutsche Bank", "slug": "deutsche-bank"},
    {"name": "BNP Paribas", "slug": "bnp-paribas"},
    {"name": "UBS", "slug": "ubs"},
    {"name": "ING", "slug": "ing"},
    {"name": "DBS Bank", "slug": "dbs-bank"},
    {"name": "OCBC Bank", "slug": "ocbc-bank"},
    {"name": "UOB", "slug": "uob"},
    {"name": "Airwallex", "slug": "airwallex"},
    {"name": "Nium", "slug": "nium"},
    {"name": "Thunes", "slug": "thunes"},
    {"name": "Grab (Grab Financial Group)", "slug": "grab-grab-financial-group"},
    {"name": "Aspire", "slug": "aspire"},
    {"name": "Xero", "slug": "xero"},
    {"name": "MYOB", "slug": "myob"},
    {"name": "Judo Bank", "slug": "judo-bank"},
    {"name": "Tyro Payments", "slug": "tyro-payments"},
    {"name": "Commonwealth Bank of Australia", "slug": "commonwealth-bank-of-australia"},
    {"name": "Westpac", "slug": "westpac"},
    {"name": "National Australia Bank (NAB)", "slug": "national-australia-bank-nab"},
    {"name": "ANZ", "slug": "anz"},
    {"name": "Zip Co", "slug": "zip-co"},
    {"name": "Sharesies", "slug": "sharesies"},
    {"name": "Rabobank", "slug": "rabobank"},
    {"name": "ABN AMRO", "slug": "abn-amro"},
    {"name": "Nordea", "slug": "nordea"},
    {"name": "Danske Bank", "slug": "danske-bank"},
    {"name": "UniCredit", "slug": "unicredit"},
    {"name": "Santander", "slug": "santander"},
    {"name": "Lloyds Banking Group", "slug": "lloyds-banking-group"},
    {"name": "NatWest Group", "slug": "natwest-group"},
    {"name": "Erste Group", "slug": "erste-group"},
    {"name": "Macquarie Group", "slug": "macquarie-group"},
    {"name": "MUFG", "slug": "mufg"},
    {"name": "Hang Seng Bank", "slug": "hang-seng-bank"},
    {"name": "Bank of New Zealand (BNZ)", "slug": "bank-of-new-zealand-bnz"},
    {"name": "Kiwibank", "slug": "kiwibank"},
    {"name": "Endowus", "slug": "endowus"},
    {"name": "StashAway", "slug": "stashaway"},
    {"name": "Syfe", "slug": "syfe"},
    {"name": "Moneyfarm", "slug": "moneyfarm"},
    {"name": "BlackRock", "slug": "blackrock"},
    {"name": "Schroders", "slug": "schroders"},
    {"name": "Crypto.com", "slug": "crypto-com"},
    {"name": "Coinbase", "slug": "coinbase"},
    {"name": "Kraken", "slug": "kraken"},
    {"name": "Circle", "slug": "circle"},
    {"name": "Luno", "slug": "luno"},
    {"name": "Emirates NBD", "slug": "emirates-nbd"},
    {"name": "First Abu Dhabi Bank (FAB)", "slug": "first-abu-dhabi-bank-fab"},
    {"name": "Mashreq Bank", "slug": "mashreq-bank"},
    {"name": "Network International", "slug": "network-international"},
    {"name": "Sarwa", "slug": "sarwa"},
    {"name": "Tabby", "slug": "tabby"},
    {"name": "Fidelity International", "slug": "fidelity-international"},
    {"name": "abrdn", "slug": "abrdn"},
    {"name": "M&G Investments", "slug": "m-g-investments"},
    {"name": "Legal & General Investment Management", "slug": "legal-general-investment-management"},
    {"name": "Janus Henderson Investors", "slug": "janus-henderson-investors"},
    {"name": "Man Group", "slug": "man-group"},
    {"name": "Aviva Investors", "slug": "aviva-investors"},
    {"name": "Robeco", "slug": "robeco"},
    {"name": "GIC", "slug": "gic"},
    {"name": "Temasek", "slug": "temasek"},
    {"name": "Eastspring Investments", "slug": "eastspring-investments"},
    {"name": "Fullerton Fund Management", "slug": "fullerton-fund-management"},
    {"name": "Value Partners Group", "slug": "value-partners-group"},
    {"name": "Nikko Asset Management", "slug": "nikko-asset-management"},
    {"name": "AMP Limited", "slug": "amp-limited"},
    {"name": "Magellan Financial Group", "slug": "magellan-financial-group"},
    {"name": "Perpetual Limited", "slug": "perpetual-limited"},
    {"name": "IFM Investors", "slug": "ifm-investors"},
    {"name": "Mubadala Investment Company", "slug": "mubadala-investment-company"},
    {"name": "Abu Dhabi Investment Authority (ADIA)", "slug": "abu-dhabi-investment-authority-adia"},
    {"name": "GXBank", "slug": "gxbank"},
    # NOTE (2026-09): "Boost Bank" and "Boost" below (slug "boost") are a
    # known, reviewed, accepted matching collision -- both names normalize
    # to the identical string "boost" once match.py's _normalize() strips
    # "Bank" as a legal/corporate suffix, so match_company() can't reliably
    # tell a real "Boost Bank" LI/Indeed posting from a real "Boost" one
    # apart from employer-name text alone; whichever is declared later in
    # this list wins ties in build_index()'s exact-match dict. Left
    # unresolved on purpose rather than forcing an arbitrary tie-break: the
    # two businesses are genuinely affiliated (Boost Bank is Axiata's 2024
    # digital-banking JV with RHB and literally shares Boost's own
    # careers.myboost.co board -- see its openNote in index.html), so a
    # stray misfile between the two slugs has minimal practical impact.
    # Documented and regression-tested via match.py's find_collisions() +
    # test_match.py's KNOWN_COLLISIONS allowlist, so this stays a tracked,
    # intentional limitation rather than a silent bug.
    {"name": "Boost Bank", "slug": "boost-bank"},
    {"name": "AEON Bank (Malaysia)", "slug": "aeon-bank-malaysia"},
    {"name": "Ryt Bank", "slug": "ryt-bank"},
    {"name": "KAF Digital Bank", "slug": "kaf-digital-bank"},
    {"name": "Maybank", "slug": "maybank"},
    {"name": "CIMB Group", "slug": "cimb-group"},
    {"name": "Public Bank Berhad", "slug": "public-bank-berhad"},
    {"name": "RHB Bank", "slug": "rhb-bank"},
    {"name": "Hong Leong Bank", "slug": "hong-leong-bank"},
    {"name": "Touch 'n Go Digital (TNG Digital)", "slug": "touch-n-go-digital-tng-digital"},
    # See the "Boost Bank" entry above -- this is the other half of the
    # documented, reviewed "boost" exact-match collision.
    {"name": "Boost", "slug": "boost"},
    {"name": "Curlec", "slug": "curlec"},
    {"name": "Versa", "slug": "versa"},
    {"name": "Wahed Invest", "slug": "wahed-invest"},
    {"name": "SAP", "slug": "sap"},
    {"name": "Amadeus", "slug": "amadeus"},
    {"name": "Dassault Systemes", "slug": "dassault-systemes"},
    {"name": "Wolters Kluwer", "slug": "wolters-kluwer"},
    {"name": "Hexagon", "slug": "hexagon"},
    {"name": "Atlassian", "slug": "atlassian"},
    {"name": "Ripple", "slug": "ripple"},
    {"name": "Swift", "slug": "swift"},
    {"name": "Amazon", "slug": "amazon"},
    {"name": "Apple", "slug": "apple"},
    {"name": "Aramco", "slug": "aramco"},
    {"name": "Visa", "slug": "visa"},
    {"name": "Mastercard", "slug": "mastercard"},
    {"name": "Intel", "slug": "intel"},
    {"name": "Rio Tinto", "slug": "rio-tinto"},
    {"name": "Shell", "slug": "shell"},
    {"name": "Petronas", "slug": "petronas"},
    {"name": "IBM", "slug": "ibm"},
    {"name": "Salesforce", "slug": "salesforce"},
    {"name": "TotalEnergies", "slug": "totalenergies"},
    {"name": "American Express", "slug": "american-express"},
    {"name": "PayPal", "slug": "paypal"},
    # -- Batch: tech companies (Sep 2026), added from the user's Tech Companies.txt --
    {"name": "Google", "slug": "google"},
    {"name": "Microsoft", "slug": "microsoft"},
    {"name": "Meta", "slug": "meta"},
    {"name": "Adobe", "slug": "adobe"},
    {"name": "Airbnb", "slug": "airbnb"},
    {"name": "Netflix", "slug": "netflix"},
    {"name": "Intuit", "slug": "intuit"},
    {"name": "Uber", "slug": "uber"},
    {"name": "NVIDIA", "slug": "nvidia"},
    {"name": "Stripe", "slug": "stripe"},
    {"name": "Spotify", "slug": "spotify"},
    {"name": "ServiceNow", "slug": "servicenow"},
    {"name": "Cisco", "slug": "cisco"},
    {"name": "LinkedIn", "slug": "li-employer"},
    {"name": "Dropbox", "slug": "dropbox"},
    {"name": "Booking.com", "slug": "booking-com"},
    {"name": "Zalando", "slug": "zalando"},
    {"name": "Delivery Hero", "slug": "delivery-hero"},
    {"name": "ASML", "slug": "asml"},
    {"name": "Lego Digital Play", "slug": "lego-digital-play"},
    {"name": "Shopee", "slug": "shopee"},
    {"name": "SEEK", "slug": "seek"},
    {"name": "Afterpay", "slug": "afterpay"},
    {"name": "SafetyCulture (now Mitti)", "slug": "safetyculture-mitti"},
    {"name": "Sony", "slug": "sony"},
    {"name": "Nintendo", "slug": "nintendo"},
    {"name": "Rakuten", "slug": "rakuten"},
    {"name": "LINE (LY Corporation)", "slug": "line-ly-corporation"},
    {"name": "Toyota", "slug": "toyota"},
    {"name": "Panasonic", "slug": "panasonic"},
    {"name": "Fujitsu", "slug": "fujitsu"},
    {"name": "Sony Interactive Entertainment", "slug": "sony-interactive-entertainment"},
    {"name": "Samsung", "slug": "samsung"},
    {"name": "LG", "slug": "lg"},
    {"name": "Coupang", "slug": "coupang"},
    {"name": "Mercado Libre", "slug": "mercado-libre"},
    # -- Batch: telecom / IT-services companies (Sep 2026), added at the
    # user's request. Also serves as the answer to "can li-scraper cover the
    # ones marked unknown ATS in index.html?" -- yes: unlike check.php's
    # adapters, li-scraper doesn't touch a company's own ATS at all, it runs
    # broad Design/UX/Product searches across LinkedIn + Indeed and then
    # matches whichever employer names come back against this list. Any
    # company here gets that supplemental coverage regardless of whether its
    # own site has a working adapter, which is exactly what the SuccessFactors/
    # Taleo/iCIMS-blocked companies below need (they're being added for that
    # reason specifically, not just for completeness like most of this file).
    #
    # Cisco is already in this list above (line ~172) -- not duplicated.
    {"name": "e&", "slug": "e-and"},
    {"name": "du (EITC)", "slug": "du"},
    # It's not an independent legal entity (see its index.html note -- fully
    # run by du/EITC), and any real UAE hiring for it would show up under
    # "du" anyway, but 2026-09 policy is full coverage over completeness
    # gaps, so it's included -- matched on the full "Virgin Mobile UAE"
    # string rather than bare "Virgin Mobile" to limit (not eliminate) the
    # risk of match.py's containment check pulling in an unrelated "Virgin
    # Mobile" posting from Australia/UK/US (whose normalized name is a
    # substring of ours, so it can still false-match the other direction --
    # worth spot-checking li-snapshot.json's virgin-mobile-uae entries once
    # this has run for real).
    {"name": "Virgin Mobile UAE", "slug": "virgin-mobile-uae"},
    {"name": "Deutsche Telekom", "slug": "deutsche-telekom"},
    {"name": "Orange", "slug": "orange"},
    {"name": "Vodafone", "slug": "vodafone"},
    {"name": "BT Group", "slug": "bt-group"},
    {"name": "Ericsson", "slug": "ericsson"},
    {"name": "Nokia", "slug": "nokia"},
    {"name": "Telefónica", "slug": "telefonica"},
    {"name": "Telenor", "slug": "telenor"},
    {"name": "Telia Company", "slug": "telia-company"},
    {"name": "Accenture", "slug": "accenture"},
    {"name": "Capgemini", "slug": "capgemini"},
    {"name": "Kyndryl", "slug": "kyndryl"},
    {"name": "T-Systems", "slug": "t-systems"},
    {"name": "Telstra", "slug": "telstra"},
    {"name": "Optus", "slug": "optus"},
    {"name": "TPG Telecom", "slug": "tpg-telecom"},
    {"name": "2degrees", "slug": "twodegrees"},
    # Matched as "Spark New Zealand" rather than bare "Spark" -- "Spark" alone
    # is a 5-char generic word (Spark Networks, Spark by Capital One, assorted
    # startups all use it) that would clear match.py's containment-matching
    # length threshold and start misattributing unrelated postings.
    {"name": "Spark New Zealand", "slug": "spark-nz"},
    {"name": "One NZ", "slug": "one-nz"},
    # -- Batch: Singapore's big 3 telcos (Sep 2026) --
    {"name": "Singtel", "slug": "singtel"},
    {"name": "StarHub", "slug": "starhub"},
    {"name": "M1", "slug": "m1"},
    # -- Batch: aviation / airlines (Sep 2026) --
    # Matched as "Emirates Airline" rather than bare "Emirates" -- this list
    # already has "Emirates NBD" (a Dubai bank), and bare "Emirates" would be
    # a substring of unrelated real postings like "Emirates Islamic Bank" or
    # "Emirates NBD Capital", which match.py's containment check would then
    # misattribute to the airline. A longer, more specific alias still
    # catches a bare "Emirates" LI posting (short names match *into* a
    # longer alias just fine) without matching the other direction.
    {"name": "Emirates Airline", "slug": "emirates"},
    {"name": "Etihad Airways", "slug": "etihad-airways"},
    {"name": "British Airways", "slug": "british-airways"},
    {"name": "KLM Royal Dutch Airlines", "slug": "klm"},
    {"name": "Lufthansa", "slug": "lufthansa"},
    {"name": "Air France", "slug": "air-france"},
    {"name": "Singapore Airlines", "slug": "singapore-airlines"},
    # -- Batch: enterprise/industrial + product-tech companies (Sep 2026) --
    {"name": "Siemens", "slug": "siemens"},
    {"name": "Bosch", "slug": "bosch"},
    {"name": "Shopify", "slug": "shopify"},
    {"name": "Celonis", "slug": "celonis"},
    {"name": "Personio", "slug": "personio"},
    {"name": "Miro", "slug": "miro"},
    {"name": "GitLab", "slug": "gitlab"},
    {"name": "Elastic", "slug": "elastic"},
    {"name": "Dynatrace", "slug": "dynatrace"},
    {"name": "GetYourGuide", "slug": "getyourguide"},
    {"name": "HelloFresh", "slug": "hellofresh"},
    {"name": "Trivago", "slug": "trivago"},
    {"name": "SoundCloud", "slug": "soundcloud"},
    {"name": "Datadog", "slug": "datadog"},
    {"name": "Cloudflare", "slug": "cloudflare"},
    {"name": "MongoDB", "slug": "mongodb"},
    # "Volvo Cars" (passenger vehicles) vs "Volvo Group" (trucks/buses/
    # construction equipment) are separate, unrelated companies since a 1999
    # ownership split -- but match.py's containment check is bidirectional,
    # so a bare "Volvo" or "Volvo Group" posting would currently misattribute
    # here (same shape of bug as the documented Boost/Boost Bank and
    # Emirates/du cases -- see match.py's find_collisions() docstring).
    # Accepted for now: Volvo Group is trucks/industrial and very unlikely to
    # post under this scraper's Product/Design/UX title list. Revisit if a
    # real Volvo Group posting ever shows up under this slug.
    {"name": "Volvo Cars", "slug": "volvo-cars"},
    {"name": "Mercedes-Benz", "slug": "mercedes-benz"},
    {"name": "BMW Group", "slug": "bmw-group"},
    {"name": "Airbus", "slug": "airbus"},
    {"name": "Philips", "slug": "philips"},
]

# Manual aliases for companies whose real LI employer name doesn't
# resemble the tracked name closely enough for the automatic normalizer in
# match.py to catch (verified where possible; a few are best-guess and worth
# rechecking against real results once this has run a few times):
ALIASES = {
    "li-employer": ["LinkedIn"],
    "meta": ["Meta Platforms"],
    "lg": ["LG Electronics", "LG Corp"],
    "safetyculture-mitti": ["Mitti", "SafetyCulture"],
    "lego-digital-play": ["LEGO Digital Play", "LEGO"],
    "line-ly-corporation": ["LINE", "LY Corporation"],
    "sony-interactive-entertainment": ["Sony Interactive Entertainment", "PlayStation", "SIE"],
    "mercado-libre": ["Mercado Libre", "MercadoLibre"],
    "dbs-bank": ["DBS", "DBS Bank Ltd"],
    "ocbc-bank": ["OCBC", "Oversea-Chinese Banking Corporation"],
    "national-australia-bank-nab": ["NAB"],
    "bank-of-new-zealand-bnz": ["BNZ"],
    "abu-dhabi-investment-authority-adia": ["ADIA"],
    "aeon-bank-malaysia": ["AEON Bank"],
    "touch-n-go-digital-tng-digital": ["Touch 'n Go", "TNG Digital", "TNGD"],
    "grab-grab-financial-group": ["Grab", "Grab Financial Group", "GFG"],
    "first-abu-dhabi-bank-fab": ["FAB", "First Abu Dhabi Bank"],
    "lloyds-banking-group": ["Lloyds Bank", "Lloyds"],
    "commonwealth-bank-of-australia": ["Commonwealth Bank", "CommBank"],
    # -- Batch: telecom / IT-services companies (Sep 2026) --
    "e-and": ["Etisalat", "e& UAE", "Etisalat Group"],
    # "Emirates Integrated Telecommunications Company" deliberately dropped
    # (2026-09): its normalized form starts with "emirates", which was
    # swallowing "Emirates Airline"/"Emirates Group" matches via containment
    # once the airline was added -- "EITC" already covers the common
    # abbreviation and real du postings are very unlikely to use the fully
    # spelled-out legal name anyway.
    "du": ["du", "EITC", "du Telecom"],
    "telefonica": ["Telefonica"],  # unaccented form, in case LI/Indeed drop the accent
    "twodegrees": ["2degrees Mobile"],
    "spark-nz": ["Spark NZ"],  # deliberately not bare "Spark" -- see COMPANIES comment
    "one-nz": ["One New Zealand"],
    # -- Batch: aviation / airlines (Sep 2026) --
    # Deliberately NOT adding bare "Emirates" or "The Emirates Group" as
    # aliases here -- both normalize to the same generic 8-char "emirates"
    # (the "group" suffix gets stripped) that "Emirates Airline" was chosen
    # as the primary name specifically to avoid registering, since it would
    # start misattributing unrelated "Emirates Islamic Bank" / "Emirates NBD
    # Capital" postings via containment. The single "Emirates Airline" entry
    # in COMPANIES already catches a bare "Emirates" posting on its own (a
    # short incoming name matches fine when it's contained *within* our
    # longer alias -- it's only dangerous the other way around).
    "klm": ["KLM", "Air France-KLM"],
}
