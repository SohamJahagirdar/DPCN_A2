"""Impact on India beyond research: technology, economy, national missions and public services.

Bibliometrics cannot show that a paper caused an economic or social benefit. What it can show is the documented
*pathways* through which research reaches users outside academia (Bornmann 2013, doi:10.1002/asi.22803; the
"payback" categories of Buxton & Hanney 1996, doi:10.1177/135581969600100107). Every pathway below leaves a
traceable record, so each claim on the dashboard can be followed back to a patent, a paper or an institution.

  Technology   Patents that cite the paper (Reliance on Science v64: Marx & Fuegi 2020, doi:10.1002/smj.3145;
               2022, doi:10.1111/jems.12455), counted at confidence >= config.PATENT_MIN_CONFIDENCE. The patent
               office comes from the patent number. The dataset has no patents from the Indian Patent Office
               (its sources are full-text patent collections that do not include India). "Author-inventor" = at least one
               author of the paper is an inventor on the patent (the dataset's `self` flag). Patent citations are
               the standard bibliometric link between science and technology (Narin et al. 1997,
               doi:10.1016/S0048-7333(97)00013-9; Ahmadpoor & Jones 2017, doi:10.1126/science.aam9527).
  Economy      Co-authorship with companies in India (Tijssen 2012, doi:10.1093/reseval/rvs013; the CWTS Leiden
               Ranking's industry-collaboration indicator). Companies are institutions OpenAlex types "company"
               (from ROR) plus company affiliations written in the authors' address text (Pvt. Ltd., Limited, LLP,
               Inc.) with an Indian location, which finds start-ups missing from ROR. Ownership: public sector
               company (PSU), Indian private, or multinational (foreign headquarters). Start-ups whose address is
               IISc's campus or its incubator (Society for Innovation and Development) are marked.
               Citations by researchers at companies in India (OpenAlex institution type "company").
  Missions     Co-authorship with, and citation by, Indian organisations that deliver national missions and public
               services, grouped by sector from the institution name and OpenAlex type: space, defence and
               aerospace, atomic energy, earth/climate/environment, agriculture, health and medicine, CSIR
               industrial R&D labs, government departments and regulators, NGOs and think tanks.
Citing papers that involve the paper's own institute are excluded, as in reputable.indian_uptake.
"""
import csv
import gzip
import json
import re
from collections import Counter, defaultdict

import numpy as np
import pandas as pd

import config
from pipeline.build import OWN_IDS
from pipeline.openalex import short_id

PATENTS_PATH = config.RAW / "patent_citations.csv.gz"

