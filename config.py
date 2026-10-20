"""Project configuration for DPCN Research Mapping Project - Group 18 (IISc + TIFR)."""
from pathlib import Path
import os

GROUP = 18
YEAR_FROM, YEAR_TO = 2016, 2026
# When the OpenAlex data in data/raw/ (the team's shared snapshot) was collected; shown on the dashboard.
# Update it after a re-fetch. A fixed date, not a build timestamp, so rebuilding gives an identical dashboard.
DATA_COLLECTED = "13–15 Oct 2026"

# Assigned institutions. `openalex_ids` are matched exactly against authorship institutions.
# Scope (team decision, Oct 2026): IISc Bangalore and TIFR Mumbai only. TIFR's other centres
# (NCBS = Group 23, NCRA, ICTS, TIFR Hyderabad, TIFR-CAM, HBCSE) are excluded, also when OpenAlex
# gives their authors the main TIFR ID (see fetch.authorship_insts).
INSTITUTIONS = {
    "IISc": {
        "name": "Indian Institute of Science, Bangalore",
        "ror": "04dese585",
        "openalex_ids": ["I59270414"],
    },
    "TIFR": {
        "name": "Tata Institute of Fundamental Research, Mumbai",
        "ror": "03ht1xw27",
        "openalex_ids": ["I11947397"],
    },
}
TIFR_CHILD_CENTRES = {
    "I147602599": "National Centre for Radio Astrophysics",
    "I194223965": "National Centre for Biological Sciences",  # Group 23
    "I4210090503": "International Centre for Theoretical Sciences",
    "I4210112849": "TIFR Centre for Interdisciplinary Sciences (Hyderabad)",
    "I57827967": "Homi Bhabha Centre for Science Education",
    "I94595606": "TIFR Centre for Applicable Mathematics",
}
# Our cluster label (PPT: Groups 18-20 "IISc · TIFR · IISERs")
OWN_CLUSTER = "IISc/TIFR/IISER"

# OpenAlex work types kept. Excludes preprint, dataset, erratum, editorial, paratext, ...
# Fetched as two queries so that adding conference papers did not invalidate the cached journal pages.
WORK_TYPES = ["article", "review", "letter", "book-chapter"]
CONFERENCE_TYPES = ["conference-paper"]
ALL_TYPES = WORK_TYPES + CONFERENCE_TYPES

# Affiliation strings that place a "TIFR"-tagged author in a TIFR centre outside Mumbai (OpenAlex often
# tags NCBS, NCRA, ICTS, ... authors with the main TIFR ID). Such authorships do not count as TIFR Mumbai.
TIFR_CENTRE_PATTERN = (r"national cent(er|re) for biological|\bncbs\b|radio astrophysics|\bncra\b|\bgmrt\b|"
                       r"radio astronomy cent|ooty|udhagamandalam|international cent(er|re) for theoretical|\bicts\b|"
                       r"homi bhabha cent(er|re) for science education|\bhbcse\b|applicable mathematics|\bcam\b|"
                       r"interdisciplinary sciences|\btcis\b|hyderabad|narsingi|gopanpally|bengaluru|bangalore|pune|"
                       r"simons cent(er|re)|instem|institute for stem cell|balloon facility")

# Papers with more author records than this are "mega-collaborations" (CMS, ALICE,
# Belle, ...). They stay in the dataset but are excluded from the co-authorship
# network and from faculty seniority heuristics.
MEGA_AUTHOR_THRESHOLD = 50

# Instructor's flag (updated 15 Oct 2026): papers with more than 12 authors (column authors_gt_12),
# i.e. 13 or more authors - papers with 11 or 12 authors are common and are not flagged.
AUTHOR_FLAG_THRESHOLD = 12

# Journal-choice analysis: "high-impact journal" = OpenAlex 2-year mean citedness >= this value. That metric is the
# impact-factor equivalent (citations this year to the journal's items of the previous two years, per item);
# the instructor asked about "IF > 10".
HIGH_IMPACT_THRESHOLD = 10
# Journals with at least this many of our papers are nodes in the journal co-usage network
JOURNAL_NETWORK_MIN_PAPERS = 15

# Impact on India: an OpenAlex SDG tag counts only at score >= 0.8 ("correct about 7 in 10" per
# https://help.openalex.org/data/sdgs ; scores 0.5-0.8 are right only about half the time).
SDG_MIN_SCORE = 0.8

# Impact beyond research - technology: patents citing our papers, from "Reliance on Science" v64 (Marx & Fuegi 2020,
# Strategic Management Journal, doi:10.1002/smj.3145; 2022, J. Economics & Management Strategy, doi:10.1111/jems.12455;
# Zenodo record 11461587, CC BY-NC 4.0). Worldwide patent offices, citations through 2023.
PATENT_CITATIONS_URL = "https://zenodo.org/records/11461587/files/_pcs_oa.csv?download=1"
# A patent-paper link counts at confidence score >= 4 (1-10 scale), the filter the dataset's authors apply to their
# current release (https://relianceonscience.org/patent-to-paper-citations).
PATENT_MIN_CONFIDENCE = 4
# Last year covered by the patent data: papers from later years cannot have patent citations yet.
PATENT_DATA_LAST_YEAR = 2023

# Faculty heuristic thresholds (used only when no official roster match exists)
FACULTY_MIN_PAPERS = 8
FACULTY_MIN_YEARS = 4
FACULTY_MIN_SENIOR_SHARE = 0.30

# Number of top partner institutions for which topic profiles are fetched (Jaccard)
N_PARTNERS_FOR_TOPICS = 40
# ...and every partner sharing at least this many papers with IISc or TIFR
MIN_SHARED_FOR_TOPICS = 10

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
CACHE = DATA / "cache"
EXTERNAL = DATA / "external"
# DPCN_SAMPLE=1 -> write to separate *_sample folders (for experiments without touching the real outputs)
SAMPLE = os.environ.get("DPCN_SAMPLE", "") == "1"
_sfx = "_sample" if SAMPLE else ""
RAW = DATA / f"raw{_sfx}"
PROCESSED = DATA / f"processed{_sfx}"
OUTPUTS = ROOT / f"outputs{_sfx}"
DASHBOARD = ROOT / "dashboard"
DASHBOARD_FILE = DASHBOARD / f"index{_sfx}.html"
REPORT = ROOT / f"report{_sfx}"
for _p in (RAW, CACHE, EXTERNAL, PROCESSED, OUTPUTS, DASHBOARD, REPORT):
    _p.mkdir(parents=True, exist_ok=True)


def openalex_api_keys():
    """API keys from env var OPENALEX_API_KEY (comma-separated) or the git-ignored file openalex_key.txt
    (one key per line). Several keys = team members' free keys; the client moves to the next key when
    one runs out of daily budget."""
    env = os.environ.get("OPENALEX_API_KEY", "")
    keyfile = ROOT / "openalex_key.txt"
    raw = env.replace(",", "\n") if env.strip() else (keyfile.read_text(encoding="utf-8") if keyfile.exists() else "")
    return [k.strip() for k in raw.splitlines() if k.strip() and not k.strip().startswith("#")]


def openalex_api_key():
    keys = openalex_api_keys()
    return keys[0] if keys else None


MAILTO = os.environ.get("OPENALEX_MAILTO", "")
