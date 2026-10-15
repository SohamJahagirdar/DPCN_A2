"""Step 2 - turn raw OpenAlex records into analysis tables and the groupN_data.csv deliverable."""
import re
import unicodedata
from functools import lru_cache
from collections import Counter, defaultdict

import numpy as np
import pandas as pd

import config
from pipeline.fetch import all_own_ids, authorship_insts, corpus_path, load_corpus
from pipeline.io_utils import read_jsonl
from pipeline.lookups import CORE, SJR
from pipeline.openalex import short_id

INVISIBLE = re.compile("[%s-%s%s-%s]" % (chr(0x200B), chr(0x200F), chr(0x202A), chr(0x202E)))  # zero-width / direction marks
OWN_IDS = {inst: set(v["openalex_ids"]) for inst, v in config.INSTITUTIONS.items()}


# =========================================================================== helpers
def h_index(cites):
    c = sorted((int(x) for x in cites), reverse=True)
    return sum(1 for i, x in enumerate(c, 1) if x >= i)


def venue_type(src):
    if not src:
        return "other"
    t = src.get("type")
    name = (src.get("display_name") or "").lower()
    if t == "journal":
        return "journal"
    if t == "conference" or (t == "book series" and ("proceedings" in name or "lecture notes" in name)):
        return "conference"
    return "other"


def strip_accents(s):
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


_DASHES = dict.fromkeys(map(ord, "\u2010\u2011\u2012\u2013\u2014\u2212"), "-")


def name_tokens(name):
    s = strip_accents(name or "").translate(_DASHES).lower()
    s = re.sub(r"\b(prof|dr|mr|mrs|ms)\.?\s", " ", s)
    s = re.sub(r"[^a-z\s\-\.]", " ", s).replace(".", " ").replace("-", " ")
    return [t for t in s.split() if t]


def name_match_strength(roster_toks, cand_toks):
    """None = incompatible, else (number of full-token matches, every roster token explained?).

    Every candidate token must be explained by a distinct roster token: a full token by an equal
    token (or by a roster initial, e.g. roster "Arun S P" vs OpenAlex "Sripati P. Arun"), an initial
    by a roster token starting with that letter. Handles "Rao M V Srisha" / "M. V. Srisha Rao" / "Srisha Rao".
    """
    pool = list(roster_toks)
    full = extra_full = extra_init = 0
    for t in sorted(cand_toks, key=len, reverse=True):   # full tokens first
        if len(t) > 1:
            if t in pool:
                pool.remove(t)
                full += 1
                continue
            joined = [p for p in pool if len(p) > 1 and (p.startswith(t) or t.startswith(p)) and min(len(p), len(t)) >= 4]
            if joined:
                pool.remove(joined[0])
                full += 1
                continue
            ini = [p for p in pool if len(p) == 1 and p == t[0]]
            if ini:
                pool.remove(ini[0])
                continue
            extra_full += 1          # e.g. "Ullas Kolthur Seetharam" vs roster "Ullas Kolthur"
        else:
            m = sorted((p for p in pool if p[0] == t), key=len)   # prefer consuming a roster initial
            if not m:
                extra_init += 1      # e.g. "Trishen S. Gunaratnam" vs roster "Trishen Gunaratnam"
                continue
            pool.remove(m[0])
    if extra_full > 1 or ((extra_full or extra_init) and full < 2):
        return None
    return full, not pool


DEPT_STOP = {"department", "dept", "of", "and", "the", "for", "centre", "center", "unit", "school", "division",
             "laboratory", "lab", "programme", "program", "in", "interdisciplinary"}
DEPT_ALIASES = {  # abbreviations seen in raw affiliation strings -> roster wording
    "csa": "computer science and automation", "ece": "electrical communication engineering",
    "ee": "electrical engineering", "sscu": "solid state and structural chemistry", "mbu": "molecular biophysics",
    "ipc": "inorganic and physical chemistry", "cense": "nano science and engineering", "mrc": "materials research",
    "dese": "electronic systems engineering", "caos": "atmospheric and oceanic sciences", "ces": "ecological sciences",
    "cds": "computational and data sciences", "mcb": "microbiology and cell biology",
    "dbg": "developmental biology and genetics", "mrdg": "developmental biology and genetics",
    "molecular reproduction": "developmental biology and genetics", "cpdm": "design and manufacturing",
    "product design and manufacturing": "design and manufacturing", "cst": "sustainable technologies",
    "icer": "energy research", "serc": "supercomputer education and research", "chep": "high energy physics",
    "iap": "instrumentation and applied physics", "dtp": "theoretical physics", "dhep": "high energy physics",
    "dcmpms": "condensed matter physics and materials science", "daa": "astronomy and astrophysics",
    "dnap": "nuclear and atomic physics", "dcs": "chemical sciences", "dbs": "biological sciences",
    "stcs": "technology and computer science", "computer science": "technology and computer science",
    "mathematics": "mathematics", "math": "mathematics", "aerospace": "aerospace engineering",
}