INDUSTRY = "Industry"
ACADEMIA = "Academia & basic research"
# (sector, name pattern), first match wins; companies are assigned to Industry before these are tried
SECTOR_RULES = [
    ("Space", r"indian space research|\bisro\b|rao satellite|satellite cent|space applications|vikram sarabhai space|"
              r"liquid propulsion|satish dhawan|remote sensing|space physics laboratory|semi-?conductor laboratory|"
              r"north eastern space|department of space|human space ?flight"),
    ("Defence & aerospace", r"defen[cs]e|\bdrdo\b|aeronautical development|gas turbine research|armament|naval |"
                            r"electronics and radar|airborne systems|artificial intelligence and robotics|"
                            r"solid state physics laboratory|terminal ballistics|high energy materials|combat vehicles|"
                            r"research cent(re|er) imarat|advanced systems laboratory|indian (army|navy|air force)|"
                            r"military|national aerospace laboratories|ordnance|airworthiness"),
    ("Atomic energy", r"bhabha atomic|cent(re|er) for atomic research|raja ramanna|nuclear power corporation|"
                      r"atomic energy regulatory|atomic minerals|heavy water|radiation (and|&) isotope|"
                      r"department of atomic energy|nuclear fuel"),
    ("Earth, climate & environment", r"earth sciences|meteorolog|weather|ocean|polar|seismolog|atmospheric research|"
                                     r"geophysical research|geological survey|ground ?water|water commission|hydrolog|"
                                     r"water resources|geomagnetism|survey of india|zoological survey|botanical survey|"
                                     r"wildlife institute|pollution control|environment|ecolog|climate|"
                                     r"coastal|earth science studies"),
    ("Agriculture & food", r"agricultur|\bicar\b|horticult|veterinary|animal husbandry|fisheries|dairy|rice research|"
                           r"crop|sugarcane|forestry|forest research|icrisat|food techn|millet|cotton|tea research|"
                           r"coffee|rubber research|spices|plantation|soil|livestock|poultry|sericult|krishi|"
                           r"plant protection|seed science"),
    ("Health & medicine", r"medical|hospital|\baiims\b|nimhans|neurosciences|mental health|\bpgimer\b|"
                          r"postgraduate institute of medical|\bicmr\b|council of medical research|cancer|"
                          r"tata memorial|\bactrec\b|health|clinic|pharmaceutical education|\bniper\b|virology|"
                          r"cholera|tuberculosis|malaria|nutrition|epidemiolog|vaccine|nursing|dental|ayurved|"
                          r"\bayush\b|homoeopath|diabet|eye institute|cardi|biomedical genomics"),
    ("Industrial R&D (CSIR labs)", r"council of scientific and industrial research|\bcsir\b|national chemical laboratory|"
                                   r"national physical laboratory|indian institute of chemical technology|"
                                   r"central electrochemical|central glass|central leather|central salt|"
                                   r"central mechanical engineering|central scientific instruments|central road research|"
                                   r"central building research|structural engineering research|national metallurgical|"
                                   r"minerals and materials technology|advanced materials and processes|"
                                   r"central institute of mining|environmental engineering research|"
                                   r"indian institute of petroleum|central drug research|"
                                   r"institute of microbial technology|indian institute of chemical biology|"
                                   r"institute of genomics and integrative|cellular and molecular biology|"
                                   r"institute of himalayan bioresource|interdisciplinary science and technology"),
    ("Government & policy", r"ministry|government of|department of|reserve bank|niti aayog|bureau of|commission|"
                            r"directorate|municipal|panchayat|national informatics|election|census|statistics office|"
                            r"regulatory authority|secretariat|parliament|high court|supreme court|police"),
]
SECTOR_RULES = [(s, re.compile(p)) for s, p in SECTOR_RULES]
NGO = "NGOs & think tanks"
SECTORS = [INDUSTRY] + [s for s, _ in SECTOR_RULES] + [NGO]
NOT_SECTOR = re.compile(r"academy of scientific and innovative research|indian institute of (science education|"
                        r"technology|information technology)|\buniversity\b|defence institute of advanced technology|"
                        r"national defence academy")
NOT_COMPANY = re.compile(r"techno india")        # education groups that ROR types as companies

PSU = re.compile(r"bharat electronics|hindustan aeronautics|bharat heavy electricals|indian oil|oil and natural gas|"
                 r"power grid|hindustan petroleum|coal india|bharat petroleum|hll lifecare|engineers india|air india|"
                 r"\bgail\b|indian immunologicals|bharat dynamics|\bntpc\b|steel authority|nuclear power corporation|"
                 r"electronics corporation of india|\bbeml\b|brahmos|mazagon|cochin shipyard|garden reach|"
                 r"hindustan copper|\bnmdc\b|uranium corporation|bharat sanchar|\bbsnl\b|"
                 r"translational research platform for veterinary")
MNC = re.compile(r"bosch|\bibm\b|microsoft|samsung|\bintel\b|texas instruments|unilever|\bshell\b|general electric|"
                 r"\bge healthcare|honeywell|agilent|hewlett|\babb\b|oracle|\bicon\b|danish hydraulic|airbus|iqvia|"
                 r"astrazeneca|syneos|meiji|novartis|johnson & johnson|glaxo|general motors|stmicro|l.or[eé]al|"
                 r"bristol|eli lilly|merck|medtronic|mylan|pfizer|daiichi|pharmaceutical product development|valagro|"
                 r"cognizant|imgenex|bloom energy|qualcomm|sandoz|faurecia|delta electronics|eurofins|google|amazon|"
                 r"nvidia|cisco|siemens|philips|ericsson|nokia|\bsap\b|adobe|accenture|analog devices|\bnxp\b|"
                 r"broadcom|mercedes|daimler|boeing|rolls.royce|sanofi|bayer|basf|dupont|caterpillar|cummins|deere|"
                 r"toyota|honda|hyundai|mitsubishi|hitachi|toshiba|panasonic|fujitsu|vmware|western digital|seagate|"
                 r"micron|applied materials|lam research|synopsys|cadence|mathworks|schlumberger|halliburton|"
                 r"baker hughes|exxon|chevron|saint.gobain|corning|nestl|procter|colgate|pepsico|abbott|roche|"
                 r"thermo fisher|walmart|uber|linkedin|yahoo|facebook|\bapple\b|infineon|marvell|mediatek|\bamd\b|"
                 r"xilinx|keysight|ansys|dassault|autodesk|continental|valeo|tesla|dell\b|lenovo|huawei|sony|\blg\b")
