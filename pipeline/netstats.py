"""Network analysis beyond description: is the observed structure more than chance, and how does it change?

Faculty co-authorship network (nodes = faculty, edges = joint papers with <= config.MEGA_AUTHOR_THRESHOLD authors):
  - Null model: degree-preserving random rewiring (Maslov & Sneppen 2002, doi:10.1126/science.1065103), so every
    faculty member keeps their number of co-authors and only *who* they work with is randomised.
  - Small world (Watts & Strogatz 1998, doi:10.1038/30918): clustering C and mean shortest path L of the largest
    component against the null model; sigma = (C / C_null) / (L / L_null) > 1 means small-world
    (Humphries & Gurney 2008, doi:10.1371/journal.pone.0002051).
  - Communities: Louvain modularity Q (Blondel et al. 2008, doi:10.1088/1742-5468/2008/10/P10008) against Q found
    by the same algorithm on the null graphs (z-score).
  - Mixing (Newman 2003, doi:10.1103/PhysRevE.67.026126): degree assortativity, and assortativity by department
    and by institute; share of links inside a department against the share expected at random.
  - Rich club (Colizza et al. 2006, doi:10.1038/nphys209): do the best-connected faculty work with each other more
    than the null model predicts? (normalised coefficient > 1 = yes)
  - Growth: the network of joint papers up to each year (cumulative): faculty linked, giant-component share.
Paper citation network (within our papers):
  - In-degree distribution: discrete power-law fit by maximum likelihood with x_min chosen by the
    Kolmogorov-Smirnov distance (Clauset, Shalizi & Newman 2009, doi:10.1137/070710111).
"""
import math
from collections import Counter

import networkx as nx
import numpy as np

import config

N_NULL = 20          # random rewirings per test
SEED = 42


def _rewired(G, k):
    H = G.copy()
    nx.double_edge_swap(H, nswap=10 * H.number_of_edges(), max_tries=10 ** 7, seed=SEED + k)
    return H


def _giant(G):
    return G.subgraph(max(nx.connected_components(G), key=lambda c: (len(c), min(c)))).copy()


def _cl(G):
    g = _giant(G)
    return nx.average_clustering(G), nx.average_shortest_path_length(g)


def _within_dept(G):
    e = G.number_of_edges()
    obs = sum(1 for a, b in G.edges if G.nodes[a].get("dept") == G.nodes[b].get("dept")) / e
    deg = Counter()
    for n, d in G.degree():
        deg[G.nodes[n].get("dept")] += d
    exp = sum((v / (2 * e)) ** 2 for v in deg.values())
    return obs, exp


def powerlaw_fit(x, xmin_max=50):
    """Discrete power law p(x) ~ x^-alpha for x >= xmin; alpha by MLE (continuous approximation with the
    x_min - 1/2 correction, Clauset et al. 2009 eq. 3.7), xmin by minimum KS distance."""
    x = np.sort(np.asarray([v for v in x if v > 0], dtype=float))
    best = None
    for xmin in range(1, xmin_max + 1):
        tail = x[x >= xmin]
        if len(tail) < 50:
            break
        alpha = 1 + len(tail) / np.sum(np.log(tail / (xmin - 0.5)))
        emp = np.arange(1, len(tail) + 1) / len(tail)                       # empirical CDF
        fit = 1 - ((tail + 0.5) / (xmin - 0.5)) ** (1 - alpha)              # fitted CDF (continuous approx.)
        ks = float(np.max(np.abs(emp - fit)))
        if best is None or ks < best["ks"]:
            best = dict(alpha=float(alpha), xmin=int(xmin), n_tail=int(len(tail)), ks=ks,
                        alpha_se=float((alpha - 1) / math.sqrt(len(tail))))
    return best


