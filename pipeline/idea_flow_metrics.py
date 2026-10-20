"""Distinct-work reach, explicit unknowns and transparent acquisition gates."""
from collections import Counter, defaultdict
import json
import math
from statistics import median

from pipeline.idea_flow import COMPLETE, SELECT, stable_rank, status, utcnow, write_csv, write_json


def composition(seed_field, citers):
    """A paper is one citer; unknown seed/citer fields never become in-field."""
    unique = {r["id"]: r for r in citers}
    counts = Counter(r["field_id"] for r in unique.values() if r.get("field_id"))
    known = sum(counts.values())
    unknown = len(unique) - known
    cross = sum(n for f, n in counts.items() if f != seed_field) if seed_field else None
    return dict(observed_citers=len(unique), known_field_citers=known, unknown_field_citers=unknown,
                cross_field_citers=cross, cross_field_share=cross / known if known and cross is not None else None,
                field_coverage=known / len(unique) if unique else None, richness=len(counts), field_counts=dict(sorted(counts.items())),
                cross_field_lower=cross / len(unique) if unique and cross is not None else None,
                cross_field_upper=(cross + unknown) / len(unique) if unique and cross is not None else None)


def expected_richness(counts, m=10):
    """Exact expected richness under uniform rarefaction, no Monte Carlo noise."""
    n = sum(counts.values())
    if n < m:
        return None
    denominator = math.comb(n, m)
    return sum(1 - (math.comb(n - k, m) / denominator if n - k >= m else 0) for k in counts.values())


def age_window(seed_year, citer_year, cutoff):
    if seed_year is None:
        return "unknown_seed_year"
    # Four full calendar years are comparable only after Dec 31 of y+3.
    if cutoff < f"{seed_year + 3}-12-31":
        return "right_censored"
    if citer_year is None:
        return "unknown_citer_year"
    if citer_year < seed_year:
        return "year_inversion"
    return "eligible" if citer_year <= seed_year + 3 else "outside_window"


def coverage_by_target(study, stage):
    coverage = {}
    for f in study.db.execute("SELECT * FROM frontiers WHERE stage=?", (stage,)):
        for target in json.loads(f["targets"]):
            target = study.canonical(target)
            item = dict(status=f["status"], frontier=f["id"], reason=f["reason"], pages=f["pages"])
            if target not in coverage or f["status"] in COMPLETE:
                coverage[target] = item
    return coverage


