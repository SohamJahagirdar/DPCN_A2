"""Build a self-contained, bounded explorer outside the historical dashboard."""
import json
from pathlib import Path
import shutil
import sys

from pipeline.idea_flow import outside, sha256, utcnow, write_json
from pipeline.idea_flow_metrics import analyze, records, summarize


def candidate_cases(rows):
    eligible = [r for r in rows if r["query_complete"] and r["field_id"] and r["known_field_citers"] >= 5 and r["field_coverage"] >= .9 and not r["original_doi_conflict"]]
    chosen, seen = [], set()
    selectors = [
        ("Cross-field candidate", sorted(eligible,key=lambda r:(-r["cross_field_share"],r["original_id"]))),
        ("Modest-volume candidate", sorted((r for r in eligible if r["stored_citations"]<100 and r["cross_field_citers"]>0),key=lambda r:(r["stored_citations"],-r["cross_field_share"],r["original_id"]))),
        ("Comparison candidate", sorted(eligible,key=lambda r:(r["cross_field_share"],r["original_id"])))]
    for label, pool in selectors:
        r = next((r for r in pool if r["canonical_id"] not in seen),None)
        if r:
            seen.add(r["canonical_id"])
            chosen.append(dict(role=label,seed=r["canonical_id"],original_id=r["original_id"],title=r["title"],
                               cross_field_share=r["cross_field_share"],known_denominator=r["known_field_citers"],
                               observed_citers=r["observed_citers"],source_query_complete=True,
                               evidence_status="Bibliographic candidate only; actual paper/citation passages not yet manually verified",
                               paper_text_verified=False))
    return dict(rule="Complete queries, >=5 known citers, >=90% field coverage, no original DOI conflict; deterministic cross-field/modest-volume/comparison ranking; no claim of adoption",
                candidates=chosen, evaluated_candidates=len(eligible), unselected_candidate_count=max(0,len(eligible)-len(chosen)),
                limitation="Illustrative candidates, not representative estimates or verified idea-adoption stories")