def network_tests(t, nets):
    F, comms = nets.get("faculty_graph"), nets.get("faculty_communities") or []
    out = {}
    if F is not None and F.number_of_edges():
        G = F.subgraph([n for n in F if F.degree(n) > 0]).copy()          # faculty with at least one link
        nulls = [_rewired(G, k) for k in range(N_NULL)]
        C, L = _cl(G)
        cl_null = [_cl(H) for H in nulls]
        Cn, Ln = float(np.mean([c for c, _ in cl_null])), float(np.mean([l for _, l in cl_null]))
        q = nx.community.modularity(G, [c & set(G) for c in comms if c & set(G)], weight=None)
        q_null = [nx.community.modularity(H, nx.community.louvain_communities(H, seed=SEED), weight=None) for H in nulls]
        r = nx.degree_assortativity_coefficient(G)
        r_null = [nx.degree_assortativity_coefficient(H) for H in nulls]
        wd, wd_exp = _within_dept(G)
        ra_dept = nx.attribute_assortativity_coefficient(G, "dept")
        ra_inst = nx.attribute_assortativity_coefficient(G, "inst")
        cross = sum(1 for a, b in G.edges if G.nodes[a].get("inst") != G.nodes[b].get("inst"))
        rc_obs = nx.rich_club_coefficient(G, normalized=False)
        rc_null = [nx.rich_club_coefficient(H, normalized=False) for H in nulls[:10]]
        degs = sorted((d for _, d in G.degree()), reverse=True)
        k_top = degs[max(0, len(degs) // 20 - 1)]                          # degree of the top 5%
        rc_levels = sorted({k for k in rc_obs if k >= 5 and k <= k_top})
        rich = [dict(k=int(k), observed=float(rc_obs[k]),
                     null=float(np.mean([h.get(k, np.nan) for h in rc_null])),
                     ratio=float(rc_obs[k] / np.mean([h.get(k, np.nan) for h in rc_null])) if np.mean([h.get(k, 0) for h in rc_null]) else None)
                for k in rc_levels]

        def z(obs, xs):
            sd = float(np.std(xs))
            return float((obs - np.mean(xs)) / sd) if sd else None

        out["faculty"] = dict(
            nodes=G.number_of_nodes(), edges=G.number_of_edges(), n_null=N_NULL,
            clustering=float(C), clustering_null=Cn, path=float(L), path_null=Ln,
            sigma=float((C / Cn) / (L / Ln)) if Cn and Ln else None,
            giant_share=len(_giant(G)) / G.number_of_nodes(),
            modularity=float(q), modularity_null=float(np.mean(q_null)), modularity_null_sd=float(np.std(q_null)),
            modularity_z=z(q, q_null),
            degree_assortativity=float(r), degree_assortativity_null=float(np.mean(r_null)),
            dept_assortativity=float(ra_dept), inst_assortativity=float(ra_inst),
            within_dept_share=float(wd), within_dept_expected=float(wd_exp),
            cross_institute_links=int(cross),
            rich_club=rich,
        )
        # growth: cumulative network of joint papers up to each year
        papers = t["papers"]
        fa = t["own_auth"].dropna(subset=["person"])
        fa = fa[fa["work_id"].isin(papers.index[~papers["is_mega"]])].drop_duplicates(["work_id", "person"])
        fa = fa[fa["person"].isin(set(F))]
        years = papers["year"]
        growth, Gy = [], nx.Graph()
        by_year = {}
        for wid, g in fa.groupby("work_id"):
            ps = sorted(set(g["person"]))
            if len(ps) > 1:
                by_year.setdefault(int(years[wid]), []).append(ps)
        for y in range(config.YEAR_FROM, config.YEAR_TO + 1):
            for ps in by_year.get(y, []):
                for i, a in enumerate(ps):
                    for b in ps[i + 1:]:
                        Gy.add_edge(a, b)
            if Gy.number_of_edges():
                growth.append(dict(year=y, faculty=Gy.number_of_nodes(), links=Gy.number_of_edges(),
                                   giant_share=len(_giant(Gy)) / Gy.number_of_nodes(),
                                   mean_degree=2 * Gy.number_of_edges() / Gy.number_of_nodes()))
        out["growth"] = growth
    C = nets.get("citation_graph")
    if C is not None and C.number_of_edges():
        indeg = [d for _, d in C.in_degree()]
        out["citation"] = dict(powerlaw=powerlaw_fit(indeg), max_in_degree=int(max(indeg)),
                               share_cited_internally=float(np.mean([d > 0 for d in indeg])))
    return out