def records(study, scope="full"):
    """Stream all incoming edges once; all original seeds retain a result row."""
    seeds = [dict(r) for r in study.db.execute("SELECT * FROM seeds" + (" WHERE pilot=1" if scope == "pilot" else "") + " ORDER BY original_id")]
    canon = {r["canonical_id"] for r in seeds if r["canonical_id"]}
    incoming = defaultdict(list)
    pilot_where=" WHERE e.cited IN (SELECT canonical_id FROM seeds WHERE pilot=1)" if scope=="pilot" else ""
    for r in study.db.execute("SELECT e.citing AS id,e.cited,e.chronology,w.field_id,w.year,w.date,w.type FROM citations e JOIN works w INDEXED BY works_analysis ON w.id=e.citing"+pilot_where):
        if r["cited"] in canon:
            incoming[r["cited"]].append(dict(r))
    all_work_meta = {r["id"]: dict(r) for r in study.db.execute("""SELECT id,field_id,field,year,type,date,
        EXISTS(SELECT 1 FROM json_each(works.data,'$.referenced_works') r
               WHERE r.value='https://openalex.org/'||works.id OR r.value=works.id) AS provider_self_reference
        FROM works WHERE id IN (SELECT canonical_id FROM seeds"""+(" WHERE pilot=1" if scope=="pilot" else "")+")")}
    coverage = coverage_by_target(study, scope)
    full_status = {w:v["status"] for w,v in coverage.items()}
    if scope == "full":
        fallback = coverage_by_target(study, "pilot")
        for w, v in fallback.items():
            if w not in coverage or (coverage[w]["status"] not in COMPLETE and v["status"] in COMPLETE):
                coverage[w] = v
    output = []
    for s in seeds:
        original = json.loads(s["data"])
        wid = s["canonical_id"]
        w = all_work_meta.get(wid, {})
        citers = incoming.get(wid, [])
        c = coverage.get(wid, dict(status="unresolved_identity" if s["identity_status"] == "not_found" else "not_started", frontier=None, reason=None, pages=0))
        comp = composition(w.get("field_id"), citers)
        # n=0 is a count of observed rows, NEVER an acquisition/impact conclusion.
        result = dict(original_id=s["original_id"], canonical_id=wid, homes=original["homes"], title=original["title"],
                      year=original["year"], stored_type=original["stored_type"], stored_citations=original["stored_citations"],
                      citation_band=original["citation_band"], sampling_field=original["sampling_field"],
                      field_id=w.get("field_id"), retrieved_field=w.get("field"), retrieved_type=w.get("type"),
                      retrieved_year=w.get("year"), doi=original.get("doi"), pilot=bool(s["pilot"]),
                      seed_after_cutoff=bool(w.get("date") and w["date"] > study.manifest["cutoff"]),
                      provider_self_reference=bool(w.get("provider_self_reference")),
                      identity_status=s["identity_status"], original_doi_conflict=original["identity_conflict"],
                      field_drift=bool(w.get("field") and w["field"] != original["sampling_field"]),
                      query_status=c["status"], query_complete=c["status"] in COMPLETE, query_frontier=c["frontier"],
                      full_batch_status=full_status.get(wid, "not_started") if scope == "full" else None,
                      query_reason=c["reason"], query_pages=c["pages"], **comp)
        result.update(known_year_citers=sum(x["year"] is not None for x in citers), known_date_citers=sum(bool(x["date"]) for x in citers),
                      known_type_citers=sum(bool(x["type"]) for x in citers),
                      chronology=dict(Counter(x["chronology"] for x in citers)),
                      rarefied_richness_10=expected_richness(comp["field_counts"]), affiliations_collected=False)
        eligibility = Counter(age_window(w.get("year"), x["year"], study.manifest["cutoff"]) for x in citers)
        year_status = age_window(w.get("year"), w.get("year"), study.manifest["cutoff"])
        eligible = [x for x in citers if age_window(w.get("year"), x["year"], study.manifest["cutoff"]) == "eligible"]
        result["age_window"] = dict(status=year_status, rule="publication year through year+3 inclusive; same-year order indeterminate",
                                    eligibility_counts=dict(eligibility), metrics=composition(w.get("field_id"), eligible) if year_status == "eligible" else None)
        output.append(result)
    return output


def compare_checks(study, primary, check):
    complete = coverage_by_target(study, check)
    differences = []
    for target, c in complete.items():
        actual = {r[0] for r in study.db.execute("SELECT DISTINCT citing FROM edge_evidence WHERE cited=? AND frontier_id=?", (target, c["frontier"]))}
        batch = {r[0] for r in study.db.execute("SELECT DISTINCT e.citing FROM edge_evidence e JOIN frontiers f ON f.id=e.frontier_id WHERE e.cited=? AND f.stage=?", (target, primary))}
        differences.append(dict(seed=target, check_complete=c["status"] in COMPLETE, batch_count=len(batch), individual_count=len(actual),
                                missing_from_batch=sorted(actual - batch), additional_in_batch=sorted(batch - actual)))
    return differences


def validate_pilot(study):
    rows = records(study, "pilot")
    comparisons = compare_checks(study, "pilot", "pilot-check")
    primary = study.db.execute("SELECT * FROM frontiers WHERE stage='pilot'").fetchall()
    resume = study.db.execute("SELECT data FROM checks WHERE name='acquisition_pilot'").fetchone()
    resumed = bool(resume and json.loads(resume[0])["requests_this_run"] == 0 and primary)
    gates = dict(unique_24=len(rows) == 24 and len({r["original_id"] for r in rows}) == 24,
                 seed_identities=bool(rows) and all(r["canonical_id"] for r in rows),
                 queries_exhausted=bool(primary) and all(f["status"] in COMPLETE for f in primary),
                 live_pagination=any(f["pages"] >= 2 for f in primary),
                 independent_checks=len(comparisons) >= 3 and all(x["check_complete"] and not x["missing_from_batch"] and not x["additional_in_batch"] for x in comparisons),
                 resume_no_duplicate_requests=resumed,
                 metadata_denominators=all(r["known_field_citers"] + r["unknown_field_citers"] == r["observed_citers"] for r in rows),
                 primary_seed_fields=bool(rows) and all(r["field_id"] for r in rows))
    chosen = json.loads((study.path / "manifests/pilot_selection.json").read_text(encoding="utf-8"))
    result = dict(passed=all(gates.values()), gates=gates, comparisons=comparisons, pilot=rows,
                  selection=chosen, workload=forecast(study, rows), at_utc=utcnow())
    study.check("pilot_acceptance", result)
    return {k: v for k, v in result.items() if k not in ("pilot", "selection")}


