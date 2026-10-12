"""Step 3 - citation network, authorship network and Indian-connectivity tables (Task 4 + Section 7)."""
import itertools
from collections import Counter, defaultdict

import networkx as nx
import numpy as np
import pandas as pd

import config
from pipeline.build import NON_INSTITUTIONS, OWN_IDS, classify_inst
from pipeline.io_utils import read_jsonl
from pipeline.openalex import short_id


def _jaccard(p, q, min_share=0.005):
    """(binary Jaccard on subfields with >= min_share of output, weighted Jaccard on share vectors)."""
    sp, sq = sum(p.values()) or 1, sum(q.values()) or 1
    P = {k: v / sp for k, v in p.items()}
    Q = {k: v / sq for k, v in q.items()}
    a = {k for k, v in P.items() if v >= min_share}
    b = {k for k, v in Q.items() if v >= min_share}
    binary = len(a & b) / len(a | b) if a | b else np.nan
    keys = set(P) | set(Q)
    weighted = sum(min(P.get(k, 0), Q.get(k, 0)) for k in keys) / (sum(max(P.get(k, 0), Q.get(k, 0)) for k in keys) or 1)
    return binary, weighted


def build_networks(t):
    papers, works, homes, flows, inst_meta = t["papers"], t["works"], t["homes"], t["flows"], t["inst_meta"]
    own_auth, persons = t["own_auth"], t["persons"]
    corpus = set(works)
    nets = {"flows_available": all(flows[("outflow", i)] is not None and
                                   (flows[("inflow", i)] is not None or flows.get(("inflow_agg", i)))
                                   for i in config.INSTITUTIONS)}

    ext = {}  # external Indian work id -> record
    for (kind, inst), recs in flows.items():
        if kind not in ("outflow", "inflow"):   # inflow_agg is a summary, not a list of works
            continue
        for r in recs or []:
            ext.setdefault(r["id"], r)
    for r in ext.values():
        for i in r["insts"]:
            inst_meta.setdefault(i["id"], (i["name"], i["type"], "IN"))

    def ext_insts(rec, exclude=()):
        return [i for i in rec["insts"] if i["id"] not in exclude]

    # =================================================================== citation network
    edges = {}  # (src, tgt) -> edge dict
    for wid, w in works.items():
        refs = {short_id(r) for r in w.get("referenced_works") or []}
        for r in refs & corpus:
            if r != wid:
                edges[(wid, r)] = ("internal", None)
    for inst in config.INSTITUTIONS:
        of = flows[("outflow", inst)]
        if of:
            ext_ids = {r["id"] for r in of}
            for wid in (w for w, h in homes.items() if inst in h):
                for r in {short_id(x) for x in works[wid].get("referenced_works") or []} & ext_ids:
                    if (wid, r) not in edges:
                        edges[(wid, r)] = ("outflow", inst)
        inf = flows[("inflow", inst)]
        if inf:
            for rec in inf:
                for c in rec.get("cites", []):
                    if (rec["id"], c) not in edges and rec["id"] not in corpus:
                        edges[(rec["id"], c)] = ("inflow", inst)

    def node_inst(n):
        if n in corpus:
            return ";".join(sorted(homes[n]))
        return "; ".join(i["name"] for i in ext[n]["insts"]) if n in ext else ""

    def node_doi(n):
        if n in corpus:
            return papers.at[n, "doi"]
        return ext.get(n, {}).get("doi")

    def node_year(n):
        if n in corpus:
            return papers.at[n, "year"]
        return ext.get(n, {}).get("year")

    crows = []
    for (s, tg), (etype, _) in edges.items():
        si, ti = node_inst(s), node_inst(tg)
        crows.append(dict(source_doi=node_doi(s), target_doi=node_doi(tg), source_inst=si, target_inst=ti,
                          year=node_year(s), source_id=s, target_id=tg, edge_type=etype,
                          cross_institution=(etype != "internal") or (si != ti)))
    cit = pd.DataFrame(crows, columns=["source_doi", "target_doi", "source_inst", "target_inst", "year",
                                       "source_id", "target_id", "edge_type", "cross_institution"])
    cit.to_csv(config.OUTPUTS / "citation_network.csv", index=False, encoding="utf-8")
    print(f"[networks] citation_network.csv: {len(cit)} edges "
          f"({(cit.edge_type == 'internal').sum()} internal)")

    # metrics on the internal (within-corpus) citation graph
    G = nx.DiGraph()
    G.add_nodes_from(corpus)
    G.add_edges_from((s, tg) for (s, tg), (e, _) in edges.items() if e == "internal")
    pr = nx.pagerank(G, alpha=0.85) if G.number_of_edges() else {n: 1 / max(len(corpus), 1) for n in corpus}
    papers["in_degree"] = pd.Series(dict(G.in_degree()))
    papers["out_degree"] = pd.Series(dict(G.out_degree()))
    papers["pagerank"] = pd.Series(pr)
    papers[["work_id", "doi", "title", "year", "homes", "venue", "citations", "in_degree", "out_degree", "pagerank"]] \
        .sort_values("pagerank", ascending=False).to_csv(config.OUTPUTS / "citation_paper_metrics.csv",
                                                         index=False, encoding="utf-8")
    wcc = sorted((len(c) for c in nx.weakly_connected_components(G)), reverse=True) if len(G) else [0]
    nets["citation_summary"] = dict(
        nodes=G.number_of_nodes(), edges=G.number_of_edges(),
        density=nx.density(G) if len(G) > 1 else 0,
        isolated=sum(1 for n in G if G.degree(n) == 0),
        largest_wcc=wcc[0], largest_wcc_share=wcc[0] / max(len(G), 1),
        mean_in_degree=float(np.mean([d for _, d in G.in_degree()])) if len(G) else 0,
        edges_by_type=cit["edge_type"].value_counts().to_dict(),
    )
    # visualisation subgraph: top papers by PageRank (+ edges among them)
    # The top-300 PageRank papers alone are mostly disconnected; show instead the 350 highest-PageRank
    # papers inside the largest connected component of the top-5000 subgraph.
    pool = G.subgraph(papers.sort_values("pagerank", ascending=False).head(5000).index)
    core = max(nx.weakly_connected_components(pool), key=len) if len(pool) else set()
    top = sorted(core, key=lambda n: -pr.get(n, 0))[:350]
    H = G.subgraph(top)
    nets["citation_vis"] = dict(
        nodes=[dict(id=n, title=str(papers.at[n, "title"])[:140], year=int(papers.at[n, "year"]),
                    inst=papers.at[n, "homes"], field=papers.at[n, "field"], cites=int(papers.at[n, "citations"]),
                    pr=float(pr.get(n, 0)), indeg=int(G.in_degree(n)), doi=papers.at[n, "doi"]) for n in H.nodes],
        edges=[[s, tg] for s, tg in H.edges])

    # citation flows with other Indian institutions
    flow_rows = []
    for (s, tg), (etype, inst) in edges.items():
        if etype == "outflow":
            for i in ext_insts(ext[tg], OWN_IDS[inst]):
                flow_rows.append(dict(inst=inst, direction="out", partner=i["id"], year=node_year(s), our_paper=s, other=tg))
        elif etype == "inflow":
            for i in ext_insts(ext[s], OWN_IDS[inst]):
                flow_rows.append(dict(inst=inst, direction="in", partner=i["id"], year=node_year(s), our_paper=tg, other=s))
    # Within-corpus edges across our two institutions (e.g. IISc-only paper citing a TIFR-only paper).
    # These are labelled "internal" above, so they never appear as outflow/inflow edges -> no double count.
    for (s, tg), (etype, _) in edges.items():
        if etype == "internal" and homes[s] != homes[tg]:
            for a in homes[s] - homes[tg]:
                for b in homes[tg] - homes[s]:
                    pid_b = config.INSTITUTIONS[b]["openalex_ids"][0]
                    pid_a = config.INSTITUTIONS[a]["openalex_ids"][0]
                    flow_rows.append(dict(inst=a, direction="out", partner=pid_b, year=node_year(s), our_paper=s, other=tg))
                    flow_rows.append(dict(inst=b, direction="in", partner=pid_a, year=node_year(s), our_paper=tg, other=s))
    flow = pd.DataFrame(flow_rows, columns=["inst", "direction", "partner", "year", "our_paper", "other"])
    flow["partner_name"] = flow["partner"].map(lambda i: inst_meta.get(i, (i,))[0])
    flow["partner_cluster"] = flow["partner"].map(lambda i: classify_inst(*inst_meta.get(i, (i, None))[:2]))
    nets["flow"] = flow

    # Out-flow in the same unit as aggregated in-flow: distinct Indian works per 100-paper batch.
    from pipeline.fetch import flow_batches
    nets["outflow_batch_works"] = {}
    for inst in config.INSTITUTIONS:
        if flows[("outflow", inst)] is None:
            continue
        out_edges = defaultdict(set)
        for r in flow_rows:
            if r["inst"] == inst and r["direction"] == "out":
                out_edges[r["our_paper"]].add(r["other"])
        nets["outflow_batch_works"][inst] = sum(len(set().union(*(out_edges.get(w, set()) for w in b)))
                                                for b in flow_batches(homes, works, inst, "outflow"))

    # Aggregated in-flow (group_by per batch) -> per-partner counts, used when full in-flow edges are absent
    nets["inflow_agg"] = {}
    for inst in config.INSTITUTIONS:
        agg = flows.get(("inflow_agg", inst))
        if agg and flows[("inflow", inst)] is None:
            rows = []
            for iid, (name, cnt) in agg["by_inst"].items():
                meta = inst_meta.get(iid)
                if iid in OWN_IDS[inst] or not meta or meta[2] != "IN" or NON_INSTITUTIONS.search(name or ""):
                    continue
                rows.append(dict(partner=iid, partner_name=meta[0], partner_cluster=classify_inst(meta[0], meta[1]),
                                 citing_works=cnt))
            nets["inflow_agg"][inst] = dict(
                partners=pd.DataFrame(rows, columns=["partner", "partner_name", "partner_cluster", "citing_works"]),
                by_year={int(k): v for k, v in agg["by_year"].items()}, total=sum(agg["per_batch"]))

    # =================================================================== authorship network
    pap_mega = papers["is_mega"]
    auth = t["auth"]
    auth_nm = auth[~auth["work_id"].map(pap_mega)]
    person_name = {k: p["name"] for k, p in persons.items()}
    oa_person = own_auth.dropna(subset=["person"]).drop_duplicates(["author_id", "inst"]).set_index(["author_id", "inst"])["person"]
    pid_by_author = defaultdict(set)
    for (aid, inst), pk in oa_person.items():
        pid_by_author[aid].add(pk)

    arows = []
    for wid, g in auth_nm.groupby("work_id", sort=False):
        g = g.drop_duplicates("author_id")
        own = g[g["own_insts"] != ""]
        if own.empty:
            continue
        others = g[(g["own_insts"] == "") & (g["indian_inst_ids"] != "")]
        doi, year = papers.at[wid, "doi"], papers.at[wid, "year"]

        def lab(r):
            if r.own_insts:
                return r.own_insts
            return "; ".join(inst_meta.get(i, (i,))[0] for i in r.indian_inst_ids.split(";") if i)

        def nm(r):
            pk = pid_by_author.get(r.author_id)
            return person_name[next(iter(pk))] if pk else r.author_name

        orows = list(own.itertuples())
        for a, b in itertools.combinations(orows, 2):
            arows.append((nm(a), nm(b), doi, lab(a), lab(b), year, a.author_id, b.author_id,
                          lab(a) != lab(b), wid))
        for a in orows:
            for b in others.itertuples():
                arows.append((nm(a), nm(b), doi, lab(a), lab(b), year, a.author_id, b.author_id, True, wid))
    am = pd.DataFrame(arows, columns=["author_a", "author_b", "paper_doi", "inst_a", "inst_b", "year",
                                      "author_a_id", "author_b_id", "cross_institution", "work_id"])
    am.to_csv(config.OUTPUTS / "authorship_network.csv", index=False, encoding="utf-8")
    print(f"[networks] authorship_network.csv: {len(am)} co-authorship edges "
          f"({am['cross_institution'].sum()} cross-institution); mega-collaboration papers "
          f"(>{config.MEGA_AUTHOR_THRESHOLD} authors) excluded")

    # faculty co-authorship graph (analysis network: nodes = faculty)
    fac = t["faculty"]
    fac_ok = fac[fac["papers"] > 0]
    F = nx.Graph()
    for r in fac_ok.itertuples():
        F.add_node(r.person, name=r.name, inst=r.inst, dept=r.department, papers=int(r.papers))
    fa = own_auth.dropna(subset=["person"])
    fa = fa[~fa["is_mega"]].drop_duplicates(["work_id", "person"])
    for wid, g in fa.groupby("work_id"):
        ps = sorted(set(g["person"]))
        for a, b in itertools.combinations(ps, 2):
            if F.has_edge(a, b):
                F[a][b]["weight"] += 1
            else:
                F.add_edge(a, b, weight=1)
    deg_c = nx.degree_centrality(F) if len(F) > 1 else {}
    btw = nx.betweenness_centrality(F, normalized=True) if len(F) > 2 else {}
    comms = nx.community.louvain_communities(F, weight="weight", seed=42) if F.number_of_edges() else []
    comm_of = {n: i for i, c in enumerate(sorted(comms, key=len, reverse=True)) for n in c}
    modularity = nx.community.modularity(F, comms, weight="weight") if comms else None
    # hub authors: number of distinct other Indian institutions among co-authors
    partners_of = defaultdict(set)
    for r in fa.itertuples():
        for i in papers.at[r.work_id, "indian_inst_ids"].split(";"):
            if i and i not in OWN_IDS[r.inst]:
                partners_of[r.person].add(i)
    fm = pd.DataFrame([dict(person=n, name=d["name"], inst=d["inst"], department=d["dept"], papers=d["papers"],
                            n_faculty_coauthors=F.degree(n), joint_papers=F.degree(n, weight="weight"),
                            degree_centrality=deg_c.get(n, 0), betweenness=btw.get(n, 0),
                            community=comm_of.get(n, -1), n_partner_institutions=len(partners_of.get(n, ())))
                       for n, d in F.nodes(data=True)])
    if len(fm):
        fm = fm.sort_values("degree_centrality", ascending=False)
    fm.to_csv(config.OUTPUTS / "faculty_network_metrics.csv", index=False, encoding="utf-8")
    comm_rows = []
    for cid, g in fm[fm["community"] >= 0].groupby("community"):
        comm_rows.append(dict(community=int(cid), size=len(g), insts=", ".join(f"{k} {v}" for k, v in g["inst"].value_counts().items()),
                              top_departments=", ".join(g["department"].value_counts().head(3).index),
                              key_members=", ".join(g.sort_values("betweenness", ascending=False)["name"].head(4))))
    comms_df = pd.DataFrame(comm_rows).sort_values("size", ascending=False) if comm_rows else pd.DataFrame()
    cc = sorted((len(c) for c in nx.connected_components(F)), reverse=True) if len(F) else [0]
    nets["authorship_summary"] = dict(
        faculty_nodes=F.number_of_nodes(), faculty_edges=F.number_of_edges(), density=nx.density(F) if len(F) > 1 else 0,
        isolated_faculty=sum(1 for n in F if F.degree(n) == 0), largest_cc=cc[0],
        n_communities=len([c for c in comms if len(c) > 1]), modularity=modularity,
        avg_clustering=nx.average_clustering(F) if len(F) else 0,
        raw_edges=len(am), raw_cross_edges=int(am["cross_institution"].sum()),
        raw_authors=int(pd.concat([am["author_a_id"], am["author_b_id"]]).nunique()) if len(am) else 0,
        mega_papers_excluded=int(pap_mega.sum()),
    )
    nets["faculty_metrics"] = fm
    nets["communities"] = comms_df
    nets["authorship_vis"] = dict(
        nodes=[dict(id=n, name=d["name"], inst=d["inst"], dept=d["dept"], papers=d["papers"],
                    comm=comm_of.get(n, -1), btw=btw.get(n, 0), deg=F.degree(n)) for n, d in F.nodes(data=True)
               if F.degree(n) > 0],
        edges=[[a, b, d["weight"]] for a, b, d in F.edges(data=True)])

    # =================================================================== Indian connections
    own_subfields = {inst: Counter(papers.loc[papers["homes"].str.contains(inst), "subfield_id"].dropna())
                     for inst in config.INSTITUTIONS}
    ptopics = {r["id"]: r["subfields"] for r in read_jsonl(config.RAW / "partner_topics.jsonl.gz") or []}
    # internal partner profile for our sibling institution
    for inst in config.INSTITUTIONS:
        ptopics.setdefault(config.INSTITUTIONS[inst]["openalex_ids"][0], dict(own_subfields[inst]))
    conn = []
    for inst in config.INSTITUTIONS:
        sub = papers[papers["homes"].str.contains(inst)]
        shared = defaultdict(list)
        for wid, ids in zip(sub.index, sub["indian_inst_ids"]):
            for i in ids.split(";"):
                if i and i not in OWN_IDS[inst]:
                    shared[i].append(wid)
        fl = flow[flow["inst"] == inst]
        cin = fl[fl["direction"] == "in"]["partner"].value_counts()
        if inst in nets["inflow_agg"]:   # citing works per batch, from the aggregated in-flow
            cin = nets["inflow_agg"][inst]["partners"].set_index("partner")["citing_works"]
        cout = fl[fl["direction"] == "out"]["partner"].value_counts()
        for pid in set(shared) | set(cin.index) | set(cout.index):
            name, otype = inst_meta.get(pid, (pid, None, None))[:2]
            if NON_INSTITUTIONS.search(name or ""):
                continue   # "Government of India", ministries: funders/parents, not research partners
            wl = shared.get(pid, [])
            cl = classify_inst(name, otype)
            jb, jw = _jaccard(own_subfields[inst], ptopics[pid]) if pid in ptopics else (np.nan, np.nan)
            conn.append(dict(your_inst=inst, partner_inst=name, shared_papers=len(wl),
                             total_citations=int(papers.loc[wl, "citations"].sum()) if wl else 0,
                             partner_openalex_id=pid, partner_cluster=cl,
                             cross_cluster=cl != config.OWN_CLUSTER,
                             citations_received_from_partner=int(cin.get(pid, 0)),
                             citations_given_to_partner=int(cout.get(pid, 0)),
                             topic_jaccard=jb, topic_weighted_jaccard=jw))
    ic = pd.DataFrame(conn).sort_values(["your_inst", "shared_papers"], ascending=[True, False])
    ic.to_csv(config.OUTPUTS / "indian_connections.csv", index=False, encoding="utf-8")
    print(f"[networks] indian_connections.csv: {len(ic)} institution pairs")
    nets["connections"] = ic
    return nets
