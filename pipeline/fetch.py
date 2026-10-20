"""Step 1 - data collection from OpenAlex.

  corpus   : all works 2016-2026 with an author affiliated to each assigned institution
  authors  : author profiles (career h-index, ORCID, affiliation history) for institutional authors
  outflow  : Indian works (other institutions) *referenced by* our corpus   -> cites_indian_inst
  inflow   : Indian works (other institutions) *citing* our corpus          -> cited_by_indian_inst
  partners : research-topic profile of top partner institutions (for Jaccard similarity)

All calls are cached (see openalex.py), so every step can be re-run / resumed.
"""
import os
import re
from collections import Counter

import config
from pipeline.io_utils import read_jsonl, write_jsonl
from pipeline.openalex import OpenAlex, chunks, short_id

WORK_SELECT = ",".join([
    "id", "doi", "title", "publication_year", "publication_date", "type", "primary_location",
    "authorships", "cited_by_count", "referenced_works", "primary_topic", "counts_by_year",
    "fwci", "is_retracted", "corresponding_author_ids", "language",
])
AUTHOR_SELECT = ",".join([
    "id", "display_name", "display_name_alternatives", "orcid", "works_count", "cited_by_count",
    "summary_stats", "affiliations", "last_known_institutions",
])


def corpus_path(inst):
    return config.RAW / f"works_{inst}.jsonl.gz"


def slim_work(w):
    """Drop bulky fields we never use."""
    for a in w.get("authorships", []):
        a.pop("affiliations", None)
        a.pop("raw_orcid", None)
        if a.get("author"):
            a["author"].pop("observed_orcids", None)
    pl = w.get("primary_location") or {}
    for k in ("license", "license_id", "pdf_url", "landing_page_url", "is_accepted", "is_published"):
        pl.pop(k, None)
    src = pl.get("source") or {}
    for k in ("host_organization_lineage", "host_organization_lineage_names", "listed_in", "is_in_doaj"):
        src.pop(k, None)
    return w


def inst_filter_ids(inst):
    return "|".join(config.INSTITUTIONS[inst]["openalex_ids"])


def all_own_ids():
    return {i for v in config.INSTITUTIONS.values() for i in v["openalex_ids"]}


# --------------------------------------------------------------------------- corpus
def fetch_corpus(oa: OpenAlex):
    for inst in config.INSTITUTIONS:
        def gen():
            for types in (config.WORK_TYPES, config.CONFERENCE_TYPES):
                flt = (f"authorships.institutions.id:{inst_filter_ids(inst)},"
                       f"publication_year:{config.YEAR_FROM}-{config.YEAR_TO},"
                       f"type:{'|'.join(types)}")
                total = oa.count("/works", flt)
                print(f"[corpus] {inst} {'|'.join(types)}: {total} works -> ~{total // 100 + 1} calls")
                for w in oa.paginate("/works", flt, WORK_SELECT):
                    yield slim_work(w)
        n = write_jsonl(corpus_path(inst), gen())
        print(f"[corpus] {inst}: saved {n} works")


_TIFR_CENTRE = re.compile(config.TIFR_CENTRE_PATTERN, re.I)


def authorship_insts(a):
    """Assigned institutions this authorship counts for (TIFR only if the author is at the Mumbai campus)."""
    ids = {short_id(i.get("id")) for i in a.get("institutions", []) if i.get("id")}
    out = []
    for inst, v in config.INSTITUTIONS.items():
        if not ids & set(v["openalex_ids"]):
            continue
        if inst == "TIFR":
            raw = " ".join(a.get("raw_affiliation_strings") or [])
            tifr_raw = [r for r in (a.get("raw_affiliation_strings") or []) if re.search(r"tata inst|tifr", r, re.I)]
            at_centre = (bool(ids & set(config.TIFR_CHILD_CENTRES))
                         or (tifr_raw and all(_TIFR_CENTRE.search(r) for r in tifr_raw))
                         or (not tifr_raw and _TIFR_CENTRE.search(raw)))
            if at_centre:
                continue
        out.append(inst)
    return out


FULL_AUTH_PATH = config.RAW / "full_authorships.jsonl.gz"


def load_full_authorships():
    """Full author lists (from single-work lookups) for works whose list-API author list was truncated."""
    return {r["id"]: r for r in read_jsonl(FULL_AUTH_PATH) or []}