def forecast(study, pilot):
    stored = sum(json.loads(r[0])["stored_citations"] for r in study.db.execute("SELECT data FROM seeds"))
    pages = study.db.execute("SELECT coalesce(sum(pages),0) FROM frontiers WHERE stage='pilot'").fetchone()[0]
    edges = sum(r["observed_citers"] for r in pilot)
    # A planning scenario, not an assertion that old counts equal retrievable edges.
    old_pilot = sum(r["stored_citations"] for r in pilot)
    factor = pages * 100 / edges if edges else None
    return dict(stored_full_citation_sum=stored, pilot_observed_edges=edges, pilot_pages=pages,
                pilot_stored_citations=old_pilot, pilot_returned_to_stored_ratio=edges / old_pilot if old_pilot else None,
                scenario_list_calls_at_old_counts=math.ceil(stored * factor / 100) + math.ceil(study.manifest["seed_count"] / 100) if factor else None,
                scenario_cost_usd=(math.ceil(stored * factor / 100) + math.ceil(study.manifest["seed_count"] / 100)) * 0.0001 if factor else None,
                caveat="Pilot deliberately excludes high-volume seeds and other fields. Scenario uses old citation totals, not exact edges; full pagination and actual budget determine completion.")


def summarize(rows):
    # Canonical aliases count once, with unioned home memberships.
    unique = {}
    for r in rows:
        key = r["canonical_id"] or r["original_id"]
        if key not in unique:
            unique[key] = dict(r, homes=list(r["homes"]))
        else:
            unique[key]["homes"] = sorted(set(unique[key]["homes"]) | set(r["homes"]))
    records_ = list(unique.values())
    groups = defaultdict(list)
    for r in records_:
        groups[("institution", ";".join(r["homes"]))].append(r)
        for inst in r["homes"]:
            groups[("institution_membership", inst)].append(r)
        for dim, value in (("field", r["retrieved_field"] or "Unknown"), ("cohort", str(r["year"])),
                           ("type", r["retrieved_type"] or "Unknown"), ("citation_band", r["citation_band"])):
            groups[(dim, value)].append(r)
        groups[("matched_stratum", json.dumps([r["retrieved_field"],r["year"],r["retrieved_type"],r["citation_band"]]))].append(r)
        for inst in r["homes"]:
            groups[("institution_matched_stratum", json.dumps([inst,r["retrieved_field"],r["year"],r["retrieved_type"],r["citation_band"]]))].append(r)
    summaries = []
    for (dim, value), rs in sorted(groups.items()):
        known = sum(r["known_field_citers"] for r in rs)
        defined = [r for r in rs if r["cross_field_share"] is not None]
        cross_denominator = sum(r["known_field_citers"] for r in defined)
        complete = [r for r in defined if r["query_complete"]]
        rarefied = [r["rarefied_richness_10"] for r in rs if r["query_complete"] and r["rarefied_richness_10"] is not None]
        age = [r["age_window"]["metrics"] for r in rs if r["query_complete"] and r["age_window"]["metrics"] is not None]
        age_defined = [r for r in age if r["cross_field_share"] is not None]
        age_denominator = sum(r["known_field_citers"] for r in age_defined)
        summaries.append(dict(dimension=dim, value=value, canonical_seeds=len(rs), completed_queries=sum(r["query_complete"] for r in rs),
                              observed_seed_citer_edges=sum(r["observed_citers"] for r in rs), known_field_citers=known,
                              unknown_field_citers=sum(r["unknown_field_citers"] for r in rs),
                              pooled_cross_field_denominator=cross_denominator,
                              pooled_cross_field_share=sum(r["cross_field_citers"] for r in defined) / cross_denominator if cross_denominator else None,
                              median_complete_seed_share=median([r["cross_field_share"] for r in complete]) if complete else None,
                              complete_seed_share_n=len(complete),
                              known_year_edge_incidences=sum(r["known_year_citers"] for r in rs),
                              known_date_edge_incidences=sum(r["known_date_citers"] for r in rs),
                              known_type_edge_incidences=sum(r["known_type_citers"] for r in rs),
                              unresolved_original_records=sum(not r["canonical_id"] for r in rs),
                              original_doi_conflict_seeds=sum(r["original_doi_conflict"] for r in rs),
                              field_drift_seeds=sum(r["field_drift"] for r in rs),
                              provider_self_reference_seeds=sum(r["provider_self_reference"] for r in rs),
                              chronology_inversion_incidences=sum(r["chronology"].get("year_inversion",0) for r in rs),
                              chronology_same_year_incidences=sum(r["chronology"].get("same_year_indeterminate",0) for r in rs),
                              complete_rarefaction_n=len(rarefied), median_complete_rarefied_richness_10=median(rarefied) if rarefied else None,
                              age_eligible_complete_seeds=len(age),
                              age_censored_seeds=sum(r["age_window"]["status"]=="right_censored" for r in rs),
                              age_known_field_edge_incidences=sum(r["known_field_citers"] for r in age),
                              age_unknown_field_edge_incidences=sum(r["unknown_field_citers"] for r in age),
                              age_pooled_cross_field_denominator=age_denominator,
                              age_pooled_cross_field_share=sum(r["cross_field_citers"] for r in age_defined)/age_denominator if age_denominator else None,
                              interpretation="Descriptive; pooled share is citation-volume weighted; institution memberships overlap on joint works; age and rarefaction summaries use completed queries"))
    return summaries


