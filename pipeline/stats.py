"""Step 4 - statistics at institution / department / faculty level (+ network & connectivity summaries)."""
import datetime as dt
import json

import numpy as np
import pandas as pd

import config
from pipeline.build import h_index


def _clean(o):
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        return None if (o != o or o in (np.inf, -np.inf)) else round(float(o), 6)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if o is pd.NaT or (isinstance(o, float) and o != o):
        return None
    return o


def records(df, cols=None):
    df = df if cols is None else df[cols]
    return _clean(df.replace({np.nan: None}).to_dict("records"))


def inst_block(p, fac, inst):
    own = {i for k, v in config.INSTITUTIONS.items() if inst in (k, "All") for i in v["openalex_ids"]}
    years = list(range(config.YEAR_FROM, config.YEAR_TO + 1))
    jr = p[p["venue_type"] == "journal"]
    jq = jr["sjr_quartile"]
    trend = p.groupby(["year", "venue_type"]).size().unstack(fill_value=0).reindex(years, fill_value=0)
    conf = p[p["venue_type"] == "conference"]
    topj = (jr.groupby("venue").agg(papers=("work_id", "size"), citations=("citations", "sum"),
                                    quartile=("sjr_quartile", lambda s: s.mode().iat[0] if s.notna().any() else None))
            .sort_values("papers", ascending=False).head(15).reset_index())
    most = p.sort_values("citations", ascending=False).head(10)
    f = fac[(fac["inst"] == inst) & (fac["papers"] > 0)] if inst != "All" else fac[fac["papers"] > 0]
    dept = (f.groupby("department").agg(faculty=("name", "size"), papers=("papers", "sum"),
                                        citations=("citations", "sum"), median_h=("h_index", "median"),
                                        mean_q1_share=("q1_share", "mean"))
            .sort_values("papers", ascending=False).reset_index())
    # department paper counts on unique papers (a paper counts once per department)
    return dict(
        kpis=dict(papers=len(p), citations=int(p["citations"].sum()),
                  mean_citations=float(p["citations"].mean()) if len(p) else 0,
                  h_index=h_index(p["citations"]), journal_papers=len(jr), conference_papers=len(conf),
                  q1_share_journals=float((jq == "Q1").sum() / jq.notna().sum()) if jq.notna().any() else None,
                  q1_share_all=float((jq == "Q1").sum() / len(p)) if len(p) else None,
                  quartile_coverage=float(jq.notna().mean()) if len(jr) else None,
                  faculty=int(len(f)), mega_papers=int(p["is_mega"].sum()),
                  many_author_papers=int(p["many_authors"].sum()),
                  many_author_share=float(p["many_authors"].mean()) if len(p) else 0,
                  with_indian_coauthor=float(p["indian_inst_ids"].map(
                      lambda x: bool(set(filter(None, x.split(";"))) - own)).mean()) if len(p) else 0,
                  median_fwci=float(p["fwci"].median()) if p["fwci"].notna().any() else None),
        trend=dict(years=years, **{k: trend[k].tolist() for k in trend.columns},
                   total=trend.sum(axis=1).tolist(),
                   citations=p.groupby("year")["citations"].sum().reindex(years, fill_value=0).tolist()),
        core=conf["core_rank"].fillna("Unranked").value_counts().to_dict(),
        top_journals=records(topj),
        most_cited=records(most, ["title", "venue", "year", "citations", "doi", "homes", "n_authors", "many_authors"]),
        many_authors_by_year=dict(years=years,
                                  many=p[p["many_authors"]].groupby("year").size().reindex(years, fill_value=0).tolist(),
                                  few=p[~p["many_authors"]].groupby("year").size().reindex(years, fill_value=0).tolist(),
                                  citations_many=p[p["many_authors"]].groupby("year")["citations"].mean()
                                  .reindex(years).tolist(),
                                  citations_few=p[~p["many_authors"]].groupby("year")["citations"].mean()
                                  .reindex(years).tolist()),
        fields=p["field"].fillna("Unknown").value_counts().to_dict(),
        subfields=p["subfield"].fillna("Unknown").value_counts().head(20).to_dict(),
        departments=records(dept),
        h_values=f["h_index"].astype(int).tolist(),
    )