OWNERSHIP = ["Public sector company (PSU)", "Indian private company", "Multinational in India"]

# company affiliations written in the address text, with an Indian location
COMPANY_TEXT = re.compile(r"\b(pvt\.?|private\s+limited|private\s+ltd\.?|ltd\.?|limited|llp|inc\.)(?=[\s,.)]|$)", re.I)
INDIAN_PLACE = re.compile(r"india|bangalore|bengaluru|mumbai|pune|hyderabad|chennai|delhi|gurgaon|gurugram|noida|"
                          r"kolkata|ahmedabad|kochi|thiruvananthapuram|mysore|mysuru|goa", re.I)
# a start-up's address on IISc's campus: its incubators (Society for Innovation and Development, CeNSE, CPDM TBI),
# the IISc campus or its PIN code
AT_IISC = re.compile(r"(society|foundation) (for|of) (science )?innovation (and|&) development|\bsid\b|incubat|"
                     r"entrepreneurship cent|\btbi\b|indian institute of science(?! education)|\biisc\b|560 ?012", re.I)
BIO_TEXT = re.compile(r"\b(he|she|his|her)\b|is currently|holds a (bachelor|master)", re.I)   # author biographies, not addresses
# stricter test for companies that have their own OpenAlex record (their authors often also list IISc itself)
AT_INCUBATOR = re.compile(r"(society|foundation) (for|of) (science )?innovation (and|&) development|\bsid\b|incubat|"
                          r"entrepreneurship cent|\btbi\b", re.I)
NOT_STARTUP = re.compile(r"triveni turbines")   # large listed company that happens to give an IISc-area address
_LEGAL = re.compile(r"\((i|p|india)\)|\b(pvt|private|ltd|limited|llp|inc)\b\.?|(?<!of )\bindia\b", re.I)


_GENERIC_END = re.compile(r"(technologies|technology|solutions|solution|services|service|systems|system|labs|lab|"
                          r"limited|ltd|pvt|private|india|s)$")


def company_key(name):
    """Spelling-insensitive key: 'AGNIT Semiconductors' = 'Agnit Semiconductor', 'Super-wave Technology' =
    'Super Wave Technologies'."""
    k = re.sub(r"[^a-z0-9]+", "", _LEGAL.sub(" ", name.lower()))
    while True:
        k2 = _GENERIC_END.sub("", k)
        if k2 == k or len(k2) < 4:
            return k
        k = k2


def clean_company(text):
    """Company name = the words before the legal suffix (Pvt. Ltd., Limited, ...), without address or department."""
    name = re.sub(r"\s+", " ", _LEGAL.sub(" ", text)).strip(" ,.-&;")
    name = re.sub(r"^(and |indian institute of science\s*& |r ?& ?d[/ ]|research and development (division|centre)?\s*|"
                  r"(presently|formerly|currently|also) (with|at) |opp\.? |department of [\w&]+ [\w&]+ |"
                  r"pharmaceutical development |quality control lab |talent development |innovation campus mumbai )",
                  "", name, flags=re.I)
    return name.strip(" ,.-&;")


def company_from_text(raw):
    """(company name, start-up at IISc) for the first Indian company address in an affiliation string, else None.
    Several affiliations can share one string, separated by ';', so each part is read on its own."""
    for part in (raw or "").split(";"):
        m = COMPANY_TEXT.search(part)
        if not m or not INDIAN_PLACE.search(part) or BIO_TEXT.search(part):
            continue
        seg = part[:m.start()].split(",")[-1]          # the comma-separated piece holding the company name
        name = clean_company(seg)
        if len(name) >= 3 and name.lower() not in ("services", "india"):
            startup = bool(AT_IISC.search(part)) and not (PSU.search(name.lower()) or MNC.search(name.lower())
                                                          or NOT_STARTUP.search(name.lower()))
            return name, startup
    return None