def full_gate(study):
    frontiers = study.db.execute("SELECT * FROM frontiers WHERE stage='full'").fetchall()
    resolved = {r[0] for r in study.db.execute("SELECT DISTINCT canonical_id FROM seeds WHERE canonical_id IS NOT NULL")}
    planned = {w for f in frontiers for w in json.loads(f["targets"])}
    identities = study.db.execute("SELECT count(*) FROM seeds").fetchone()[0]
    covered = planned == resolved and identities == study.manifest["seed_count"]
    unresolved = study.db.execute("SELECT count(*) FROM seeds WHERE canonical_id IS NULL AND identity_status!='not_found'").fetchone()[0]
    checks = compare_checks(study, "full", "full-check")
    passed = covered and bool(frontiers) and not unresolved and all(r["status"] in COMPLETE for r in frontiers) and len(checks) >= 6 and all(x["check_complete"] and not x["missing_from_batch"] and not x["additional_in_batch"] for x in checks)
    return dict(passed=passed, all_full_frontiers_complete=bool(frontiers) and all(r["status"] in COMPLETE for r in frontiers),
                all_original_records_accounted=identities == study.manifest["seed_count"],
                all_resolved_targets_planned=covered, missing_resolved_targets=sorted(resolved-planned),
                unexpected_targets=sorted(planned-resolved), pending_identity_records=unresolved, independent_checks=checks)


