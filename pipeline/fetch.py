"""Step 1 - data collection from OpenAlex.

  corpus   : all works 2016-2026 with an author affiliated to each assigned institution
  authors  : author profiles (career h-index, ORCID, affiliation history) for institutional authors
  outflow  : Indian works (other institutions) *referenced by* our corpus   -> cites_indian_inst
  inflow   : Indian works (other institutions) *citing* our corpus          -> cited_by_indian_inst
  partners : research-topic profile of top partner institutions (for Jaccard similarity)

All calls are cached (see openalex.py), so every step can be re-run / resumed.
"""
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


def load_corpus():
    """dict work_id -> work, plus dict work_id -> set(assigned institutions).

    A work belongs to an institution if at least one authorship counts for it (see authorship_insts).
    OpenAlex truncates long author lists (100 authors), so for a work returned by the institution's query
    in which no visible authorship carries the institution ID, the query result is trusted."""
    works, homes = {}, {}
    for inst in config.INSTITUTIONS:
        ids = set(config.INSTITUTIONS[inst]["openalex_ids"])
        for w in read_jsonl(corpus_path(inst)) or []:
            wid = short_id(w["id"])
            auths = w.get("authorships", [])
            h = {i for a in auths for i in authorship_insts(a)}
            visible = any(ids & {short_id(i.get("id")) for i in a.get("institutions", []) if i.get("id")} for a in auths)
            if not visible:
                h.add(inst)
            if h:
                works[wid] = w
                homes.setdefault(wid, set()).update(h)
    return works, homes


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
    for inst in config.INSTITUTIONS:
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