def load_corpus():
    """dict work_id -> work, plus dict work_id -> set(assigned institutions).

    A work belongs to an institution if at least one authorship counts for it (see authorship_insts).
    The list API truncates author lists at 100, so a work with no visible authorship of the institution is
    trusted only until its full author list has been fetched (`fullauthors` step); if the full list still
    shows no author of ours, the work is dropped (mis-tagged by OpenAlex)."""
    works, homes = {}, {}
    full = load_full_authorships()
    for inst in config.INSTITUTIONS:
        ids = set(config.INSTITUTIONS[inst]["openalex_ids"])
        for w in read_jsonl(corpus_path(inst)) or []:
            wid = short_id(w["id"])
            if wid in full:   # replace the truncated author list (Indian authorships + true author count)
                w["authorships"] = full[wid]["authorships"]
                w["authors_count"] = full[wid]["n_authors"]
            auths = w.get("authorships", [])
            h = {i for a in auths for i in authorship_insts(a)}
            visible = any(ids & {short_id(i.get("id")) for i in a.get("institutions", []) if i.get("id")} for a in auths)
            if not visible and wid not in full:
                h.add(inst)
            if h:
                works[wid] = w
                homes.setdefault(wid, set()).update(h)
    return works, homes


def fetch_full_authorships(oa: OpenAlex, workers=8):
    """The list API returns at most 100 authors per work. For works with a capped list, or where none of the
    visible authors carries our institution ID, fetch the full record with a single-work lookup (free under
    OpenAlex pricing). Only Indian authorships are kept, plus the true author count."""
    from concurrent.futures import ThreadPoolExecutor
    own = all_own_ids()
    targets = set()
    for inst in config.INSTITUTIONS:
        for w in read_jsonl(corpus_path(inst)) or []:
            auths = w.get("authorships", [])
            visible = any(own & {short_id(i.get("id")) for i in a.get("institutions", []) if i.get("id")} for a in auths)
            if len(auths) >= 100 or not visible:
                targets.add(short_id(w["id"]))
    done = load_full_authorships()
    todo = sorted(targets - set(done))
    print(f"[full-authors] {len(targets)} works need full author lists; {len(todo)} still to fetch")

    def one(wid):
        try:
            w = oa.get(f"/works/{wid}", {"select": "id,authorships"}, use_cache=False)
        except Exception as e:   # keep going; a later run retries
            print(f"   {wid}: {e!r}"[:200])
            return None
        auths = w.get("authorships", [])
        keep = [a for a in slim_work({"authorships": auths})["authorships"]
                if any(i.get("country_code") == "IN" for i in a.get("institutions", []))]
        return {"id": wid, "n_authors": len(auths), "authorships": keep}

    out = list(done.values())
    with ThreadPoolExecutor(workers) as ex:
        for k, rec in enumerate(ex.map(one, todo)):
            if rec:
                out.append(rec)
            if k % 500 == 499:
                write_jsonl(FULL_AUTH_PATH, out)
                print(f"   {k + 1}/{len(todo)} fetched")
    write_jsonl(FULL_AUTH_PATH, out)
    print(f"[full-authors] saved {len(out)} full author lists")


# --------------------------------------------------------------------------- authors
def institutional_author_counts(works):
    cnt = Counter()
    for w in works.values():
        for a in w.get("authorships", []):
            if authorship_insts(a) and a.get("author", {}).get("id"):
                cnt[short_id(a["author"]["id"])] += 1
    return cnt


def fetch_authors(oa: OpenAlex, min_papers=3):
    works, _ = load_corpus()
    cnt = institutional_author_counts(works)
    ids = sorted(a for a, c in cnt.items() if c >= min_papers)
    print(f"[authors] {len(cnt)} institutional authors, fetching {len(ids)} with >= {min_papers} papers "
          f"(~{len(ids) // 100 + 1} calls)")
    out = []
    for batch in chunks(ids, 100):
        out.extend(oa.paginate("/authors", "ids.openalex:" + "|".join(batch), AUTHOR_SELECT))
    n = write_jsonl(config.RAW / "authors.jsonl.gz", out)
    print(f"[authors] saved {n}")