def deeper_reach(study):
    selection = study.db.execute("SELECT data FROM checks WHERE name='g2_selection'").fetchone()
    selection = json.loads(selection[0]) if selection else dict(seeds=[],reason="Full G1 gates or sampling not yet completed")
    summaries, reach, paths = [], [], []
    for s in selection.get("seeds",[]):
        seed = s["seed"]
        g1 = {r[0] for r in study.db.execute("SELECT citing FROM citations WHERE cited=?",(seed,))}
        g2 = set(); overlap=set(); statuses=[]
        for parent in s["sampled_intermediates"]:
            frontiers = [r for r in study.db.execute("SELECT * FROM frontiers WHERE stage='g2'") if parent in json.loads(r["targets"])]
            for f in frontiers:
                statuses.append(f["status"])
                for e in study.db.execute("SELECT DISTINCT citing,cited FROM edge_evidence WHERE frontier_id=?",(f["id"],)):
                    flag="return_to_seed" if e["citing"]==seed else "already_direct" if e["citing"] in g1 else "new_G2"
                    paths.append(dict(seed=seed,intermediate=parent,reached=e["citing"],frontier=f["id"],query_status=f["status"],selection_probability=s["selection_probability"],scope="sampled_G2",path_status=flag))
                    if e["citing"] in g1:
                        overlap.add(e["citing"])
                    elif e["citing"] != seed:
                        g2.add(e["citing"])
        for node in sorted(g2):
            reach.append(dict(seed=seed,reached=node,distance=2,scope="sampled_G2",source_query_complete=bool(statuses) and all(x in COMPLETE for x in statuses)))
        def classify(ids):
            ordered=sorted(ids);out=[]
            for start in range(0,len(ordered),500):
                batch=ordered[start:start+500]
                out.extend(dict(r) for r in study.db.execute("SELECT id,field_id FROM works WHERE id IN ("+",".join("?" for _ in batch)+")",batch))
            return composition(None,out)
        g1_fields,g2_fields=classify(g1),classify(g2)
        summaries.append(dict(seed=seed,g1_distinct=len(g1),sampled_intermediates=len(s["sampled_intermediates"]),g1_population=s["g1_population"],
                              observed_new_g2_distinct=len(g2),g1_g2_overlap=len(overlap),actual_two_edge_paths=sum(p["seed"]==seed and p["reached"]!=seed for p in paths),
                              g1_field_composition=g1_fields,g2_field_composition=g2_fields,
                              observed_new_field_ids=sorted(set(g2_fields["field_counts"])-set(g1_fields["field_counts"])),
                              frontier_statuses=dict(Counter(statuses)),scope="Conditional on sampled intermediates; not a complete G2 population"))
    return dict(selection=selection,seeds=summaries),reach,paths


