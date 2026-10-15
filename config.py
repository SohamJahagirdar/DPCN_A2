"""Project configuration for DPCN Research Mapping Project - Group 18 (IISc + TIFR)."""
from pathlib import Path
import os

GROUP = 18
YEAR_FROM, YEAR_TO = 2016, 2026

# Assigned institutions. `openalex_ids` are matched exactly against authorship
# institutions. TIFR's child centres (NCRA, ICTS, TIFR-Hyderabad, TIFR-CAM, HBCSE)
# are NOT included by default; NCBS belongs to Group 23. Add their IDs here if the
# professor wants them (see QUESTIONS_FOR_PROFESSOR.md).
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

# Instructor request (13 Oct 2026): "flag those papers having co-authors greater than 10".
# n_coauthors = n_authors - 1 (co-authors of any one author); flag = n_coauthors > 10, i.e. >= 12 authors.
COAUTHOR_FLAG_THRESHOLD = 10

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