@lru_cache(maxsize=None)
def dept_tokens(s):
    s = strip_accents(str(s or "")).lower().replace("&", " and ")
    for k, v in DEPT_ALIASES.items():
        if re.fullmatch(rf"(department of |dept\.? of )?{re.escape(k)}", s.strip()):
            s = v
    toks = {re.sub(r"(ies|s)$", lambda m: "y" if m.group(1) == "ies" else "", t)
            for t in re.findall(r"[a-z]+", s)}
    return toks - DEPT_STOP


GENERIC_DEPT_WORDS = {"engineering", "science", "technology", "research", "material", "system", "studie"}


@lru_cache(maxsize=None)
def dept_similar(a, b):
    ta, tb = dept_tokens(a), dept_tokens(b)
    if not ta or not tb:
        return False
    inter = len(ta & tb)
    jac = inter / len(ta | tb)
    small = min(len(ta), len(tb))
    if small == 1:
        tok = next(iter(ta if len(ta) == 1 else tb))
        return jac >= 0.5 or (inter == 1 and len(tok) >= 8 and tok not in GENERIC_DEPT_WORDS)
    if inter == small and small >= 3:
        return True                            # "Condensed Matter Physics" ~ "... and Materials Science"
    return jac >= 0.75                         # keeps EE != ECE, Materials Eng != Materials Research


DEPT_KEYS = re.compile(r"\b(department|dept|centre|center|unit|school|division|laborator|programme|program|"
                       r"facility|cell|chair)\w*", re.I)
INST_WORDS = re.compile(r"indian institute of science|tata institute|\biisc\b|\btifr\b|bangalore|bengaluru|mumbai|"
                        r"india\b|homi bhabha road|colaba|c\.?\s*v\.?\s*raman", re.I)


def clean_dept(s):
    s = strip_accents(s).strip(" .;:-")
    s = re.sub(r"^(the\s+)?(department|dept\.?)\s+(of|for)\s+", "", s, flags=re.I)
    s = re.sub(r"\s+(department|dept\.?)$", "", s, flags=re.I)
    s = s.replace("&", "and")
    s = re.sub(r"\s+", " ", s).strip(" .;:-")
    if not s:
        return None
    if s.isupper() and len(s) > 6:
        s = s.title()
    return s[0].upper() + s[1:]


def extract_dept(raw_strings):
    for raw in raw_strings or []:
        for seg in re.split(r"[,;]", raw):
            seg = seg.strip()
            if not seg or len(seg) > 90 or INST_WORDS.search(seg) and not DEPT_KEYS.search(seg):
                continue
            if DEPT_KEYS.search(seg) and not re.search(r"tata institute|indian institute of science", seg, re.I):
                d = clean_dept(seg)
                if d and len(d) > 3:
                    return d
    return None


# ---------------------------------------------------------------- Indian institution clusters
CSIR_LABS = r"(csir|council of scientific (and|&) industrial research|national chemical laboratory|indian institute of chemical technology|" \
            r"central electrochemical|central food technological|national institute for interdisciplinary science|" \
            r"national metallurgical laboratory|national physical laboratory|central scientific instruments|" \
            r"central glass (and|&) ceramic|central mechanical engineering|central road research|central institute of mining|" \
            r"central building research|central electronics engineering|structural engineering research centre|" \
            r"advanced materials and processes research|centre for cellular (and|&) molecular biology|" \
            r"institute of genomics (and|&) integrative biology|institute of microbial technology|central drug research|" \
            r"indian institute of integrative medicine|national institute of oceanography|national geophysical research|" \
            r"national botanical research|central leather research|indian institute of petroleum|" \
            r"national environmental engineering|indian institute of toxicology|central salt (and|&) marine|" \
            r"indian institute of chemical biology|national aerospace laboratories|central institute of medicinal|" \
            r"north east institute of science|institute of minerals (and|&) materials|institute of himalayan bioresource|" \
            r"central mining|fourth paradigm|national institute of science communication)"