def sector_of(name, otype):
    n = (name or "").lower()
    if otype == "company" and not NOT_COMPANY.search(n):
        return INDUSTRY
    if not NOT_SECTOR.search(n):
        for s, rx in SECTOR_RULES:
            if rx.search(n):
                return s
    if otype == "healthcare":
        return "Health & medicine"
    if otype == "nonprofit":
        return NGO
    if otype == "government" and re.search(r"government|ministry|department", n):
        return "Government & policy"
    return ACADEMIA


def ownership_of(name):
    n = (name or "").lower()
    return OWNERSHIP[0] if PSU.search(n) else OWNERSHIP[2] if MNC.search(n) else OWNERSHIP[1]


def load_patents():
    """Patent citations to our papers at the confidence threshold; one row per (paper, patent)."""
    if not PATENTS_PATH.exists():
        return pd.DataFrame(columns=["work_id", "patent", "office", "own"])
    with gzip.open(PATENTS_PATH, "rt", encoding="utf-8", newline="") as f:
        df = pd.DataFrame(list(csv.DictReader(f)))
    df = df[pd.to_numeric(df["confscore"]) >= config.PATENT_MIN_CONFIDENCE].copy()
    df["office"] = df["patent"].str.split("-").str[0].str.upper()
    df["own"] = df["self"] == "isself"          # values: isself / notself / unkself (unknown)
    return df.groupby(["work_id", "patent"], sort=True).agg(office=("office", "first"), own=("own", "max")).reset_index()


def pathways(t):
    """Per paper: patents, industry co-authors and sector users. Cached on t (one computation per variant)."""
    papers, works, homes = t["papers"], t["works"], t["homes"]
    cached = t.get("_pathways")
    if cached and cached[0] is papers:     # variants copy t, so check it is the same paper table
        return cached[1]
    own_all = set().union(*OWN_IDS.values())
    sec_cache = {}

    def sec(iid, name, typ):
        if iid not in sec_cache:
            sec_cache[iid] = sector_of(name, typ)
        return sec_cache[iid]

    # --- co-authors outside academia (Indian institutions and company addresses)
    co = {}
    for wid in sorted(papers.index):
        comp, sectors, orgs = {}, set(), {}
        for a in works[wid].get("authorships", []):
            typed_company = False
            for i in a.get("institutions", []):
                iid = short_id(i.get("id"))
                if not iid or i.get("country_code") != "IN" or iid in own_all:
                    continue
                s = sec(iid, i.get("display_name"), i.get("type"))
                if s == INDUSTRY:
                    typed_company = True
                    nm = re.sub(r"\s*\(india\)$", "", i.get("display_name") or "", flags=re.I)
                    first = nm.split()[0].lower() if nm.split() else "?"
                    startup = ownership_of(nm) == OWNERSHIP[1] and not NOT_STARTUP.search(nm.lower()) and any(
                        first in part.lower() and AT_INCUBATOR.search(part)
                        for raw in a.get("raw_affiliation_strings") or [] for part in raw.split(";"))
                    k = company_key(nm)
                    comp[k] = (nm, comp.get(k, (nm, False))[1] or startup)
                elif s != ACADEMIA:
                    sectors.add(s)
                    orgs[iid] = (i.get("display_name"), s)
            if not typed_company:
                for raw in a.get("raw_affiliation_strings") or []:
                    hit = company_from_text(raw)
                    if hit:
                        k = company_key(hit[0])
                        comp[k] = (comp.get(k, hit)[0], comp.get(k, hit)[1] or hit[1])
        if comp:
            sectors.add(INDUSTRY)
        co[wid] = (comp, sectors, orgs)

    # one display name per company: the most frequent spelling
    spell = defaultdict(Counter)
    for comp, _, _ in co.values():
        for k, (nm, _) in comp.items():
            spell[k][nm] += 1
    canon = {k: sorted(c.items(), key=lambda x: (-x[1], x[0]))[0][0] for k, c in spell.items()}

    # --- Indian citing papers by sector (own-institute citing papers excluded)
    cit = defaultdict(lambda: defaultdict(set))   # work -> sector -> citing ids
    cit_orgs = defaultdict(Counter)               # sector -> Counter(institution) over citing papers
    cit_company = Counter()
    cit_names = defaultdict(Counter)              # work -> Counter((sector, institution)) over citing papers
    for (kind, _), recs in sorted(t["flows"].items()):
        if kind != "inflow" or not recs:
            continue
        for r in recs:
            ids = {i["id"] for i in r["insts"]}
            secs = {}
            for i in r["insts"]:
                s = sec(i["id"], i.get("name"), i.get("type"))
                if s != ACADEMIA:
                    secs.setdefault(s, set()).add((i["id"], i.get("name")))
            if not secs:
                continue
            for c in r.get("cites", []):
                if c not in homes or c not in co:
                    continue
                if ids & set().union(*(OWN_IDS[h] for h in homes[c])):
                    continue
                for s, insts in secs.items():
                    if r["id"] not in cit[c][s]:
                        cit[c][s].add(r["id"])
                        for iid, nm in sorted(insts, key=str):   # sorted: tie order must not depend on set order
                            cit_orgs[s][nm] += 1
                            cit_names[c][(s, nm)] += 1
                            if s == INDUSTRY:
                                cit_company[re.sub(r"\s*\(india\)$", "", nm or "", flags=re.I)] += 1

    pat = load_patents()
    pg = pat.groupby("work_id")
    rows = []
    for wid in sorted(papers.index):
        comp, sectors, orgs = co[wid]
        p = pg.get_group(wid) if wid in pg.groups else None
        cites = {s: len(v) for s, v in cit.get(wid, {}).items()}
        rows.append(dict(
            work_id=wid,
            patents=0 if p is None else len(p),
            patents_self=0 if p is None else int(p["own"].sum()),
            patent_offices="" if p is None else ";".join(sorted(set(p["office"]))),
            companies="; ".join(sorted(canon[k] for k in comp)),
            company_owners=";".join(sorted({ownership_of(canon[k]) for k in comp})),
            iisc_startup="; ".join(sorted(canon[k] for k, v in comp.items() if v[1])),
            coauthor_sectors=";".join(s for s in SECTORS if s in sectors),
            coauthor_orgs="; ".join(sorted({f"{n}" for n, _ in orgs.values() if n})),
            citing_sectors=";".join(s for s in SECTORS if cites.get(s)),
            **{f"cit_{s}": cites.get(s, 0) for s in SECTORS},
        ))
    df = pd.DataFrame(rows).set_index("work_id")
    df["industry"] = df["companies"] != ""
    df["nonacademic_user"] = (df["coauthor_sectors"] != "") | (df["citing_sectors"] != "")
    t["_pathways"] = (papers, (df, pat, dict(cit_orgs), cit_company, dict(cit_names)))
    return t["_pathways"][1]