def fetch_missing_profiles(oa: OpenAlex):
    """Author profiles for matched faculty IDs that have none yet (free single lookups). Uses the
    faculty list of the last build, so run it after `python run.py build`."""
    import pandas as pd
    fl = config.OUTPUTS / "faculty_list.csv"
    if not fl.exists():
        print("[profiles] no faculty_list.csv yet - run a build first")
        return
    fac = pd.read_csv(fl, dtype=str)
    path = config.RAW / "authors.jsonl.gz"
    have = {short_id(a["id"]): a for a in read_jsonl(path) or []}
    want = {i for ids in fac["openalex_ids"].dropna() for i in ids.split(";") if i.startswith("A")}
    todo = sorted(want - set(have))
    print(f"[profiles] {len(todo)} faculty author IDs without a profile")
    for aid in todo:
        try:
            have[aid] = oa.get(f"/authors/{aid}", {"select": AUTHOR_SELECT})
        except Exception as e:
            print(f"   {aid}: {e!r}"[:200])
    write_jsonl(path, have.values())
    print(f"[profiles] {len(have)} author profiles saved")


# --------------------------------------------------------------------------- Indian flows
def compact_external(w, corpus_ids=None):
    insts = {}
    for a in w.get("authorships", []):
        for i in a.get("institutions", []):
            if i.get("country_code") == "IN" and i.get("id"):
                insts[short_id(i["id"])] = {"id": short_id(i["id"]), "name": i.get("display_name"),
                                           "type": i.get("type")}
    rec = {"id": short_id(w["id"]), "doi": w.get("doi"), "year": w.get("publication_year"),
           "insts": list(insts.values())}
    if corpus_ids is not None:
        rec["cites"] = [short_id(r) for r in w.get("referenced_works", []) if short_id(r) in corpus_ids]
    return rec


def fetch_flows(oa: OpenAlex, which=("outflow", "inflow")):
    works, homes = load_corpus()
    corpus_ids = set(works)
    # DPCN_REVERSE=1: walk institutions and batches backwards, so a second process with another
    # team member's key can work from the other end; each skips what the other already cached.
    reverse = os.environ.get("DPCN_REVERSE") == "1"
    for inst in (list(config.INSTITUTIONS)[::-1] if reverse else config.INSTITUTIONS):
        own_neg = ",".join(f"authorships.institutions.id:!{i}" for i in config.INSTITUTIONS[inst]["openalex_ids"])
        if "outflow" in which:
            # Indian works (not involving this institution) referenced by our papers.
            seen = {}
            batches = flow_batches(homes, works, inst, "outflow")
            print(f"[outflow] {inst}: {len(batches)} batches of citing papers")
            for k, batch in enumerate(batches):
                flt = f"cited_by:{'|'.join(batch)},authorships.countries:IN,{own_neg}"
                for w in oa.paginate("/works", flt, "id,doi,publication_year,authorships"):
                    seen[short_id(w["id"])] = compact_external(w)
                if k % 50 == 0:
                    print(f"   batch {k}: {len(seen)} Indian referenced works so far; {oa.status()}")
            write_jsonl(config.RAW / f"outflow_{inst}.jsonl.gz", seen.values())
            print(f"[outflow] {inst}: {len(seen)} Indian referenced works")
        if "inflow" in which:
            # Indian works (not involving this institution) citing our papers.
            seen = {}
            batches = flow_batches(homes, works, inst, "inflow")
            if reverse:
                batches = batches[::-1]
            print(f"[inflow] {inst}: {len(batches)} batches of cited papers")
            for k, batch in enumerate(batches):
                flt = f"cites:{'|'.join(batch)},authorships.countries:IN,{own_neg}"
                for w in oa.paginate("/works", flt, "id,doi,publication_year,authorships,referenced_works"):
                    rec = compact_external(w, corpus_ids)
                    prev = seen.get(rec["id"])
                    if prev:
                        rec["cites"] = sorted(set(prev["cites"]) | set(rec["cites"]))
                    seen[rec["id"]] = rec
                if k % 50 == 0:
                    print(f"   batch {k}: {len(seen)} Indian citing works so far; {oa.status()}")
            write_jsonl(config.RAW / f"inflow_{inst}.jsonl.gz", seen.values())
            print(f"[inflow] {inst}: {len(seen)} Indian citing works")


