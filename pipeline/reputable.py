"""Papers in very reputable journals and their impact on India (instructor's request, 15 Oct 2026).

Reputable journals = the Nature Index journal list (178 journals/proceedings chosen by panels of active
scientists, independently of Springer Nature; https://www.nature.com/nature-index/faq), with the index's
article rules for Physical Review A/B/D, MNRAS and A&A (see build.nature_index_paper). "Flagship" =
Nature, Science, Cell, PNAS.

Impact on India - every indicator is computed from OpenAlex fields (https://help.openalex.org/api-entities/works/work-object):
  1. Indian uptake      citing works with >= 1 author at an Indian institution (institution country_code = IN)
                        other than the paper's own institute(s); from those works' referenced_works.
  2. Indian share       Indian citing works / all citing works (cited_by_count).
  3. Breadth            distinct Indian institutions and institution clusters (course PPT clusters) citing.
  4. Reach              cited by at least one institution outside the elite clusters (state/private universities
                        and colleges = cluster "Other University/College").
  5. Speed              years from publication to the first Indian citation.
  6. Indian Citation Index (ICI)  a paper's Indian citations / mean Indian citations of our journal papers in the same
                        field and year (1.0 = typical for IISc/TIFR); same construction as OpenAlex's FWCI.
  7. Collaboration      co-authored with another Indian institution.
  8. National relevance title/abstract names India or an Indian place/mission (fetch.INDIA_TERMS); OpenAlex SDG tag
                        with score >= config.SDG_MIN_SCORE (https://help.openalex.org/data/sdgs).
  Global benchmarks: OpenAlex fwci (1.0 = world average for type, year, subfield) and top-10% flag.
"""
from collections import Counter, defaultdict

import numpy as np
import pandas as pd

import config
from pipeline.build import OWN_IDS, classify_inst

ELITE_OTHER = "Other University/College"


def indian_uptake(t):
    """Per paper: Indian citing works, institutions, clusters, first-citation lag (own institutes excluded)."""
    papers, homes, inst_meta = t["papers"], t["homes"], t["inst_meta"]
    cluster_cache = {}

    def cluster(iid, name, typ):
        if iid not in cluster_cache:
            cluster_cache[iid] = classify_inst(name, typ)
        return cluster_cache[iid]

    citing = defaultdict(dict)   # work -> {citing id: (year, inst ids)}
    for (kind, _), recs in t["flows"].items():
        if kind != "inflow" or not recs:
            continue
        for r in recs:
            ids = {i["id"] for i in r["insts"]}
            for c in r.get("cites", []):
                if c not in homes or r["id"] in citing[c]:
                    continue
                own = set().union(*(OWN_IDS[h] for h in homes[c]))
                if ids & own:
                    continue      # citing work involves the paper's own institute: self-citation, not uptake
                citing[c][r["id"]] = (r.get("year"), r["insts"])
    rows = []
    for wid, cw in citing.items():
        insts = {i["id"]: i for _, ins in cw.values() for i in ins}
        clusters = {cluster(i["id"], i.get("name"), i.get("type")) for i in insts.values()}
        years = [y for y, _ in cw.values() if y]
        rows.append(dict(work_id=wid, indian_citations=len(cw), indian_institutions=len(insts),
                         indian_clusters=len(clusters), reaches_wider=ELITE_OTHER in clusters,
                         first_indian_year=min(years) if years else None,
                         citing_insts=list(insts)))
    up = pd.DataFrame(rows).set_index("work_id") if rows else pd.DataFrame(
        columns=["indian_citations", "indian_institutions", "indian_clusters", "reaches_wider", "first_indian_year",
                 "citing_insts"])
    out = papers[["work_id", "year", "citations", "field"]].join(up, how="left")
    for c in ["indian_citations", "indian_institutions", "indian_clusters"]:
        out[c] = out[c].fillna(0).astype(int)
    out["reaches_wider"] = out["reaches_wider"].fillna(False).astype(bool)
    out["lag"] = out["first_indian_year"] - out["year"]
    # Indian Citation Index: relative to our journal papers of the same field and year
    jp = papers["venue_type"] == "journal"
    base = out[jp].groupby(["field", "year"])["indian_citations"].mean()
    out["ici"] = [ic / base.get((f, y), np.nan) if base.get((f, y), 0) else np.nan
                  for ic, f, y in zip(out["indian_citations"], out["field"], out["year"])]
    return out, cluster_cache


def _group_metrics(p, up):
    """One comparison row for a set of papers."""
    u = up.loc[p.index]
    cited = u[u["indian_citations"] > 0]
    return dict(
        papers=int(len(p)),
        median_citations=float(p["citations"].median()) if len(p) else None,
        mean_fwci=float(p["fwci"].mean()) if p["fwci"].notna().any() else None,
        top10_share=float(p["top10_pct"].mean()) if p["top10_pct"].notna().any() else None,
        indian_citations_mean=float(u["indian_citations"].mean()) if len(u) else None,
        indian_share=float(u["indian_citations"].sum() / p["citations"].sum()) if p["citations"].sum() else None,
        indian_institutions_mean=float(u["indian_institutions"].mean()) if len(u) else None,
        cited_in_india_share=float((u["indian_citations"] > 0).mean()) if len(u) else None,
        reaches_wider_share=float(u["reaches_wider"].mean()) if len(u) else None,
        median_lag=float(cited["lag"].median()) if len(cited) else None,
        ici_mean=float(u["ici"].mean()) if u["ici"].notna().any() else None,
        indian_coauthor_share=float((p["n_indian_partners"] > 0).mean()) if len(p) else None,
        india_focus_share=float(p["india_focus"].mean()) if p["india_focus"].notna().any() else None,
        sdg_share=float(p["top_sdg"].notna().mean()) if "top_sdg" in p else None,
    )