def preview(study, directory):
    path = outside(directory, study.manifest["repository"])
    if path == study.path or path in study.path.parents or study.path in path.parents:
        raise ValueError("Preview and study-data directories must be separate")
    marker = path / "preview_manifest.json"
    if path.exists() and any(path.iterdir()) and not marker.exists():
        raise ValueError("Nonempty unrecognized review directory; preserving its contents")
    if marker.exists():
        previous=json.loads(marker.read_text(encoding="utf-8"))
        if previous.get("study") != str(study.path) or previous.get("version") != study.manifest["version"]:
            raise ValueError("Review directory belongs to a different study")
    path.mkdir(parents=True,exist_ok=True)
    analyze(study)
    rows = json.loads((study.path/"results/seed_metrics.json").read_text(encoding="utf-8"))
    summary = json.loads((study.path/"results/summary.json").read_text(encoding="utf-8"))
    candidates = candidate_cases(rows)
    evidence_file=study.path/"evidence/case_verifications.json"
    reviewed=json.loads(evidence_file.read_text(encoding="utf-8")) if evidence_file.exists() else []
    for item in reviewed:
        item["bibliographic_edge_in_study"]=bool(study.db.execute("SELECT 1 FROM citations WHERE citing=? AND cited=?",(item["citing"],item["seed"])).fetchone())
        item["metric_row"]=next((r for r in rows if r["canonical_id"]==item["seed"]),None)
        citing=study.db.execute("SELECT id,title,doi,year,field FROM works WHERE id=?",(item["citing"],)).fetchone()
        item["citing_work"]=dict(citing) if citing else None
    write_json(study.path/"results/case_candidates.json",candidates)
    # Bounded path excerpts: all pilot seeds and deterministic case candidates.
    selected = {r["canonical_id"] for r in rows if r["pilot"] and r["canonical_id"]}
    selected.update(r["seed"] for r in candidates["candidates"])
    selected.update(r["seed"] for r in reviewed)
    g2row = study.db.execute("SELECT data FROM checks WHERE name='g2_selection'").fetchone()
    g2 = json.loads(g2row[0]) if g2row else dict(eligible_to_acquire=False,seeds=[],unfilled=["IISc","TIFR"],reason="Not yet selected")
    selected.update(s["seed"] for s in g2.get("seeds",[]))
    paths = {}
    for seed in sorted(selected):
        total = study.db.execute("SELECT count(*) FROM citations WHERE cited=?",(seed,)).fetchone()[0]
        items=[]
        for r in study.db.execute("SELECT w.id,w.title,w.doi,w.year,w.type,w.field,w.field_id,e.chronology FROM citations e JOIN works w ON w.id=e.citing WHERE e.cited=? ORDER BY w.year,w.id LIMIT 40",(seed,)):
            evidence=study.db.execute("SELECT frontier_id,page,retrieved_utc FROM edge_evidence WHERE citing=? AND cited=? ORDER BY retrieved_utc LIMIT 1",(r["id"],seed)).fetchone()
            items.append(dict(r,generation=1,cited=seed,evidence=dict(evidence)))
        second=[]
        sample=next((s for s in g2.get("seeds",[]) if s["seed"]==seed),None)
        if sample:
            g1={r[0] for r in study.db.execute("SELECT citing FROM citations WHERE cited=?",(seed,))}
            seen=set()
            for parent in sample["sampled_intermediates"]:
                for r in study.db.execute("SELECT w.id,w.title,w.doi,w.year,w.type,w.field,e.chronology FROM citations e JOIN works w ON w.id=e.citing WHERE e.cited=? ORDER BY w.year,w.id LIMIT 5",(parent,)):
                    if r["id"]==seed or r["id"] in g1:
                        continue
                    evidence=study.db.execute("SELECT frontier_id,page,retrieved_utc FROM edge_evidence WHERE citing=? AND cited=? ORDER BY retrieved_utc LIMIT 1",(r["id"],parent)).fetchone()
                    parent_evidence=study.db.execute("SELECT frontier_id,page,retrieved_utc FROM edge_evidence WHERE citing=? AND cited=? ORDER BY retrieved_utc LIMIT 1",(parent,seed)).fetchone()
                    parent_work=study.db.execute("SELECT id,title,doi,year FROM works WHERE id=?",(parent,)).fetchone()
                    second.append(dict(r,generation=2,cited=parent,seed=seed,shared_descendant=r["id"] in seen,
                                       evidence=dict(evidence),parent_evidence=dict(parent_evidence),parent=dict(parent_work)))
                    seen.add(r["id"])
        paths[seed]=dict(g1=items,g1_total=total,g1_omitted=max(0,total-len(items)),g2=second,g2_sample=sample,
                         g2_excerpt=True,interpretation="Paper-to-paper bibliographic linkage; no passage-level interpretation verified")
    direct = study.db.execute("SELECT count(*),count(DISTINCT citing) FROM citations WHERE cited IN (SELECT canonical_id FROM seeds WHERE canonical_id IS NOT NULL)").fetchone()
    fields={r["field_id"]:r["field"] for r in study.db.execute("SELECT DISTINCT field_id,field FROM works WHERE field_id IS NOT NULL")}
    payload=dict(seeds=rows,summary=summary,field_names=fields,paths=paths,cases=candidates,g2=g2,
                 reviewed_cases=reviewed,g2_results=json.loads((study.path/"results/g2_summary.json").read_text(encoding="utf-8")),
                 generated_utc=utcnow(),cutoff=study.manifest["cutoff"],direct_edges=direct[0],distinct_direct_citers=direct[1],
                 provenance=dict(provider="OpenAlex Core",selected_fields=study.manifest["selected_fields"],
                                 original_input_hashes=study.manifest["protected_sha256"],
                                 first_retrieval=study.db.execute("SELECT min(at_utc) FROM requests WHERE status=200").fetchone()[0],
                                 last_retrieval=study.db.execute("SELECT max(at_utc) FROM requests WHERE status=200").fetchone()[0],
                                 snapshots=study.db.execute("SELECT count(DISTINCT snapshot) FROM pages").fetchone()[0]))
    template=Path(__file__).with_name("idea_flow_template.html").read_text(encoding="utf-8")
    text=json.dumps(payload,ensure_ascii=False,allow_nan=False,separators=(",",":")).replace("<","\\u003c").replace("\u2028","\\u2028").replace("\u2029","\\u2029")
    html=template.replace("/*__IDEA_DATA__*/null",text)
    if "/*__IDEA_DATA__*/null" in html:
        raise ValueError("Preview data marker was not replaced")
    old=path/"index.html"
    if old.exists():
        history=path/"history";history.mkdir(exist_ok=True)
        archived=history/(sha256(old)+".html")
        if not archived.exists():
            shutil.copyfile(old,archived)
    tmp=path/"index.html.tmp";tmp.write_text(html,encoding="utf-8");tmp.replace(old)
    outputs={p.name:sha256(p) for p in path.glob("*.html")}
    write_json(marker,dict(version=study.manifest["version"],study=str(study.path),generated_utc=payload["generated_utc"],sha256=outputs))
    readme=("# Follow the Idea local explorer\n\n"
            "Self-contained index.html; open directly, or serve this directory:\n\n"
            '```powershell\n& "'+sys.executable+'" -B -m http.server 8018 --bind 127.0.0.1 --directory "'+str(path)+'"\n```\n\n'
            "Open http://127.0.0.1:8018/index.html . No external scripts or browser network access required.\n\n"
            "Coverage states and source cutoff are embedded. Path lists are labelled excerpts; full normalized tables remain in "
            +str(study.path/"results")+". CSV exports contain all filtered seed rows (not only the current table page).\n")
    (path/"README.md").write_text(readme,encoding="utf-8")
    return dict(preview=str(path/"index.html"),sha256=outputs["index.html"],seed_rows=len(rows),embedded_path_seeds=len(paths),full_quality_gate=summary["full_quality_gate"]["passed"])
