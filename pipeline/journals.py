"""Journal choice: who publishes where, why, and how journals cluster (instructor's request, 15 Oct 2026).

  * who  - per faculty: journals used, loyalty (share in their top-3 journals), Q1 and high-impact share
           (in pipeline/build.py faculty_table); here aggregated by rank, department, institution
  * why  - share of papers in Q1 / high-impact journals by team size, collaboration type, field, rank;
           plus a logistic regression that holds the other factors fixed
  * how  - journal co-usage network: journals linked when the same faculty publish in both;
           Louvain communities = publication ecosystems
"High-impact" = OpenAlex 2-year mean citedness >= config.HIGH_IMPACT_THRESHOLD (impact-factor equivalent).
"""
import itertools
from collections import defaultdict

import networkx as nx
import numpy as np
import pandas as pd

import config

TEAM_BANDS = [(1, 3, "1–3 authors"), (4, 6, "4–6"), (7, 12, "7–12"), (13, 50, "13–50"), (51, 10 ** 6, "more than 50")]


def _team_band(n):
    return next(lab for lo, hi, lab in TEAM_BANDS if lo <= n <= hi)


def _rates(df, by, order=None, min_papers=30):
    g = df.groupby(by).agg(papers=("work_id", "nunique"), q1=("is_q1", "mean"), high=("is_high", "mean"),
                           impact=("journal_impact", "median"))
    g = g[g["papers"] >= min_papers]
    if order:
        g = g.reindex([o for o in order if o in g.index])
    else:
        g = g.sort_values("papers", ascending=False)
    return [dict(group=str(k), papers=int(r.papers), q1_share=float(r.q1), high_impact_share=float(r.high),
                 median_impact=float(r.impact)) for k, r in g.iterrows()]


PREFIXES = {"rank_": "Faculty rank", "team_": "Team size", "collaboration_": "Collaboration",
            "field_g_": "Field", "inst_": "Institution"}


def _regression(fp):
    """Logit on faculty-paper rows; odds ratios with paper-clustered 95% CIs. Returns rows or []."""
    try:
        import statsmodels.api as sm
    except ImportError:
        return []
    d = fp.dropna(subset=["journal_impact"]).copy()
    d = d[d["rank"].isin(["Assistant professor / Reader", "Associate professor", "Professor"])]
    if len(d) < 500:
        return []
    top_fields = d["field"].value_counts().head(6).index
    d["field_g"] = d["field"].where(d["field"].isin(top_fields), "Other fields")
    X = pd.get_dummies(d[["rank", "team", "collaboration", "field_g", "inst"]], drop_first=False, dtype=float)
    refs = ["rank_Professor", "team_4–6", "collaboration_Within IISc/TIFR only",
            f"field_g_{d['field_g'].value_counts().index[0]}", "inst_IISc"]
    X = X.drop(columns=[r for r in refs if r in X.columns])
    X["year (per 5 years)"] = (d["year"] - 2021) / 5
    X = sm.add_constant(X)
    groups = d["work_id"].astype("category").cat.codes
    out = []
    for outcome, y in [("Q1 journal", d["is_q1"].astype(float)), ("High-impact journal", d["is_high"].astype(float))]:
        try:
            res = sm.Logit(y, X).fit(disp=0, cov_type="cluster", cov_kwds={"groups": groups})
        except Exception as e:   # perfect separation etc.
            print(f"[journals] regression for {outcome} failed: {e}")
            continue
        ci = res.conf_int()
        for name in X.columns:
            if name == "const":
                continue
            prefix = next((p for p in PREFIXES if name.startswith(p)), "")
            out.append(dict(outcome=outcome, factor=PREFIXES.get(prefix, "Year"), level=name[len(prefix):],
                            odds_ratio=float(np.exp(res.params[name])), ci_low=float(np.exp(ci.loc[name, 0])),
                            ci_high=float(np.exp(ci.loc[name, 1])), p=float(res.pvalues[name])))
    return out


def _network(jp, fp):
    """Journal co-usage network (all our institutes): nodes = journals with enough of our papers,
    edge weight = number of faculty who published in both."""
    counts = jp["venue"].value_counts()
    keep = counts[counts >= config.JOURNAL_NETWORK_MIN_PAPERS].index
    fac_by_j = fp[fp["venue"].isin(keep)].groupby("venue")["person"].agg(set)
    G = nx.Graph()
    meta = jp[jp["venue"].isin(keep)].groupby("venue").agg(
        papers=("work_id", "nunique"), impact=("journal_impact", "max"),
        quartile=("sjr_quartile", lambda s: s.mode().iat[0] if s.notna().any() else None),
        field=("field", lambda s: s.mode().iat[0] if s.notna().any() else None))
    for v, r in meta.iterrows():
        G.add_node(v, papers=int(r.papers), impact=None if pd.isna(r.impact) else float(r.impact),
                   quartile=r.quartile, field=r.field, faculty=len(fac_by_j.get(v, ())))
    for a, b in itertools.combinations(fac_by_j.index, 2):
        w = len(fac_by_j[a] & fac_by_j[b])
        if w >= 3:
            G.add_edge(a, b, weight=w)
    G.remove_nodes_from([n for n in list(G) if G.degree(n) == 0])
    if G.number_of_edges() == 0:
        return dict(nodes=[], edges=[], communities=[])
    comms = sorted(nx.community.louvain_communities(G, weight="weight", seed=42), key=lambda c: (-len(c), min(c)))
    comm_of = {n: i for i, c in enumerate(comms) for n in c}
    labels = []
    for i, c in enumerate(comms):
        fields = pd.Series([G.nodes[n]["field"] for n in sorted(c)]).value_counts()
        top = sorted(c, key=lambda n: (-G.nodes[n]["papers"], n))[:3]
        labels.append(dict(community=i, size=len(c), field=fields.index[0] if len(fields) else "Mixed",
                           papers=int(sum(G.nodes[n]["papers"] for n in c)), journals=", ".join(top)))
    return dict(
        nodes=[dict(id=n, comm=comm_of[n], **G.nodes[n]) for n in G],
        edges=[[a, b, d["weight"]] for a, b, d in G.edges(data=True)],
        communities=labels, modularity=float(nx.community.modularity(G, comms, weight="weight")))