def fetch_flows_new_papers(oa: OpenAlex):
    """Flows for papers that joined an institute's set after the flow fetch (e.g. through full author lists):
    queried in their own batches and merged into the existing out/inflow files."""
    works, homes = load_corpus()
    corpus_ids = set(works)
    for inst in config.INSTITUTIONS:
        have_out = {r["id"]: r for r in read_jsonl(config.RAW / f"outflow_{inst}.jsonl.gz") or []}
        have_in = {r["id"]: r for r in read_jsonl(config.RAW / f"inflow_{inst}.jsonl.gz") or []}
        covered = config.RAW / f"flows_covered_{inst}.txt"
        done = set(covered.read_text().split()) if covered.exists() else set()
        old = _homes_without_full_lists()
        new = sorted(w for w, h in homes.items() if inst in h and inst not in old.get(w, set()) and w not in done)
        if not new:
            continue
        own_neg = ",".join(f"authorships.institutions.id:!{i}" for i in config.INSTITUTIONS[inst]["openalex_ids"])
        print(f"[flows-new] {inst}: {len(new)} papers")
        for batch in chunks([w for w in new if works[w].get("referenced_works")], 100):
            for w in oa.paginate("/works", f"cited_by:{'|'.join(batch)},authorships.countries:IN,{own_neg}",
                                 "id,doi,publication_year,authorships"):
                have_out.setdefault(short_id(w["id"]), compact_external(w))
        for batch in chunks([w for w in new if works[w].get("cited_by_count", 0) > 0], 100):
            for w in oa.paginate("/works", f"cites:{'|'.join(batch)},authorships.countries:IN,{own_neg}",
                                 "id,doi,publication_year,authorships,referenced_works"):
                rec = compact_external(w, corpus_ids)
                prev = have_in.get(rec["id"])
                if prev:
                    rec["cites"] = sorted(set(prev["cites"]) | set(rec["cites"]))
                have_in[rec["id"]] = rec
        write_jsonl(config.RAW / f"outflow_{inst}.jsonl.gz", have_out.values())
        write_jsonl(config.RAW / f"inflow_{inst}.jsonl.gz", have_in.values())
        covered.write_text(" ".join(sorted(done | set(new))))
        print(f"[flows-new] {inst}: now {len(have_out)} out-flow and {len(have_in)} in-flow works")


def _homes_without_full_lists():
    """Institution sets as they were before full author lists were applied (when the flows were fetched)."""
    global load_full_authorships
    orig = load_full_authorships
    load_full_authorships = lambda: {}
    try:
        return load_corpus()[1]
    finally:
        load_full_authorships = orig


def flow_batches(homes, works, inst, kind):
    """Deterministic 100-paper batches (shared by fetch and build so per-batch counts line up).
    Conference papers (added later) go after the journal papers so earlier cached batches stay valid."""
    ids = sorted((w for w, h in homes.items() if inst in h),
                 key=lambda w: (works[w].get("type") in config.CONFERENCE_TYPES, w))
    if kind == "outflow":
        ids = [w for w in ids if works[w].get("referenced_works")]
    else:
        ids = [w for w in ids if works[w].get("cited_by_count", 0) > 0]
    return list(chunks(ids, 100))


def fetch_inflow_aggregate(oa: OpenAlex):
    """Cheap in-flow: per 100-paper batch, group the Indian citing works (not involving our institution)
    by institution and by year -> 2 calls per batch instead of ~60 for full edges.
    Unit = distinct citing works per batch (summed over batches)."""
    works, homes = load_corpus()
    for inst in config.INSTITUTIONS:
        own_neg = ",".join(f"authorships.institutions.id:!{i}" for i in config.INSTITUTIONS[inst]["openalex_ids"])
        batches = flow_batches(homes, works, inst, "inflow")
        print(f"[inflow-agg] {inst}: {len(batches)} batches -> {2 * len(batches)} calls")
        by_inst, by_year, names, per_batch = Counter(), Counter(), {}, []
        for k, batch in enumerate(batches):
            flt = f"cites:{'|'.join(batch)},authorships.countries:IN,{own_neg}"
            yrs = oa.group_by("/works", flt, "publication_year")
            per_batch.append(sum(g["count"] for g in yrs))
            for g in yrs:
                by_year[int(g["key"])] += g["count"]
            for g in oa.group_by("/works", flt, "authorships.institutions.id"):
                iid = short_id(g["key"])
                by_inst[iid] += g["count"]
                names[iid] = g.get("key_display_name")
            if k % 50 == 0:
                print(f"   batch {k}/{len(batches)}; {oa.status()}")
        write_jsonl(config.RAW / f"inflow_agg_{inst}.jsonl.gz", [dict(
            by_inst={i: [names[i], c] for i, c in by_inst.items()}, by_year=dict(by_year), per_batch=per_batch)])
        print(f"[inflow-agg] {inst}: {sum(per_batch)} Indian citing works (per-batch distinct)")