CASES_PATH = config.EXTERNAL / "impact_case_studies.json"


def _match(P, m):
    """Papers matching every condition of one rule: company (co-author company name), faculty (IISc/TIFR faculty
    author, any of the names), title / title_re (text or regex in the title), india_term, doi (list), inst,
    exclude_doi (papers whose attribution could not be confirmed)."""
    sel = pd.Series(True, index=P.index)
    if "company" in m:
        sel &= P["companies"].str.contains(m["company"], case=False, regex=False)
    if "faculty" in m:
        names = m["faculty"] if isinstance(m["faculty"], list) else [m["faculty"]]
        sel &= P["faculty"].apply(lambda fs: any(n.lower() == f.lower() for f in fs for n in names))
    if "title" in m:
        sel &= P["title"].fillna("").str.contains(m["title"], case=False, regex=False)
    if "title_re" in m:
        rx = re.compile(m["title_re"], re.I)
        sel &= P["title"].fillna("").map(lambda x: bool(rx.search(x)))
    if "india_term" in m:
        sel &= P["india_terms"].fillna("").str.contains(m["india_term"], case=False, regex=False)
    if "doi" in m:
        sel &= P["doi"].fillna("").str.lower().isin([d.lower() for d in m["doi"]])
    if "inst" in m:
        sel &= P["homes"].str.contains(m["inst"], regex=False)
    if "exclude_doi" in m:
        sel &= ~P["doi"].fillna("").str.lower().isin([d.lower() for d in m["exclude_doi"]])
    return sel


