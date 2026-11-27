"""
Talent Hubs: official regional and national job portals for internationals,
read every run alongside LI and Indeed (Isu's list, triaged 2026-11-26/27; see
the project doc zenpath-2026-11-26-talent-hubs-triage.md for what was skipped and why).

HUBS is the one list: hb-scraper/scrape.py runs it, tags rows with the hub's id
as their source, and publishes it with each hub's last-run health as
openMarket.talentHubs in data/hb-snapshot.json, from which the app builds
Settings › Job sites › Talent Hubs and its labels. When several hubs list the
same role, one record is kept (the first hub in HUBS order supplies the link)
with every hub in its `sources`; the app does the same across the two snapshots. `country` is where the hub's jobs are; countries only a
hub covers are scrape.py's EXTRA_MARKETS (accepted, not searched on LI or Indeed).

Each module's read(http, sleep, terms) returns (rows, health) and never raises.
A hub switched off in Settings (scraper-control.php's hubsOff, handed over by
the workflow as ZP_CONTROL_FILE) isn't read; its roles expire from the snapshot
as usual and the app hides them meanwhile.
"""
import json
import os
import sys

import arbetsformedlingen
import brainport
import gothenburg
import hire_helsinki
import jobsplus
import make_it_in_munich
import nav
import skane
import south_holland
import talent_berlin
import vdab
import welcome_to_nl
import work_in_austria
import work_in_estonia
import work_in_lithuania
import work_in_luxembourg
import workindenmark

HUBS = [
    {"id": "welcometonl", "name": "Welcome to NL", "country": "Netherlands",
     "url": "https://www.welcome-to-nl.nl/jobs/", "read": welcome_to_nl.read},
    {"id": "southholland", "name": "Work in South Holland", "country": "Netherlands",
     "url": "https://jobs.workinsouthholland.nl/jobs", "read": south_holland.read},
    {"id": "brainport", "name": "Brainport Eindhoven", "country": "Netherlands",
     "url": "https://brainporteindhoven.com/int/work/jobs", "read": brainport.read},
    {"id": "talentberlin", "name": "Talent Berlin", "country": "Germany",
     "url": "https://talent.berlin/jobs", "read": talent_berlin.read},
    {"id": "makeitinmunich", "name": "Make it in Munich", "country": "Germany",
     "url": "https://www.make-it-in-munich.com/munich-job-board/", "read": make_it_in_munich.read},
    {"id": "vdab", "name": "VDAB", "country": "Belgium",
     "url": "https://www.vdab.be/vindeenjob/jobs/jobs-in-belgium", "read": vdab.read},
    {"id": "workinluxembourg", "name": "Work in Luxembourg", "country": "Luxembourg",
     "url": "https://jobs.workinluxembourg.com/offers", "read": work_in_luxembourg.read},
    {"id": "workinaustria", "name": "Work in Austria", "country": "Austria",
     "url": "https://www.workinaustria.com/en/employees/jobs", "read": work_in_austria.read},
    {"id": "workindenmark", "name": "Workindenmark", "country": "Denmark",
     "url": "https://workindenmark.jobnet.dk/find-job", "read": workindenmark.read},
    {"id": "arbetsformedlingen", "name": "Arbetsförmedlingen", "country": "Sweden",
     "url": "https://arbetsformedlingen.se/platsbanken", "read": arbetsformedlingen.read},
    {"id": "skane", "name": "Skåne STEM jobs", "country": "Sweden",
     "url": "https://skane.com/live-work/international-house/stem-jobportal/", "read": skane.read},
    {"id": "gothenburg", "name": "Careers in Gothenburg", "country": "Sweden",
     "url": "https://careersingothenburg.com/", "read": gothenburg.read},
    {"id": "nav", "name": "NAV arbeidsplassen", "country": "Norway",
     "url": "https://arbeidsplassen.nav.no/stillinger?v=6&workLanguage=Engelsk", "read": nav.read},
    {"id": "hirehelsinki", "name": "Hire Helsinki", "country": "Finland",
     "url": "https://www.myhelsinki.fi/hire-helsinki/", "read": hire_helsinki.read},
    {"id": "workinestonia", "name": "Work in Estonia", "country": "Estonia",
     "url": "https://workinestonia.com/job/", "read": work_in_estonia.read},
    {"id": "workinlithuania", "name": "Work in Lithuania", "country": "Lithuania",
     "url": "https://jobs.workinlithuania.com/", "read": work_in_lithuania.read},
    {"id": "jobsplus", "name": "Jobsplus", "country": "Malta",
     "url": "https://jobsplus.gov.mt/vacancy", "read": jobsplus.read},
]
HUB_IDS = [h["id"] for h in HUBS]
assert len(set(HUB_IDS)) == len(HUB_IDS), "hub ids must be unique"


def hubs_off(path=None):
    """Hub ids switched off in Settings, from the workflow's copy of
        scraper-control.php's answer. Missing or unreadable: none off.
    """
    path = path if path is not None else os.environ.get("ZP_CONTROL_FILE", "")
    if not path:
        return set()
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return set()
    off = data.get("hubsOff") if isinstance(data, dict) else None
    return {h for h in off if h in HUB_IDS} if isinstance(off, list) else set()


def run_talent_hubs(terms, off=frozenset(), debug=False, hubs=None):
    """Reads every hub not in `off`. Returns (rows as (hub_id, row), report),
        report being HUBS' public fields plus each hub's health and `off`.
    """
    rows, report = [], []
    for hub in (hubs if hubs is not None else HUBS):
        entry = {k: hub[k] for k in ("id", "name", "country", "url")}
        if hub["id"] in off:
            entry.update(off=True, rows=0, pages=0, total=None, error=None)
        else:
            try:
                hub_rows, health = hub["read"](terms=terms)
            except Exception as e:  # noqa: BLE001 -- a reader bug must not lose the other hubs
                hub_rows, health = [], {"rows": 0, "pages": 0, "total": None, "error": f"{type(e).__name__}: {e}"}
            rows.extend((hub["id"], row) for row in hub_rows)
            entry.update(off=False, **health)
        if debug or entry.get("error"):
            print(f"[talent-hubs] {hub['id']}: " + ("off" if entry["off"] else
                  f"{entry['rows']} rows, {entry['pages']} pages" + (f", error: {entry['error']}" if entry["error"] else "")),
                  file=sys.stderr)
        report.append(entry)
    return rows, report