def fetch_institution_meta(oa: OpenAlex):
    """Country/type for institutions seen only in aggregated in-flow (batched list calls)."""
    works, _ = load_corpus()
    known = {short_id(i["id"]) for w in works.values() for a in w.get("authorships", [])
             for i in a.get("institutions", []) if i.get("id")}
    need = set()
    for inst in config.INSTITUTIONS:
        for r in read_jsonl(config.RAW / f"inflow_agg_{inst}.jsonl.gz") or []:
            need |= set(r["by_inst"])
    path = config.RAW / "institutions_extra.jsonl.gz"
    have = {r["id"] for r in read_jsonl(path) or []}
    todo = sorted(need - known - have)
    out = list(read_jsonl(path) or [])
    for batch in chunks(todo, 100):
        for i in oa.paginate("/institutions", "ids.openalex:" + "|".join(batch), "id,display_name,country_code,type"):
            out.append({"id": short_id(i["id"]), "name": i["display_name"], "country": i.get("country_code"),
                        "type": i.get("type")})
    write_jsonl(path, out)
    print(f"[institutions] metadata for {len(out)} extra institutions")


# --------------------------------------------------------------------------- journals (sources)
SOURCE_SELECT = ",".join(["id", "display_name", "type", "issn_l", "host_organization_name", "country_code",
                          "is_oa", "is_in_doaj", "apc_usd", "summary_stats", "works_count"])


def fetch_sources(oa: OpenAlex):
    """Metadata of every journal/conference our papers appear in: publisher, country, open access, APC and
    OpenAlex's 2-year mean citedness (the impact-factor equivalent)."""
    works, _ = load_corpus()
    ids = sorted({short_id(((w.get("primary_location") or {}).get("source") or {}).get("id")) for w in works.values()} - {None})
    print(f"[sources] {len(ids)} journals/venues -> ~{len(ids) // 100 + 1} calls")
    out = []
    for batch in chunks(ids, 100):
        out.extend(oa.paginate("/sources", "ids.openalex:" + "|".join(batch), SOURCE_SELECT))
    n = write_jsonl(config.RAW / "sources.jsonl.gz", out)
    print(f"[sources] saved {n}")


# --------------------------------------------------------------------------- national relevance
# Words/places marking a study set in or about India (searched in title + abstract). "Indian Institute of ..."
# style affiliation phrases are removed first so author addresses do not count.
INDIA_TERMS = re.compile(
    r"\b(india|indian|bharat|andhra pradesh|arunachal|assam|bihar|chhattisgarh|goa|gujarat|haryana|himachal|"
    r"jharkhand|karnataka|kerala|madhya pradesh|maharashtra|manipur|meghalaya|mizoram|nagaland|odisha|orissa|"
    r"punjab|rajasthan|sikkim|tamil nadu|telangana|tripura|uttar pradesh|uttarakhand|west bengal|jammu|kashmir|"
    r"ladakh|delhi|puducherry|andaman|lakshadweep|bengaluru|bangalore|mumbai|chennai|kolkata|hyderabad|pune|"
    r"ahmedabad|varanasi|himalaya|himalayan|western ghats|eastern ghats|deccan|ganga|ganges|brahmaputra|"
    r"indo-gangetic|sundarbans|thar desert|isro|chandrayaan|mangalyaan|aditya-l1|astrosat|gmrt|indigen)\b", re.I)
_AFFIL = re.compile(r"indian (institute|council|statistical|association|academy|national|space research)\w*", re.I)