def case_studies(P, pat, cit_names):
    """Documented examples (data/external/impact_case_studies.json: facts and sources checked by hand), each
    joined to the matching papers in our data and what the data shows about their use."""
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8")) if CASES_PATH.exists() else []
    out = []
    for c in cases:
        sel = pd.Series(False, index=P.index)
        rules = c.get("match") or []                # null = no paper of ours is linked to this outcome
        for m in (rules if isinstance(rules, list) else [rules]):   # a list = any of them
            sel |= _match(P, m)
        S = P[sel]
        users = Counter()
        for wid in S.index:
            for key in cit_names.get(wid, {}):
                users[key] += 1                       # number of these papers the organisation cites
        coorgs = Counter(o for x in S["coauthor_orgs"] if x for o in x.split("; "))
        sp = pat[pat["work_id"].isin(S.index)].drop_duplicates("patent")
        top = S.sort_values(["citations", "year"], ascending=False).head(4)
        out.append(dict(c, papers=int(len(S)), citations=int(S["citations"].sum()), patents=int(len(sp)),
                        fields=S["field"].value_counts().head(3).index.tolist(),
                        users=[dict(sector=k[0], name=k[1], papers=int(v))
                               for k, v in sorted(users.items(), key=lambda x: (-x[1], x[0]))[:8]],
                        coauthor_orgs=[n for n, _ in sorted(coorgs.items(), key=lambda x: (-x[1], x[0]))[:6]],
                        top=[dict(title=r.title, year=int(r.year), venue=r.venue, citations=int(r.citations), doi=r.doi)
                             for r in top.itertuples()]))
    return out


def _share(x):
    return float(x.mean()) if len(x) else None