def reputable_stats(t, out_dir=None):
    papers = t["papers"].copy()
    own_all = set().union(*OWN_IDS.values())
    papers["n_indian_partners"] = papers["indian_inst_ids"].map(
        lambda x: len({i for i in x.split(";") if i} - own_all))
    up, clusters = indian_uptake(t)
    inst_meta = t["inst_meta"]
    jp = papers[papers["venue_type"] == "journal"]
    fac = t["own_auth"].dropna(subset=["person"]).drop_duplicates(["work_id", "person"])
    fac_names = fac.groupby("work_id")["person"].agg(lambda s: "; ".join(t["persons"][k]["name"] for k in s))
    years = list(range(config.YEAR_FROM, config.YEAR_TO + 1))
    out = {}
    for inst in list(config.INSTITUTIONS) + ["All"]:
        sub = jp if inst == "All" else jp[jp["homes"].str.contains(inst)]
        ni, other, flag = sub[sub["nature_index"]], sub[~sub["nature_index"]], sub[sub["flagship"]]
        comp = [dict(group="Nature Index journals", **_group_metrics(ni, up)),
                dict(group="…of which India-focused", **_group_metrics(ni[ni["india_focus"] == True], up)),
                dict(group="Flagship (Nature, Science, Cell, PNAS)", **_group_metrics(flag, up)),
                dict(group="Other journal papers", **_group_metrics(other, up))]
        u_ni = up.loc[ni.index]
        # who cites our reputable papers in India
        cnt = Counter(i for lst in u_ni["citing_insts"].dropna() for i in lst)
        top_citers = [dict(name=inst_meta.get(i, (i,))[0], cluster=clusters.get(i), papers=int(c))
                      for i, c in cnt.most_common(15)]
        def cl_share(u):
            c = Counter(clusters.get(i) for lst in u["citing_insts"].dropna() for i in lst)
            tot = sum(c.values()) or 1
            return {k: v / tot for k, v in c.items()}
        sdg_ni = ni["sdgs"].dropna().str.split("; ").explode()
        sdg_ni = sdg_ni[sdg_ni != ""].value_counts()
        sdg_ot = other["sdgs"].dropna().str.split("; ").explode()
        sdg_ot = sdg_ot[sdg_ot != ""].value_counts()
        by_year = sub.groupby("year")["nature_index"].agg(["sum", "mean"]).reindex(years)
        top_india = ni.join(up[["indian_citations", "indian_institutions", "indian_clusters"]]) \
            .sort_values("indian_citations", ascending=False).head(10)
        out[inst] = dict(
            kpis=dict(ni_papers=int(len(ni)), ni_share=float(len(ni) / len(sub)) if len(sub) else None,
                      flagship_papers=int(len(flag)), ni_journals=int(ni["venue"].nunique()),
                      ni_cited_in_india=float((u_ni["indian_citations"] > 0).mean()) if len(ni) else None,
                      ni_india_focus=float(ni["india_focus"].mean()) if len(ni) and ni["india_focus"].notna().any() else None),
            comparison=comp,
            by_year=dict(years=years, papers=by_year["sum"].fillna(0).astype(int).tolist(),
                         share=by_year["mean"].tolist()),
            top_journals=[dict(venue=v, papers=int(c)) for v, c in ni["venue"].value_counts().head(12).items()],
            top_citers=top_citers,
            clusters=dict(ni=cl_share(u_ni), other=cl_share(up.loc[other.index])),
            sdgs=[dict(sdg=k, ni_share=float(v / len(ni)), other_share=float(sdg_ot.get(k, 0) / len(other)))
                  for k, v in sdg_ni.head(10).items()] if len(ni) else [],
            top_india=[dict(title=r.title, venue=r.venue, year=int(r.year), homes=r.homes, india_focus=bool(r.india_focus),
                            citations=int(r.citations), indian_citations=int(r.indian_citations),
                            indian_institutions=int(r.indian_institutions), doi=r.doi)
                       for r in top_india.itertuples()],
        )
    allni = jp[jp["nature_index"]].join(up[["indian_citations", "indian_institutions", "indian_clusters",
                                            "reaches_wider", "ici"]])
    out["papers"] = [dict(title=(r.title or "")[:200], venue=r.venue, year=int(r.year), homes=r.homes,
                          faculty=fac_names.get(r.work_id, ""), citations=int(r.citations),
                          fwci=None if pd.isna(r.fwci) else round(float(r.fwci), 2),
                          indian_citations=int(r.indian_citations), indian_institutions=int(r.indian_institutions),
                          indian_clusters=int(r.indian_clusters), reaches_wider=bool(r.reaches_wider),
                          india_focus=bool(r.india_focus) if r.india_focus is not None else None,
                          india_terms=r.india_terms or "", sdg=r.top_sdg or "", flagship=bool(r.flagship),
                          many_authors=bool(r.many_authors), doi=r.doi)
                     for r in allni.sort_values("citations", ascending=False).itertuples()]
    out["sdg_min_score"] = config.SDG_MIN_SCORE
    # per-paper table behind every number (journal papers)
    if out_dir is not None:
        cols = ["doi", "title", "year", "homes", "venue", "nature_index", "flagship", "citations", "fwci", "top10_pct",
                "collaboration", "india_focus", "india_terms", "sdgs"]
        tbl = jp[cols].join(up[["indian_citations", "indian_institutions", "indian_clusters", "reaches_wider",
                                "first_indian_year", "ici"]])
        (out_dir / "stats").mkdir(parents=True, exist_ok=True)
        tbl.rename(columns={"ici": "indian_citation_index"}).to_csv(out_dir / "stats" / "india_impact_per_paper.csv",
                                                                     encoding="utf-8")
    return out