def _abstract(inv):
    if not inv:
        return ""
    pos = [(i, w) for w, idx in inv.items() for i in idx]
    return " ".join(w for _, w in sorted(pos))


def fetch_relevance(oa: OpenAlex):
    """Per paper: OpenAlex SDG tags, top-1%/10% citation flags, and India-related terms in title/abstract."""
    works, _ = load_corpus()
    out = []
    for batch in chunks(sorted(works), 100):
        for w in oa.paginate("/works", "ids.openalex:" + "|".join(batch),
                             "id,title,sustainable_development_goals,abstract_inverted_index,citation_normalized_percentile"):
            abstract = _abstract(w.get("abstract_inverted_index"))
            text = _AFFIL.sub(" ", f"{w.get('title') or ''} {abstract}")
            terms = sorted({m.group(1).lower() for m in INDIA_TERMS.finditer(text)})
            cnp = w.get("citation_normalized_percentile") or {}
            out.append(dict(id=short_id(w["id"]), has_abstract=bool(abstract), india_terms=terms,
                            sdgs=[dict(id=short_id(g["id"]), name=g.get("display_name"), score=g.get("score"))
                                  for g in w.get("sustainable_development_goals") or []],
                            top1=bool(cnp.get("is_in_top_1_percent")), top10=bool(cnp.get("is_in_top_10_percent"))))
    n = write_jsonl(config.RAW / "relevance.jsonl.gz", out)
    print(f"[relevance] {n} papers: SDG tags, top-percentile flags and India terms")


# --------------------------------------------------------------------------- patents citing our papers
PATENTS_PATH = config.RAW / "patent_citations.csv.gz"


def fetch_patent_citations(source=None):
    """Patents citing our papers, from the Reliance on Science dataset (no OpenAlex calls).

    Streams the 2.5 GB `_pcs_oa.csv` (config.PATENT_CITATIONS_URL, or a local copy given by `source` / env
    DPCN_PATENT_FILE) and keeps only the rows for our papers. Its `oaid` is the number of the OpenAlex work ID.
    """
    import csv
    import gzip
    import io
    import requests
    works, _ = load_corpus()
    ours = {wid[1:] for wid in works}
    source = source or os.environ.get("DPCN_PATENT_FILE")
    if source:
        stream = open(source, encoding="utf-8", newline="")
    else:
        print(f"[patents] streaming {config.PATENT_CITATIONS_URL} (~2.5 GB) ...")
        r = requests.get(config.PATENT_CITATIONS_URL, stream=True, timeout=600)
        r.raise_for_status()
        stream = io.TextIOWrapper(r.raw, encoding="utf-8", newline="")
    reader = csv.reader(stream)
    head = next(reader)
    col = {c: i for i, c in enumerate(head)}
    keep, n = [], 0
    for row in reader:
        n += 1
        if row[col["oaid"]] in ours:
            keep.append(("W" + row[col["oaid"]], row[col["patent"]], row[col["confscore"]], row[col["reftype"]],
                         row[col["wherefound"]], row[col["self"]]))
        if n % 10_000_000 == 0:
            print(f"[patents] {n:,} rows read, {len(keep):,} cite our papers", flush=True)
    stream.close()
    keep.sort()
    tmp = PATENTS_PATH.with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["work_id", "patent", "confscore", "reftype", "wherefound", "self"])
        w.writerows(keep)
    tmp.replace(PATENTS_PATH)
    print(f"[patents] {n:,} rows read; {len(keep):,} patent citations to {len({k[0] for k in keep}):,} of our papers")


# --------------------------------------------------------------------------- partner topics
def fetch_partner_topics(oa: OpenAlex, partner_ids):
    """Subfield publication counts 2016-2026 for each partner institution (1 group_by call each)."""
    out = []
    for pid in partner_ids:
        flt = f"authorships.institutions.lineage:{pid},publication_year:{config.YEAR_FROM}-{config.YEAR_TO}"
        groups = oa.group_by("/works", flt, "primary_topic.subfield.id")
        out.append({"id": pid, "subfields": {short_id(g["key"]): g["count"] for g in groups
                                             if g.get("key") and g["key"] != "unknown"}})
    write_jsonl(config.RAW / "partner_topics.jsonl.gz", out)
    print(f"[partners] topic profiles for {len(out)} partner institutions")