DAE_GROUP = r"(bhabha atomic research|indira gandhi centre for atomic|raja ramanna|national institute of science education (and|&) research|niser)"
PREMIER = r"(indian statistical institute|institute of mathematical sciences|chennai mathematical|harish[- ]chandra|" \
          r"national centre for biological sciences|s\.?\s*n\.?\s*bose|bose institute|saha institute)"
CENTRAL_UNIS = r"(jawaharlal nehru university|university of hyderabad|university of delhi|banaras hindu|jadavpur university|" \
               r"jamia millia|aligarh muslim|visva[- ]bharati|pondicherry university|tezpur university|" \
               r"central university|university of allahabad|assam university|north[- ]eastern hill)"


def classify_inst(name, otype=None):
    n = (name or "").lower()
    if "indian institute of science education" in n:
        return "IISc/TIFR/IISER"
    if re.search(r"indian institute of science\b", n) or "tata institute of fundamental" in n or re.search(r"\btifr\b", n) or \
            re.search(r"international centre for theoretical sciences|national centre for radio astrophysics|homi bhabha centre for science education", n):
        return "IISc/TIFR/IISER"
    if re.search(PREMIER, n):
        return "Premier Science"
    if re.search(r"indian institute of information technology|international institute of information technology|\biiit|"
                 r"atal bihari vajpayee indian institute|pdpm", n):
        return "IIIT"
    if re.search(r"indian institute of technology|\biit\b|indian school of mines", n):
        return "IIT"
    if re.search(r"national institute of technology|\bnit\b|maulana azad national institute|motilal nehru national", n):
        return "NIT"
    if re.search(CSIR_LABS, n):
        return "CSIR"
    if re.search(DAE_GROUP, n):
        return "DAE"
    if re.search(r"academy of scientific and innovative research|acsir", n):
        return "CSIR"
    if re.search(r"atomic energy|homi bhabha national institute|variable energy cyclotron|institute of physics, bhubane|ugc[- ]dae|"
                 r"institute for plasma research|tata memorial|atomic minerals", n):
        return "Other DAE"
    if re.search(CENTRAL_UNIS, n):
        return "Central University"
    if re.search(r"indian space research|isro|space applications|vikram sarabhai|defence research|drdo|"
                 r"aeronautical development|physical research laboratory|indian institute of astrophysics|"
                 r"raman research|jawaharlal nehru centre|indian association for the cultivation|inter-university centre|"
                 r"aryabhatta research|indian institute of tropical meteorology|national centre for|satellite cent|"
                 r"defence|meteorolog|earth sciences|indian council of|biotechnology|national institute of immunology|"
                 r"translational health|dna fingerprinting|powder metallurgy|materials for electronics|"
                 r"nano and soft matter|palaeosciences|bioinformatics|stem cell|national institute of (advanced studies|"
                 r"mental health|plant genome)|indian institute of space science", n):
        return "Govt R&D / Autonomous"
    if otype == "healthcare" or re.search(r"medical|hospital|aiims|all india institute of medical|nimhans|pgimer|icmr", n):
        return "Medical"
    if otype == "company":
        return "Industry"
    if re.search(r"university|college|vidyapeeth|vishwavidyalaya", n) or otype == "education":
        return "Other University/College"
    return "Other"


# =========================================================================== main build
def load_flows():
    out = {}
    for kind in ("outflow", "inflow"):
        for inst in config.INSTITUTIONS:
            p = config.RAW / f"{kind}_{inst}.jsonl.gz"
            out[(kind, inst)] = list(read_jsonl(p)) if p.exists() else None
    for inst in config.INSTITUTIONS:
        p = config.RAW / f"inflow_agg_{inst}.jsonl.gz"
        out[("inflow_agg", inst)] = next(read_jsonl(p), None) if p.exists() else None
    return out


NON_INSTITUTIONS = re.compile(r"^(government of |ministry of |department of (science and technology|biotechnology)$)", re.I)