def analyze(study):
    # Flags describe the frozen normalized metadata, not a later response's
    # possibly changed year. Immutable response evidence remains untouched.
    with study.db:
        study.db.execute("""UPDATE citations SET chronology=(SELECT CASE
          WHEN s.year IS NULL OR t.year IS NULL THEN 'unknown_year'
          WHEN s.year<t.year THEN 'year_inversion'
          WHEN s.year=t.year THEN 'same_year_indeterminate' ELSE 'later_year' END
          FROM works s INDEXED BY works_analysis,works t INDEXED BY works_analysis
          WHERE s.id=citations.citing AND t.id=citations.cited)""")
    rows = records(study)
    pilot = records(study, "pilot")
    summary = summarize(rows)
    gate = full_gate(study)
    print(json.dumps(dict(analysis_progress="seed_metrics_computed",original_seed_rows=len(rows))),flush=True)
    stats = dict(at_utc=utcnow(), study_version=study.manifest["version"], cutoff=study.manifest["cutoff"],
                 original_seeds=len(rows), resolved_original_seeds=sum(bool(r["canonical_id"]) for r in rows),
                 seed_query_status=dict(Counter(r["query_status"] for r in rows)),
                 full_quality_gate=gate, acquired=status(study),
                 unknown_field_edge_incidences=study.db.execute("SELECT count(*) FROM citations e JOIN works w INDEXED BY works_analysis ON w.id=e.citing WHERE w.field_id IS NULL AND e.cited IN (SELECT canonical_id FROM seeds)").fetchone()[0],
                 caveat="Absent acquisition is unknown reach. Completed queries cover OpenAlex Core, not all scholarship. Citations do not prove idea adoption.")
    directory = study.path / "results"
    write_json(directory / "seed_metrics.json", rows)
    write_json(directory / "pilot_metrics.json", pilot)
    write_json(directory / "summary.json", stats)
    write_json(directory / "group_summaries.json", summary)
    cols = [k for k in rows[0] if k not in ("field_counts", "age_window", "chronology")]
    write_csv(directory / "seed_metrics.csv", cols, rows)
    write_csv(directory / "group_summaries.csv", list(summary[0]) if summary else ["dimension", "value"], summary)
    flows=[]
    for inst in ("All","IISc","TIFR"):
        condition="" if inst=="All" else " AND EXISTS (SELECT 1 FROM seeds s,json_each(s.data,'$.homes') h WHERE s.canonical_id=e.cited AND h.value=?)"
        query="""SELECT s.field_id AS seed_field_id,s.field AS seed_field,c.field_id AS citing_field_id,c.field AS citing_field,
                 count(*) AS seed_citer_links,count(DISTINCT e.citing) AS distinct_citing_work_ids,count(DISTINCT e.cited) AS distinct_seed_ids
                 FROM citations e JOIN works s INDEXED BY works_analysis ON s.id=e.cited JOIN works c INDEXED BY works_analysis ON c.id=e.citing
                 WHERE e.cited IN (SELECT canonical_id FROM seeds WHERE canonical_id IS NOT NULL)"""+condition+" GROUP BY s.field_id,c.field_id ORDER BY seed_citer_links DESC"
        flows.extend(dict(r,institution_membership=inst,unit="Distinct ordered work pairs; joint-home memberships overlap") for r in study.db.execute(query,() if inst=="All" else (inst,)))
    write_csv(directory/"field_flows.csv",["institution_membership","seed_field_id","seed_field","citing_field_id","citing_field","seed_citer_links","distinct_citing_work_ids","distinct_seed_ids","unit"],flows)
    write_json(directory/"field_flows.json",flows)
    write_csv(directory / "frontiers.csv", [r[1] for r in study.db.execute("PRAGMA table_info(frontiers)")], (dict(r) for r in study.db.execute("SELECT * FROM frontiers ORDER BY stage,id")))
    def work_rows():
        original_dois=defaultdict(set)
        for seed in study.db.execute("SELECT canonical_id,data FROM seeds"):
            original=json.loads(seed["data"])
            if seed["canonical_id"] and original.get("doi"):
                original_dois[seed["canonical_id"]].add(original["doi"])
        for r in study.db.execute("SELECT * FROM works ORDER BY id"):
            data=json.loads(r["data"]);pt=data.get("primary_topic") or {};loc=data.get("primary_location") or {};source=loc.get("source") or {}
            row={k:r[k] for k in ("id","doi","title","year","date","type","field_id","field","snapshot")}
            row.update(external_ids=data.get("ids") or {},doi_aliases=sorted(original_dois.get(r["id"],set())|({r["doi"]} if r["doi"] else set())),
                       date_precision="provider_date_precision_unverified" if r["date"] else "year_only" if r["year"] else "unknown",
                       venue=source.get("display_name"),source_id=source.get("id"),topic_id=pt.get("id"),topic=pt.get("display_name"),
                       subfield_id=(pt.get("subfield") or {}).get("id"),subfield=(pt.get("subfield") or {}).get("display_name"),
                       domain_id=(pt.get("domain") or {}).get("id"),domain=(pt.get("domain") or {}).get("display_name"),
                       cited_by_count=data.get("cited_by_count"),referenced_works_count=len(data.get("referenced_works") or []),
                       updated_date=data.get("updated_date"),created_date=data.get("created_date"),language=data.get("language"),
                       is_retracted=data.get("is_retracted"),is_xpac=data.get("is_xpac"),field_missing=not bool(r["field_id"]),
                       provider_self_reference=any(v in (r["id"],"https://openalex.org/"+r["id"]) for v in (data.get("referenced_works") or [])),
                       reference_storage="Full IDs in frozen works.data JSON and response snapshot; exact study edges in citations.csv")
            yield row
    work_columns=["id","doi","doi_aliases","external_ids","title","year","date","date_precision","type","venue","source_id","field_id","field","subfield_id","subfield","domain_id","domain","topic_id","topic","cited_by_count","referenced_works_count","updated_date","created_date","language","is_retracted","is_xpac","field_missing","provider_self_reference","snapshot","reference_storage"]
    write_csv(directory / "works.csv", work_columns, work_rows())
    print(json.dumps(dict(analysis_progress="normalized_work_export_written")),flush=True)
    write_csv(directory / "citations.csv", ["citing","cited","chronology"], (dict(r) for r in study.db.execute("SELECT * FROM citations ORDER BY cited,citing")))
    write_csv(directory / "aliases.csv", ["original_id","canonical_id","evidence","retrieved_utc"], (dict(r) for r in study.db.execute("SELECT * FROM aliases ORDER BY original_id")))
    write_csv(directory / "doi_conflicts.csv", ["doi","work_ids","count"], (dict(doi=r[0],work_ids=r[1].split(","),count=r[2]) for r in study.db.execute("SELECT doi,group_concat(id),count(*) FROM works INDEXED BY works_doi_ids WHERE doi!='' GROUP BY doi HAVING count(*)>1 ORDER BY doi")))
    write_csv(directory / "edge_evidence.csv", ["citing","cited","frontier_id","page","retrieved_utc"], (dict(r) for r in study.db.execute("SELECT * FROM edge_evidence ORDER BY cited,citing,frontier_id,page")))
    deeper, extra_reach, paths = deeper_reach(study)
    write_json(directory / "g2_summary.json", deeper)
    coverage = coverage_by_target(study,"full")
    def reach_rows():
        for r in study.db.execute("SELECT citing,cited FROM citations WHERE cited IN (SELECT canonical_id FROM seeds) ORDER BY cited,citing"):
            if r[0] != r[1]:
                yield dict(seed=r[1],reached=r[0],distance=1,scope="direct_observed",source_query_complete=coverage.get(r[1],{}).get("status") in COMPLETE)
        yield from extra_reach
    write_csv(directory / "reach.csv", ["seed","reached","distance","scope","source_query_complete"], reach_rows())
    write_csv(directory / "sampled_paths.csv", ["seed","intermediate","reached","frontier","query_status","selection_probability","scope","path_status"], paths)
    # Store accurate gates independently of acquisition state reports.
    study.check("full_acceptance", gate)
    study.check("analysis_latest", {k:v for k,v in stats.items() if k != "acquired"})
    return {k:v for k,v in stats.items() if k != "acquired"}


