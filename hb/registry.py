import json
import os
import sys

import arbetsformedlingen
import brainport
import gothenburg
import hire_helsinki
import jobsplus
import make_it_in_munich
import make_it_in_the_north
import nav
import skane
import south_holland
import talent_berlin
import vdab
import welcome_to_nl
import work_in_austria
import work_in_estonia
import work_in_finland
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
    {"id": "makeitinthenorth", "name": "Make it in the North", "country": "Netherlands",
     "url": "https://www.makeitinthenorth.nl/jobs/", "read": make_it_in_the_north.read},
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
    {"id": "workinfinland", "name": "Work in Finland", "country": "Finland",
     "url": "https://www.workinfinland.com/en/jobs", "read": work_in_finland.read},
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
    path = path if path is not None else os.environ.get("PP_CONTROL_FILE", "")
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
    rows, report = [], []
    for hub in (hubs if hubs is not None else HUBS):
        entry = {k: hub[k] for k in ("id", "name", "country", "url")}
        if hub["id"] in off:
            entry.update(off=True, rows=0, pages=0, total=None, error=None)
        else:
            try:
                hub_rows, health = hub["read"](terms=terms)
            except Exception as e:
                hub_rows, health = [], {"rows": 0, "pages": 0, "total": None, "error": f"{type(e).__name__}: {e}"}
            rows.extend((hub["id"], row) for row in hub_rows)
            entry.update(off=False, **health)
        if debug or entry.get("error"):
            print(f"[talent-hubs] {hub['id']}: " + ("off" if entry["off"] else
                  f"{entry['rows']} rows, {entry['pages']} pages" + (f", error: {entry['error']}" if entry["error"] else "")),
                  file=sys.stderr)
        report.append(entry)
    return rows, report