def compute_stats(t, nets, out_dir=None, json_path=None):
    out_dir = out_dir or config.OUTPUTS
    json_path = json_path or (config.PROCESSED / "stats.json")
    papers, fac = t["papers"], t["faculty"]
    st = dict(meta=dict(group=config.GROUP, institutions={k: v["name"] for k, v in config.INSTITUTIONS.items()},
                        years=[config.YEAR_FROM, config.YEAR_TO], sample=config.SAMPLE,
                        generated=dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
                        mega_threshold=config.MEGA_AUTHOR_THRESHOLD,
                        flows_available=nets["flows_available"],
                        n_papers=len(papers), n_rows=len(t["dataset"]),
                        roster_size={i: int((t["roster"]["institution"] == i).sum()) for i in config.INSTITUTIONS},
                        faculty_sources=fac["faculty_source"].value_counts().to_dict()))
    st["inst"] = {}
    for inst in list(config.INSTITUTIONS) + ["All"]:
        p = papers if inst == "All" else papers[papers["homes"].str.contains(inst)]
        st["inst"][inst] = inst_block(p, fac, inst)
        st["inst"][inst]["kpis"]["shared_with_other"] = int(papers["homes"].str.contains(";").sum())

    # Instructor's flag: every paper with more than 12 authors, with our faculty authors on it
    ds = t["dataset"]
    fac_names = (ds[ds["is_faculty"]].groupby("openalex_work_id")["author"]
                 .agg(lambda s: "; ".join(dict.fromkeys(s))))
    fl = papers[papers["many_authors"]].sort_values(["citations", "year"], ascending=False).copy()
    fl["faculty_authors"] = fl["work_id"].map(fac_names).fillna("")
    fl["title"] = fl["title"].fillna("").str.slice(0, 220)
    st["flagged"] = records(fl, ["title", "year", "homes", "venue", "venue_type", "n_authors",
                                 "is_mega", "citations", "field", "faculty_authors", "doi"])

    st["faculty"] = records(fac.sort_values("papers", ascending=False),
                            ["name", "inst", "department", "rank", "papers", "citations", "h_index", "h_index_career",
                             "q1_share", "high_impact_papers", "journals_used", "top3_journal_share", "top3_journals"]
                            if "h_index_nonmega" in fac else None)

    # --------------------------------------------------------------- citation network
    top10 = papers.sort_values("pagerank", ascending=False).head(10)
    indeg = papers["in_degree"].fillna(0).astype(int)
    st["citation"] = dict(
        summary=nets["citation_summary"],
        top_pagerank=records(top10, ["title", "venue", "year", "homes", "citations", "in_degree", "pagerank", "doi"]),
        top_pagerank_nonmega=records(papers[~papers["is_mega"]].sort_values("pagerank", ascending=False).head(10),
                                     ["title", "venue", "year", "homes", "citations", "in_degree", "pagerank", "doi"]),
        indegree_dist={int(k): int(v) for k, v in indeg.value_counts().sort_index().items()},
        vis=nets["citation_vis"],
    )
    # --------------------------------------------------------------- flows
    flow = nets["flow"]
    years = list(range(config.YEAR_FROM, config.YEAR_TO + 1))
    st["flows"] = {}
    for inst in config.INSTITUTIONS:
        f = flow[flow["inst"] == inst]
        out_full = t["flows"][("outflow", inst)] is not None
        in_full = t["flows"][("inflow", inst)] is not None
        agg = nets["inflow_agg"].get(inst)
        # count citation links (paper->paper), not institution attributions
        links = f.drop_duplicates(["direction", "our_paper", "other"])
        n_in = int((links["direction"] == "in").sum())
        n_out = int((links["direction"] == "out").sum())
        by_year = links.groupby(["year", "direction"]).size().unstack(fill_value=0).reindex(years, fill_value=0)
        in_year = by_year.get("in", pd.Series(0, index=years)).tolist()
        top_in = (f[f.direction == "in"].groupby(["partner_name", "partner_cluster"]).size()
                  .sort_values(ascending=False).head(10).reset_index(name="citations"))
        clusters = f.groupby(["partner_cluster", "direction"]).size().unstack(fill_value=0)
        cl = {c: dict(inflow=int(r.get("in", 0)), outflow=int(r.get("out", 0))) for c, r in clusters.iterrows()}
        mode, unit = ("edges", "citation links")
        impact = (n_in / n_out) if (n_out and in_full and out_full) else None
        if not in_full and agg:
            mode, unit = "aggregate", "distinct citing works per 100-paper batch"
            n_in = agg["total"]
            in_year = [agg["by_year"].get(y, 0) for y in years]
            p = agg["partners"]
            top_in = (p.sort_values("citing_works", ascending=False).head(10)
                      .rename(columns={"citing_works": "citations"})[["partner_name", "partner_cluster", "citations"]])
            for c, v in p.groupby("partner_cluster")["citing_works"].sum().items():
                cl.setdefault(c, dict(inflow=0, outflow=0))["inflow"] = int(v)
            ob = nets["outflow_batch_works"].get(inst)
            impact = (n_in / ob) if ob else None
        elif not in_full:
            mode = "internal only"
        st["flows"][inst] = dict(
            inflow=n_in, outflow=n_out, impact_ratio=impact, inflow_mode=mode, inflow_unit=unit,
            outflow_available=out_full, outflow_batch_works=nets["outflow_batch_works"].get(inst),
            by_year=dict(years=years, inflow=in_year, outflow=by_year.get("out", pd.Series(0, index=years)).tolist()),
            top_citing=records(top_in), clusters=cl,
        )
    # --------------------------------------------------------------- authorship network
    fm = nets["faculty_metrics"]
    st["authorship"] = dict(
        summary=nets["authorship_summary"],
        top_degree=records(fm.sort_values("degree_centrality", ascending=False).head(10)) if len(fm) else [],
        top_betweenness=records(fm.sort_values("betweenness", ascending=False).head(10)) if len(fm) else [],
        hubs=records(fm.sort_values("n_partner_institutions", ascending=False).head(10)) if len(fm) else [],
        communities=records(nets["communities"].head(15)) if len(nets["communities"]) else [],
        vis=nets["authorship_vis"],
    )
    # --------------------------------------------------------------- connectivity map
    ic = nets["connections"]
    st["connectivity"] = {}
    for inst in config.INSTITUTIONS:
        c = ic[ic["your_inst"] == inst]
        co = c[c["shared_papers"] > 0]
        st["connectivity"][inst] = dict(
            n_partners=int(len(co)),
            top_partners=records(co.head(20), ["partner_inst", "partner_cluster", "shared_papers", "total_citations",
                                               "citations_received_from_partner", "citations_given_to_partner",
                                               "cross_cluster", "topic_jaccard", "topic_weighted_jaccard"]),
            clusters=co.groupby("partner_cluster")["shared_papers"].sum().sort_values(ascending=False).to_dict(),
        )
    from pipeline.journals import journal_stats
    st["journals"] = journal_stats(t)
    st = _clean(st)
    json_path.write_text(json.dumps(st, indent=1), encoding="utf-8")
    write_stat_tables(st, out_dir)
    return st