def sample_g2(study):
    gate = full_gate(study)
    if not gate["passed"]:
        result = dict(eligible_to_acquire=False, reason="Full direct-citer quality gate not passed", seeds=[], unfilled=["IISc","TIFR"])
        study.check("g2_selection", result)
        return result
    rs = records(study)
    selected, used, slots = [], set(), []
    for inst in ("IISc", "TIFR"):
        candidates = [r for r in rs if inst in r["homes"] and r["query_complete"] and r["canonical_id"] and r["field_id"] and not r["original_doi_conflict"] and r["known_field_citers"] >= 10 and r["field_coverage"] >= 0.9]
        candidates.sort(key=lambda r: stable_rank(r["original_id"], "g2-seed-v1|42|"))
        s = next((r for r in candidates if r["canonical_id"] not in used), None)
        if not s:
            slots.append(inst); continue
        used.add(s["canonical_id"])
        g1 = [r[0] for r in study.db.execute("SELECT citing FROM citations WHERE cited=?", (s["canonical_id"],))]
        ordered = sorted(g1, key=lambda w: stable_rank(w, "g2-intermediates-v1|42|" + s["canonical_id"] + "|"))
        probability = min(10, len(g1)) / len(g1)
        entry = dict(seed=s["canonical_id"], original_id=s["original_id"], allocated_institution=inst, all_homes=s["homes"],
                     g1_population=len(g1), sampled_intermediates=ordered[:10], selection_probability=probability)
        selected.append(entry)
        for wid in entry["sampled_intermediates"]:
            params = dict(filter="cites:" + wid + ",to_publication_date:" + study.manifest["cutoff"], corpus="core", select=SELECT, per_page=100)
            study.frontier("g2", "citers", [wid], params, sampling=dict(seed=s["canonical_id"], probability=probability, population=len(g1)))
    result = dict(eligible_to_acquire=bool(selected), seeds=selected, unfilled=slots,
                  selection_rule="Lowest predeclared hash among eligible seeds; ten hash-selected intermediates, no outcome ranking", scope="Sampled G2, no unweighted global G2 estimates")
    study.check("g2_selection", result)
    write_json(study.path / "manifests/g2_selection.json", result, immutable=True)
    return result