def load_roster():
    frames = []
    for f in sorted(config.EXTERNAL.glob("faculty_*.csv")):
        frames.append(pd.read_csv(f, dtype=str).fillna(""))
    if not frames:
        return pd.DataFrame(columns=["institution", "name", "department", "designation"])
    r = pd.concat(frames, ignore_index=True)
    r["department"] = r["department"].map(lambda d: "; ".join(clean_dept(x) or x for x in d.split(";") if x.strip()))
    r["primary_department"] = r["department"].str.split(";").str[0].str.strip()
    r["is_honorary"] = r["designation"].str.contains("honorary|emerit", case=False)
    return r[r["institution"].isin(list(config.INSTITUTIONS))].reset_index(drop=True)


def build_all():
    works, homes = load_corpus()
    print(f"[build] {len(works)} unique works")
    sjr, core = SJR(), CORE()
    all_own = all_own_ids()
    inst_meta = {r["id"]: (r["name"], r["type"], r["country"])   # institution id -> (name, type, country)
                 for r in read_jsonl(config.RAW / "institutions_extra.jsonl.gz") or []}

    # ------------------------------------------------------------------ papers + authorships
    prow, arow = [], []
    for wid, w in works.items():
        auths = w.get("authorships", [])
        n_auth = w.get("authors_count") or len(auths)   # true count when the list was truncated
        pl = w.get("primary_location") or {}
        src = pl.get("source") or {}
        issns = [i for i in ([src.get("issn_l")] + (src.get("issn") or [])) if i]
        year = w.get("publication_year")
        vt = "conference" if w.get("type") == "conference-paper" else venue_type(src)
        sj = sjr.lookup(issns, year) if issns else None
        crank = core.lookup(src.get("display_name")) if vt == "conference" or (vt == "other" and src) else None
        if crank and vt == "other":
            vt = "conference"
        pt = w.get("primary_topic") or {}
        indian = {}
        for a in auths:
            for i in a.get("institutions", []):
                iid = short_id(i.get("id"))
                if not iid:
                    continue
                inst_meta.setdefault(iid, (i.get("display_name"), i.get("type"), i.get("country_code")))
                if i.get("country_code") == "IN":
                    indian[iid] = i.get("display_name")
        quart = sj[0] if sj and vt == "journal" else (crank if crank else (sj[0] if sj else None))
        prow.append(dict(
            work_id=wid, doi=w.get("doi"), title=w.get("title") or w.get("display_name"), year=year,
            oa_type=w.get("type"), venue=src.get("display_name"), source_id=short_id(src.get("id")),
            source_type=src.get("type"), venue_type=vt, issn=src.get("issn_l") or (issns[0] if issns else None),
            citations=w.get("cited_by_count", 0), fwci=w.get("fwci"),
            domain=(pt.get("domain") or {}).get("display_name"), field=(pt.get("field") or {}).get("display_name"),
            subfield=(pt.get("subfield") or {}).get("display_name"),
            subfield_id=short_id((pt.get("subfield") or {}).get("id")), topic=pt.get("display_name"),
            n_authors=n_auth, is_mega=n_auth > config.MEGA_AUTHOR_THRESHOLD,
            many_authors=n_auth > config.AUTHOR_FLAG_THRESHOLD,   # instructor's flag: > 12 authors
            homes=";".join(sorted(homes[wid])), sjr_quartile=sj[0] if sj else None, sjr=sj[1] if sj else None,
            sjr_areas=sj[2] if sj else None, core_rank=crank, quartile=quart,
            n_refs=len(w.get("referenced_works") or []), is_retracted=w.get("is_retracted"),
            indian_inst_ids=";".join(sorted(indian)),
        ))
        corr = {short_id(x) for x in (w.get("corresponding_author_ids") or [])}
        for a in auths:
            au = a.get("author") or {}
            aid = short_id(au.get("id"))
            if not aid:   # OpenAlex has not assigned an author ID: key it by the normalised name
                nm_toks = name_tokens(au.get("display_name") or a.get("raw_author_name"))
                aid = "N:" + "-".join(nm_toks) if nm_toks else None
            if not aid:
                continue
            iids = [short_id(i.get("id")) for i in a.get("institutions", []) if i.get("id")]
            own = authorship_insts(a)
            arow.append(dict(
                work_id=wid, author_id=aid, author_name=INVISIBLE.sub("", au.get("display_name") or a.get("raw_author_name") or "").strip(),
                orcid=au.get("orcid"), position=a.get("author_position"),
                is_corresponding=bool(a.get("is_corresponding")) or aid in corr,
                own_insts=";".join(own), inst_ids=";".join(iids),
                indian_inst_ids=";".join(i for i in iids if inst_meta.get(i, (0, 0, 0))[2] == "IN"),
                dept=extract_dept(a.get("raw_affiliation_strings")) if own else None,
                year=w.get("publication_year"), n_authors=n_auth,
            ))
    papers = pd.DataFrame(prow).set_index("work_id", drop=False)
    auth = pd.DataFrame(arow)
    # A name-based ID ("N:...", authorship without an OpenAlex author ID) is folded into the real author ID
    # when exactly one real ID with the same name exists at the same institution.
    auth["name_key"] = auth["author_name"].map(lambda n: "-".join(sorted(name_tokens(n))))
    real = auth[~auth["author_id"].str.startswith("N:") & (auth["own_insts"] != "")]
    real_ids = real.groupby(["own_insts", "name_key"])["author_id"].agg(lambda s: set(s))
    def _fold(r):
        if not r.author_id.startswith("N:"):
            return r.author_id
        ids = real_ids.get((r.own_insts, r.name_key))
        return next(iter(ids)) if ids and len(ids) == 1 else r.author_id
    pseudo = auth["author_id"].str.startswith("N:")
    auth.loc[pseudo, "author_id"] = auth[pseudo].apply(_fold, axis=1)
    auth = auth.drop(columns="name_key")
    print(f"[build] {len(papers)} papers, {len(auth)} authorships; quartile coverage "
          f"{papers['quartile'].notna().mean():.1%}")

    # ------------------------------------------------------------------ institutional authors
    own_auth = auth[auth["own_insts"] != ""].copy()
    own_auth["inst"] = own_auth["own_insts"].str.split(";")
    own_auth = own_auth.explode("inst")
    own_auth["citations"] = own_auth["work_id"].map(papers["citations"])
    own_auth["senior"] = (own_auth["position"].eq("last") | own_auth["is_corresponding"] | own_auth["n_authors"].eq(1))
    own_auth["is_mega"] = own_auth["n_authors"] > config.MEGA_AUTHOR_THRESHOLD

    # Keep a paper for an institution only if at least one of its authors there can be identified
    # (even the full author list shows none -> OpenAlex mis-tag, e.g. a nameless or unreadable author).
    have = set(zip(own_auth["work_id"], own_auth["inst"]))
    dropped = []
    for wid in list(homes):
        keep = {i for i in homes[wid] if (wid, i) in have}
        if not keep:
            dropped.append(wid)
            del homes[wid], works[wid]
        else:
            homes[wid] = keep
    papers = papers.drop(index=dropped)
    papers["homes"] = papers["work_id"].map(lambda w: ";".join(sorted(homes[w])))
    auth = auth[~auth["work_id"].isin(dropped)]
    own_auth = own_auth[own_auth["work_id"].isin(papers.index)]
    print(f"[build] dropped {len(dropped)} papers with no identifiable IISc/TIFR author; {len(papers)} remain")

    profiles = {short_id(a["id"]): a for a in read_jsonl(config.RAW / "authors.jsonl.gz") or []}

    # ------------------------------------------------------------------ faculty identification
    roster = load_roster()
    cand = own_auth.groupby(["inst", "author_id"]).agg(
        name=("author_name", lambda s: s.mode().iat[0]), n=("work_id", "nunique"),
        last_year=("year", "max")).reset_index()
    person_of = {}  # (inst, author_id) -> person key
    persons = {}    # person key -> dict
    depts_of = own_auth.dropna(subset=["dept"]).groupby(["inst", "author_id"])["dept"].agg(list).to_dict()
    other_depts = {i: sorted({d.strip() for x in roster.loc[roster["institution"] == i, "department"]
                              for d in x.split(";") if d.strip()}) for i in config.INSTITUTIONS}
    for inst, grp in cand.groupby("inst"):
        rs = roster[roster["institution"] == inst]
        cand_toks = [(row.author_id, name_tokens(row.name), row.n) for row in grp.itertuples()]
        # also use alternative names from author profiles
        alt = {aid: [name_tokens(x) for x in (profiles.get(aid, {}).get("display_name_alternatives") or [])][:10]
               for aid, _, _ in cand_toks}
        name_ids = Counter(tuple(sorted(ct)) for _, ct, _ in cand_toks)
        for ridx, r in rs.sort_values("is_honorary", kind="stable").iterrows():
            rt = name_tokens(r["name"])
            rdepts = [d.strip() for d in r["department"].split(";") if d.strip()]
            key = f"R:{inst}:{ridx}"
            by_dept, no_dept, unique_name = [], [], []
            for aid, ct, n in cand_toks:
                scores = [s for s in [name_match_strength(rt, ct)] + [name_match_strength(rt, x) for x in alt[aid]] if s]
                if not scores:
                    continue
                full, complete = max(scores)
                if full < 1 or (full == 1 and not complete):
                    continue
                strong = full >= 2 or (complete and len(rt) >= 3)
                ds = depts_of.get((inst, aid), [])
                share = sum(any(dept_similar(d, rd) for rd in rdepts) for d in ds) / len(ds) if ds else 0
                other = (sum(any(dept_similar(d, od) for od in other_depts[inst] if od not in rdepts) for d in ds)
                         / len(ds)) if ds else 0
                if share >= 0.2:
                    by_dept.append((aid, share, n))
                elif other < 0.5 and strong:
                    # no department info, or only labs/groups we can't map -> fall back to the name
                    no_dept.append((aid, 0, n))
                elif strong and complete and name_ids[tuple(sorted(ct))] == 1 and sorted(ct) == sorted(rt):
                    # exactly the roster name and nobody else at the institute has it: same person,
                    # papers just carry another department (earlier post, joint appointment)
                    unique_name.append((aid, 0, n))
                # else: affiliations clearly in a different department -> a different person
            # Department-consistent IDs win; otherwise (no department info at all) take only the
            # most prolific name match, so common names ("Praveen Kumar") don't absorb strangers.
            matched = by_dept or sorted(no_dept, key=lambda x: -x[2])[:1] or unique_name
            # an OpenAlex ID belongs to one roster person only (regular faculty are matched first)
            matched = [m for m in matched if (inst, m[0]) not in person_of]
            if not matched:
                continue
            persons[key] = dict(person=key, inst=inst, name=r["name"], department=r["primary_department"],
                                designation=r["designation"], faculty_source="retired list" if r["designation"].startswith("Retired") else "roster",
                                is_honorary=bool(r["is_honorary"]),
                                author_ids=[m[0] for m in matched])
            for aid, _, _ in matched:
                # an OpenAlex ID matching two roster people is ambiguous -> keep the stronger match
                prev = person_of.get((inst, aid))
                person_of[(inst, aid)] = key if prev is None else prev
    n_roster = sum(1 for p in persons.values())
    print(f"[build] roster: {len(roster)} faculty listed, {n_roster} matched to OpenAlex authors")

    # heuristic for authors not on (current) rosters: former faculty who left before the roster date
    stats = own_auth.groupby(["inst", "author_id"]).agg(
        n=("work_id", "nunique"), years=("year", "nunique"), last_year=("year", "max"),
        n_nonmega=("is_mega", lambda s: int((~s).sum())),
        senior_nonmega=("senior", "sum")).reset_index()
    nm = own_auth[~own_auth["is_mega"]].groupby(["inst", "author_id"])["senior"].mean()
    stats["senior_share"] = [nm.get((i, a), np.nan) for i, a in zip(stats["inst"], stats["author_id"])]
    for r in stats.itertuples():
        if (r.inst, r.author_id) in person_of:
            continue
        on_roster_era = r.last_year >= config.YEAR_TO - 1   # still publishing there now -> roster is authoritative
        if roster[roster["institution"] == r.inst].empty:
            on_roster_era = False
        if (not on_roster_era and r.n >= config.FACULTY_MIN_PAPERS and r.years >= config.FACULTY_MIN_YEARS
                and r.n_nonmega >= 3 and (r.senior_share or 0) >= config.FACULTY_MIN_SENIOR_SHARE):
            key = f"H:{r.inst}:{r.author_id}"
            prof = profiles.get(r.author_id, {})
            persons[key] = dict(person=key, inst=r.inst, name=prof.get("display_name") or
                                cand.loc[(cand.inst == r.inst) & (cand.author_id == r.author_id), "name"].iat[0],
                                department=None, designation="former faculty (heuristic)",
                                faculty_source="heuristic", is_honorary=False, author_ids=[r.author_id])
            person_of[(r.inst, r.author_id)] = key
    print(f"[build] faculty: {sum(p['faculty_source'] == 'roster' for p in persons.values())} roster-matched + "
          f"{sum(p['faculty_source'] == 'heuristic' for p in persons.values())} heuristic (former)")

    own_auth["person"] = [person_of.get((i, a)) for i, a in zip(own_auth["inst"], own_auth["author_id"])]

    # departments for heuristic faculty: modal parsed department
    dept_mode = own_auth.dropna(subset=["dept"]).groupby("person")["dept"].agg(lambda s: s.mode().iat[0])
    for k, p in persons.items():
        if not p["department"]:
            p["department"] = dept_mode.get(k) or "Unknown"

    # ------------------------------------------------------------------ per-faculty metrics
    fac_rows = []
    fa = own_auth.dropna(subset=["person"]).drop_duplicates(["person", "work_id"])
    pap = papers.set_index("work_id")
    for key, g in fa.groupby("person"):
        p = persons[key]
        wp = pap.loc[g["work_id"]]
        nonmega = wp[~wp["is_mega"]]
        venue_counts = wp["venue"].dropna().value_counts()
        prof_h = [profiles.get(a, {}).get("summary_stats", {}).get("h_index") for a in p["author_ids"]]
        prof_h = [x for x in prof_h if x is not None]
        orcid = next((profiles.get(a, {}).get("orcid") for a in p["author_ids"] if profiles.get(a, {}).get("orcid")), None)
        jq = wp[wp["venue_type"] == "journal"]["sjr_quartile"]
        fac_rows.append(dict(
            person=key, inst=p["inst"], name=p["name"], department=p["department"], designation=p["designation"],
            faculty_source=p["faculty_source"], is_honorary=p["is_honorary"],
            openalex_ids=";".join(p["author_ids"]), orcid=orcid,
            papers=len(wp), papers_nonmega=len(nonmega), citations=int(wp["citations"].sum()),
            papers_authors_gt_12=int(wp["many_authors"].sum()),
            citations_nonmega=int(nonmega["citations"].sum()),
            h_index=h_index(wp["citations"]), h_index_nonmega=h_index(nonmega["citations"]),
            h_index_career=max(prof_h) if prof_h else None,
            q1_share=float((jq == "Q1").mean()) if jq.notna().any() else None,
            top_journal=venue_counts.index[0] if len(venue_counts) else None,
            first_year=int(wp["year"].min()), last_year=int(wp["year"].max()),
            top_field=wp["field"].mode().iat[0] if wp["field"].notna().any() else None,
        ))
    faculty = pd.DataFrame(fac_rows)
    # roster faculty with no matched publications still belong in the faculty list
    matched_names = {(p["inst"], p["name"]) for p in persons.values()}
    unmatched = roster[[(i, n) not in matched_names for i, n in zip(roster["institution"], roster["name"])]]
    if len(unmatched):
        faculty = pd.concat([faculty, pd.DataFrame(dict(
            person=[f"R:{i}:{k}" for i, k in zip(unmatched["institution"], unmatched.index)],
            inst=unmatched["institution"], name=unmatched["name"], department=unmatched["primary_department"],
            designation=unmatched["designation"], faculty_source="roster (no OpenAlex match)",
            is_honorary=unmatched["is_honorary"], papers=0, citations=0, h_index=0))], ignore_index=True)

    tables = dict(papers=papers, auth=auth, own_auth=own_auth, faculty=faculty, persons=persons,
                  inst_meta=inst_meta, flows=load_flows(), works=works, homes=homes, roster=roster)
    tables["dataset"] = build_dataset_rows(tables)
    out = config.OUTPUTS / f"group{config.GROUP}_data.csv"
    tables["dataset"].to_csv(out, index=False, encoding="utf-8")
    faculty.to_csv(config.OUTPUTS / "faculty_list.csv", index=False, encoding="utf-8")
    papers.to_pickle(config.PROCESSED / "papers.pkl")
    print(f"[build] wrote {out.name}: {len(tables['dataset'])} rows")
    return tables