def journal_stats(t):
    papers, own_auth, persons = t["papers"], t["own_auth"], t["persons"]
    years = list(range(config.YEAR_FROM, config.YEAR_TO + 1))
    jp = papers[(papers["venue_type"] == "journal") & papers["venue"].notna()].copy()
    jp["is_q1"] = jp["sjr_quartile"] == "Q1"
    jp["is_high"] = jp["journal_impact"] >= config.HIGH_IMPACT_THRESHOLD
    jp["team"] = jp["n_authors"].map(_team_band)
    jp["indian_journal"] = jp["journal_country"] == "IN"

    # faculty-paper rows (journal papers only)
    fa = own_auth.dropna(subset=["person"]).drop_duplicates(["work_id", "person"])
    fp = fa[["work_id", "person", "inst"]].merge(jp.drop(columns=["homes", "work_id"]), left_on="work_id",
                                                  right_index=True)
    fp["rank"] = fp["person"].map(lambda k: _rank(persons[k]))
    fp["department"] = fp["person"].map(lambda k: persons[k]["department"])
    fac = t["faculty"]

    out = {}
    for inst in list(config.INSTITUTIONS) + ["All"]:
        sub = jp if inst == "All" else jp[jp["homes"].str.contains(inst)]
        fsub = fp if inst == "All" else fp[fp["inst"] == inst]
        fc = fac if inst == "All" else fac[fac["inst"] == inst]
        loyal = fc[(fc.get("journals_used", 0) > 0) & (fc["papers"] >= 5)]["top3_journal_share"].dropna()
        top = (sub.groupby("venue").agg(papers=("work_id", "size"), impact=("journal_impact", "max"),
                                        quartile=("sjr_quartile", lambda s: s.mode().iat[0] if s.notna().any() else None),
                                        publisher=("publisher", "first"), oa=("oa_journal", "first"),
                                        country=("journal_country", "first"))
               .sort_values("papers", ascending=False).head(15))
        nfac = fsub.groupby("venue")["person"].nunique()
        pub = sub["publisher"].dropna().value_counts()   # share is still of all journal papers
        by_year = sub.groupby("year").agg(q1=("is_q1", "mean"), high=("is_high", "mean"), oa=("oa_journal", "mean"))
        by_year = by_year.reindex(years)
        drivers = {
            "Team size": _rates(sub, "team", [b[2] for b in TEAM_BANDS]),
            "Collaboration": _rates(sub, "collaboration", ["Within IISc/TIFR only", "With other Indian institutes", "International"]),
            "Field": _rates(sub, "field")[:10],
            "Faculty rank": _rates(fsub, "rank", ["Assistant professor / Reader", "Associate professor", "Professor",
                                                  "Former faculty", "Honorary / emeritus", "Rank not listed"]),
            "Department": _rates(fsub, "department")[:15],
        }
        if inst == "All":
            drivers["Institution"] = _rates(fp, "inst")
        out[inst] = dict(
            kpis=dict(journal_papers=int(len(sub)), journals_used=int(sub["venue"].nunique()),
                      q1_share=float(sub["is_q1"].sum() / sub["sjr_quartile"].notna().sum()) if sub["sjr_quartile"].notna().any() else None,
                      high_impact_papers=int(sub["is_high"].sum()), high_impact_share=float(sub["is_high"].mean()) if len(sub) else None,
                      oa_share=float(sub["oa_journal"].mean()) if len(sub) else None,
                      indian_journal_share=float(sub["indian_journal"].mean()) if len(sub) else None,
                      median_loyalty=float(loyal.median()) if len(loyal) else None,
                      top20_share=float(sub["venue"].value_counts().head(20).sum() / len(sub)) if len(sub) else None),
            top_journals=[dict(venue=v, papers=int(r.papers), impact=None if pd.isna(r.impact) else float(r.impact),
                               quartile=r.quartile, publisher=r.publisher, oa=bool(r.oa), country=r.country,
                               faculty=int(nfac.get(v, 0))) for v, r in top.iterrows()],
            quartile=sub["sjr_quartile"].fillna("Unranked/NA").value_counts().to_dict(),
            publishers=[dict(name=k, papers=int(v), share=float(v / len(sub))) for k, v in pub.head(10).items()],
            by_year=dict(years=years, q1=by_year["q1"].tolist(), high=by_year["high"].tolist(), oa=by_year["oa"].tolist()),
            drivers=drivers,
            loyalty=[float(x) for x in loyal],
        )
    out["regression"] = _regression(fp.assign(team=fp["n_authors"].map(_team_band)))
    out["network"] = _network(jp, fp)
    out["threshold"] = config.HIGH_IMPACT_THRESHOLD
    return out


def _rank(person):
    from pipeline.build import rank_group
    return rank_group(person["designation"], person["faculty_source"])