def write_stat_tables(st, out_dir=None):
    """Flat CSVs of the headline statistics (handy for the report)."""
    out = (out_dir or config.OUTPUTS) / "stats"
    out.mkdir(exist_ok=True)
    rows = []
    for inst, b in st["inst"].items():
        rows.append(dict(institution=inst, **{k: v for k, v in b["kpis"].items()}))
        pd.DataFrame(b["top_journals"]).head(5).to_csv(out / f"top5_journals_{inst}.csv", index=False)
        pd.DataFrame(b["most_cited"]).to_csv(out / f"top10_cited_{inst}.csv", index=False)
        pd.DataFrame(b["departments"]).to_csv(out / f"departments_{inst}.csv", index=False)
        pd.DataFrame({"year": b["trend"]["years"], "papers": b["trend"]["total"]}).to_csv(out / f"trend_{inst}.csv", index=False)
    pd.DataFrame(rows).to_csv(out / "institution_kpis.csv", index=False)
    pd.DataFrame(st["citation"]["top_pagerank"]).to_csv(out / "citation_top10_pagerank.csv", index=False)
    pd.DataFrame(st["citation"]["top_pagerank_nonmega"]).to_csv(out / "citation_top10_pagerank_nonmega.csv", index=False)
    pd.DataFrame(st["authorship"]["top_degree"]).to_csv(out / "authorship_top10_degree.csv", index=False)
    pd.DataFrame(st["authorship"]["top_betweenness"]).to_csv(out / "authorship_top10_betweenness.csv", index=False)
    pd.DataFrame(st["authorship"]["communities"]).to_csv(out / "authorship_communities.csv", index=False)
    j = st["journals"]
    pd.DataFrame(j["regression"]).to_csv(out / "journal_choice_regression.csv", index=False)
    pd.DataFrame([dict(institution=i, factor=f, **r) for i in [*config.INSTITUTIONS, "All"]
                  for f, rows in j[i]["drivers"].items() for r in rows]).to_csv(out / "journal_choice_drivers.csv", index=False)
    pd.DataFrame([dict(institution=i, **r) for i in [*config.INSTITUTIONS, "All"] for r in j[i]["top_journals"]]
                 ).to_csv(out / "journal_choice_top_journals.csv", index=False)
    pd.DataFrame(j["network"]["communities"]).to_csv(out / "journal_ecosystems.csv", index=False)