def build_dataset_rows(t):
    papers, own_auth, persons, inst_meta, flows, works = (t["papers"], t["own_auth"], t["persons"],
                                                          t["inst_meta"], t["flows"], t["works"])
    # Indian-citation flags per (work, inst)
    cites_ind, cited_by_ind = {}, {}
    for inst in config.INSTITUTIONS:
        of = flows[("outflow", inst)]
        if of is not None:
            ext = {r["id"] for r in of}
            for wid in papers.index[papers["homes"].str.contains(inst)]:
                refs = {short_id(r) for r in works[wid].get("referenced_works") or []}
                cites_ind[(wid, inst)] = len(refs & ext)
        inf = flows[("inflow", inst)]
        if inf is not None:
            cnt = Counter(c for r in inf for c in r.get("cites", []))
            for wid in papers.index[papers["homes"].str.contains(inst)]:
                cited_by_ind[(wid, inst)] = cnt.get(wid, 0)

    fac_auth = own_auth.dropna(subset=["person"])
    by_work_inst = defaultdict(list)
    for r in fac_auth.drop_duplicates(["work_id", "inst", "person"]).itertuples():
        by_work_inst[(r.work_id, r.inst)].append((persons[r.person]["name"], r.author_id, persons[r.person]["department"], True))
    other_auth = own_auth[own_auth["person"].isna()].groupby(["work_id", "inst"])
    other_names = other_auth["author_name"].agg(lambda s: "; ".join(dict.fromkeys(s)))
    other_dept = other_auth["dept"].agg(lambda s: s.dropna().mode().iat[0] if s.notna().any() else None)

    rows = []
    for p in papers.itertuples():
        for inst in p.homes.split(";"):
            own = OWN_IDS[inst]
            co = [inst_meta[i][0] for i in p.indian_inst_ids.split(";") if i and i not in own]
            people = by_work_inst.get((p.work_id, inst)) or [
                (other_names.get((p.work_id, inst)) or "[not listed: OpenAlex author list truncated]", None,
                 other_dept.get((p.work_id, inst)), False)]
            ci, cb = cites_ind.get((p.work_id, inst)), cited_by_ind.get((p.work_id, inst))
            for name, aid, dept, is_fac in people:
                rows.append(dict(
                    group=config.GROUP, institution=inst, author=name, title=p.title, year=p.year,
                    type=p.venue_type, journal_name=p.venue, issn=p.issn if p.venue_type == "journal" else None,
                    doi=p.doi, citations=p.citations, quartile=p.quartile,
                    coauthor_institutes="; ".join(co),
                    cites_indian_inst=None if ci is None else ci > 0,
                    cited_by_indian_inst=None if cb is None else cb > 0,
                    # ---- extra columns (beyond the required set)
                    n_authors=p.n_authors, authors_gt_12=p.many_authors,   # instructor's flag
                    is_faculty=is_fac, department=dept, author_openalex_id=aid, openalex_work_id=p.work_id,
                    sjr_quartile=p.sjr_quartile, core_rank=p.core_rank, field=p.field, subfield=p.subfield,
                    domain=p.domain,
                    mega_collaboration=p.is_mega,
                    n_refs_to_indian_inst=ci, n_cites_from_indian_inst=cb, openalex_type=p.oa_type,
                ))
    return pd.DataFrame(rows)


def top_partner_ids(n, min_shared=None):
    """Indian co-author institutions (excluding our own) for topic-profile fetching: the n most frequent,
    plus every institution sharing at least `min_shared` papers with one of our institutes."""
    works, homes = load_corpus()
    own = all_own_ids()
    cnt = Counter()
    per_inst = Counter()
    for wid, w in works.items():
        ids = {short_id(i["id"]) for a in w.get("authorships", []) for i in a.get("institutions", [])
               if i.get("country_code") == "IN" and i.get("id")}
        cnt.update(ids - own)
        for inst in homes[wid]:
            per_inst.update((inst, i) for i in ids - OWN_IDS[inst])
    flows = load_flows()
    cit = Counter()
    for (kind, _), recs in flows.items():
        if recs and kind == "inflow":
            for r in recs:
                cit.update({i["id"] for i in r["insts"]} - own)
    ids = [i for i, _ in cnt.most_common(n)]
    ids += [i for i, _ in cit.most_common(n // 2) if i not in ids]
    if min_shared:
        ids += sorted({i for (_, i), c in per_inst.items() if c >= min_shared} - set(ids))
    return ids