def impact_stats(t, out_dir=None):
    papers = t["papers"]
    pw, pat, cit_orgs, cit_company, cit_names = pathways(t)
    pw = pw.reindex(papers.index)
    P = papers[["title", "year", "homes", "field", "venue", "citations", "doi", "many_authors", "india_terms"]].join(pw)
    years = list(range(config.YEAR_FROM, config.YEAR_TO + 1))
    last = config.PATENT_DATA_LAST_YEAR
    out = {}
    for inst in list(config.INSTITUTIONS) + ["All"]:
        sub = P if inst == "All" else P[P["homes"].str.contains(inst)]
        win = sub[sub["year"] <= last]                 # papers old enough to have patent citations in the data
        sp = pat[pat["work_id"].isin(sub.index)]
        up = sp.drop_duplicates("patent")
        comp_rows = Counter()
        comp_owner, comp_iisc = {}, {}
        for r in sub[sub["industry"]].itertuples():
            for nm in r.companies.split("; "):
                comp_rows[nm] += 1
                comp_owner[nm] = ownership_of(nm)
                comp_iisc[nm] = comp_iisc.get(nm, False) or nm in (r.iisc_startup or "").split("; ")
        own_counts = {o: int(sub["company_owners"].str.contains(re.escape(o)).sum()) for o in OWNERSHIP}
        by_year = sub.groupby("year").agg(n=("industry", "size"), ind=("industry", "sum"), pat=("patents", lambda x: (x > 0).sum()))
        by_year = by_year.reindex(years).fillna(0)
        fields = win.groupby("field").agg(n=("patents", "size"), cited=("patents", lambda x: (x > 0).sum()),
                                          patents=("patents", "sum"))
        fields = fields[fields["n"] >= 100].assign(share=lambda d: d["cited"] / d["n"]).sort_values("share", ascending=False)
        sectors = []
        for s in SECTORS:
            co_n = int(sub["coauthor_sectors"].str.contains(re.escape(s)).sum())
            cited_n = int((sub[f"cit_{s}"] > 0).sum())
            sectors.append(dict(sector=s, coauthored=co_n, cited_papers=cited_n, citing_works=int(sub[f"cit_{s}"].sum()),
                                any_share=float(((sub["coauthor_sectors"].str.contains(re.escape(s))) |
                                                 (sub[f"cit_{s}"] > 0)).mean()) if len(sub) else None,
                                top_citers=[n for n, _ in sorted(cit_orgs.get(s, Counter()).items(), key=lambda x: (-x[1], str(x[0])))[:4]] if inst == "All" else []))
        top_pat = sub[sub["patents"] > 0].sort_values(["patents", "citations"], ascending=False).head(15)
        out[inst] = dict(
            kpis=dict(
                papers=int(len(sub)), papers_window=int(len(win)),
                patent_cited=int((win["patents"] > 0).sum()), patent_cited_share=_share(win["patents"] > 0),
                patents=int(len(up)), top_offices=[o for o in up["office"].value_counts().head(4).index],
                patents_self=int(up["own"].sum()), offices=int(up["office"].nunique()),
                industry_papers=int(sub["industry"].sum()), industry_share=_share(sub["industry"]),
                companies=int(len(comp_rows)), iisc_startups=int(sum(comp_iisc.values())),
                nonacademic=int(sub["nonacademic_user"].sum()), nonacademic_share=_share(sub["nonacademic_user"]),
                mission_coauthored=int(sub["coauthor_sectors"].str.replace(INDUSTRY, "").str.strip(";").ne("").sum()),
            ),
            offices=[dict(office=o, patents=int(c)) for o, c in up["office"].value_counts().sort_index().sort_values(ascending=False, kind="stable").head(12).items()],
            patent_fields=[dict(field=f, papers=int(r.n), cited=int(r.cited), share=float(r.share), patents=int(r.patents))
                           for f, r in fields.head(14).iterrows()],
            by_year=dict(years=years, papers=by_year["n"].astype(int).tolist(), industry=by_year["ind"].astype(int).tolist(),
                         patent_cited=by_year["pat"].astype(int).tolist(), last_patent_year=last),
            companies=[dict(name=n, papers=int(c), owner=comp_owner[n], iisc=bool(comp_iisc[n]))
                       for n, c in sorted(comp_rows.items(), key=lambda x: (-x[1], x[0]))[:30]],
            ownership=own_counts,
            citing_companies=[dict(name=n, works=int(c)) for n, c in sorted(cit_company.items(), key=lambda x: (-x[1], x[0]))[:15]] if inst == "All" else [],
            sectors=sectors,
            top_patented=[dict(title=r.title, year=int(r.year), homes=r.homes, field=r.field, patents=int(r.patents),
                               patents_self=int(r.patents_self), offices=r.patent_offices,
                               citations=int(r.citations), doi=r.doi) for r in top_pat.itertuples()],
        )
    # evidence table: every paper with a pathway beyond academia, strongest first (full list in the CSV)
    ev = P[(P["patents"] > 0) | P["industry"] | (P["coauthor_sectors"] != "")].copy()
    ev["n_users"] = ev[[f"cit_{s}" for s in SECTORS]].gt(0).sum(axis=1)
    ev = ev.sort_values(["patents", "n_users", "citations"], ascending=False, kind="stable")
    out["evidence"] = [dict(title=(r.title or "")[:200], year=int(r.year), homes=r.homes, field=r.field,
                            patents=int(r.patents), patents_self=int(r.patents_self),
                            companies=r.companies, startup=r.iisc_startup, coauthor_sectors=r.coauthor_sectors,
                            citing_sectors=r.citing_sectors, many_authors=bool(r.many_authors), doi=r.doi)
                       for r in ev.head(2500).itertuples()]
    out["evidence_total"] = int(len(ev))
    fac = t["own_auth"].dropna(subset=["person"]).drop_duplicates(["work_id", "person"])
    names = fac.groupby("work_id")["person"].agg(lambda s: sorted(t["persons"][k]["name"] for k in s))
    P["faculty"] = [names.get(w, []) for w in P.index]
    out["cases"] = case_studies(P, pat, cit_names)
    out["settings"] = dict(min_confidence=config.PATENT_MIN_CONFIDENCE, last_patent_year=last,
                           patents_available=bool(len(pat)))
    if out_dir is not None:
        (out_dir / "stats").mkdir(parents=True, exist_ok=True)
        cols = ["doi", "title", "year", "homes", "field", "citations", "patents", "patents_self",
                "patent_offices", "companies", "company_owners", "iisc_startup", "coauthor_sectors", "coauthor_orgs",
                "citing_sectors"] + [f"cit_{s}" for s in SECTORS]
        P[cols].rename(columns={f"cit_{s}": f"cited_by_{s}" for s in SECTORS}) \
            .to_csv(out_dir / "stats" / "india_pathways_per_paper.csv", encoding="utf-8")
        pd.DataFrame([dict(sector=s["sector"], coauthored_papers=s["coauthored"], papers_cited_by_sector=s["cited_papers"],
                           citing_papers_from_sector=s["citing_works"]) for s in out["All"]["sectors"]]) \
            .to_csv(out_dir / "stats" / "india_pathways_by_sector.csv", index=False, encoding="utf-8")
    return out
