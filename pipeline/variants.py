"""Analysis variant requested by the instructor: everything recomputed WITHOUT the flagged papers
(more than config.AUTHOR_FLAG_THRESHOLD authors). Deliverable CSVs are not touched; this variant's
network files and statistics go to outputs/without_flagged/."""
import config
from pipeline.build import faculty_table

OUT = config.OUTPUTS / "without_flagged"


def without_flagged(t):
    papers = t["papers"]
    keep = set(papers.index[~papers["many_authors"]])
    v = dict(t)
    v["papers"] = papers.loc[sorted(keep)]
    v["works"] = {w: x for w, x in t["works"].items() if w in keep}
    v["homes"] = {w: h for w, h in t["homes"].items() if w in keep}
    v["auth"] = t["auth"][t["auth"]["work_id"].isin(keep)]
    v["own_auth"] = t["own_auth"][t["own_auth"]["work_id"].isin(keep)]
    v["dataset"] = t["dataset"][t["dataset"]["openalex_work_id"].isin(keep)]
    # citing works from other Indian institutes: keep only their citations of the remaining papers
    flows = {}
    for key, recs in t["flows"].items():
        if key[0] == "inflow" and recs is not None:
            recs = [dict(r, cites=[c for c in r.get("cites", []) if c in keep]) for r in recs]
            recs = [r for r in recs if r["cites"]]
        flows[key] = recs
    v["flows"] = flows
    v["faculty"] = faculty_table(v["own_auth"], t["persons"], v["papers"], t["profiles"], t["roster"])
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"[variant] without flagged papers: {len(v['papers'])} of {len(papers)} papers")
    return v


def _median(xs):
    xs = sorted(xs)
    return xs[len(xs) // 2] if xs else None


def compare(st_all, st_nf):
    """Key metrics side by side (with / without flagged papers) per institution -> list of rows."""
    import pandas as pd
    rows = []

    def add(inst, group, metric, a, b, fmt="int"):
        change = None
        if isinstance(a, (int, float)) and isinstance(b, (int, float)) and a:
            change = (b - a) / abs(a)
        rows.append(dict(institution=inst, group=group, metric=metric, with_flagged=a, without_flagged=b,
                         change=change, fmt=fmt))

    for inst in list(config.INSTITUTIONS) + ["All"]:
        A, N = st_all["inst"][inst], st_nf["inst"][inst]
        ka, kn = A["kpis"], N["kpis"]
        add(inst, "Output", "Papers", ka["papers"], kn["papers"])
        add(inst, "Output", "Citations", ka["citations"], kn["citations"])
        add(inst, "Output", "Mean citations per paper", ka["mean_citations"], kn["mean_citations"], "1dp")
        add(inst, "Output", "Institutional h-index", ka["h_index"], kn["h_index"])
        add(inst, "Quality", "Q1 share of journal papers", ka["q1_share_journals"], kn["q1_share_journals"], "pct")
        add(inst, "Quality", "Top journal", (A["top_journals"] or [{}])[0].get("venue"),
            (N["top_journals"] or [{}])[0].get("venue"), "text")
        add(inst, "Quality", "Most-cited paper", (A["most_cited"] or [{}])[0].get("title"),
            (N["most_cited"] or [{}])[0].get("title"), "text")
        add(inst, "Faculty", "Faculty with papers", ka["faculty"], kn["faculty"])
        add(inst, "Faculty", "Median faculty h-index", _median(A["h_values"]), _median(N["h_values"]))
        add(inst, "Collaboration", "Papers with another Indian institute", ka["with_indian_coauthor"],
            kn["with_indian_coauthor"], "pct")
        if inst in st_all["flows"]:
            fa, fn = st_all["flows"][inst], st_nf["flows"][inst]
            add(inst, "Indian citation flow", "Citations from other Indian institutes", fa["inflow"], fn["inflow"])
            add(inst, "Indian citation flow", "Citations to other Indian institutes", fa["outflow"], fn["outflow"])
            add(inst, "Indian citation flow", "In / out ratio", fa["impact_ratio"], fn["impact_ratio"], "2dp")
            ca, cn = st_all["connectivity"][inst], st_nf["connectivity"][inst]
            add(inst, "Indian connectivity", "Partner institutions", ca["n_partners"], cn["n_partners"])
            add(inst, "Indian connectivity", "Top partner",
                (ca["top_partners"] or [{}])[0].get("partner_inst"), (cn["top_partners"] or [{}])[0].get("partner_inst"), "text")
    ca, cn = st_all["citation"]["summary"], st_nf["citation"]["summary"]
    add("All", "Citation network", "Citations among our papers", ca["edges"], cn["edges"])
    add("All", "Citation network", "Share in largest component", ca["largest_wcc_share"], cn["largest_wcc_share"], "pct")
    add("All", "Citation network", "Top paper by PageRank", (st_all["citation"]["top_pagerank"] or [{}])[0].get("title"),
        (st_nf["citation"]["top_pagerank"] or [{}])[0].get("title"), "text")
    aa, an = st_all["authorship"]["summary"], st_nf["authorship"]["summary"]
    add("All", "Co-authorship network", "Faculty–faculty links", aa["faculty_edges"], an["faculty_edges"])
    add("All", "Co-authorship network", "Louvain communities", aa["n_communities"], an["n_communities"])
    add("All", "Co-authorship network", "Modularity", aa["modularity"], an["modularity"], "2dp")
    add("All", "Co-authorship network", "Isolated faculty", aa["isolated_faculty"], an["isolated_faculty"])
    df = pd.DataFrame(rows)
    (config.OUTPUTS / "stats").mkdir(exist_ok=True)
    df.drop(columns="fmt").to_csv(config.OUTPUTS / "stats" / "with_vs_without_flagged.csv", index=False,
                                  encoding="utf-8")
    return rows
