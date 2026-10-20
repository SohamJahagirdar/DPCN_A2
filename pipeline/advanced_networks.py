"""Additional network analyses that can run from the committed CSV outputs.

This module deliberately does not require ``data/raw``. It uses the generated
faculty and authorship tables, so teammates with the repository outputs can
reproduce these analyses without refetching OpenAlex.
"""
from pathlib import Path
import itertools

import networkx as nx
import pandas as pd

import config


def _faculty_names(faculty):
    return set(faculty.loc[faculty["papers"] > 0, "name"].dropna())


def _faculty_graph(edges, faculty_names, include_flagged):
    e = edges[edges["author_a"].isin(faculty_names) & edges["author_b"].isin(faculty_names)].copy()
    if not include_flagged:
        e = e[~e["paper_authors_gt_12"]]
    graph = nx.Graph()
    for row in e.itertuples():
        if row.author_a != row.author_b:
            graph.add_edge(row.author_a, row.author_b)
    return graph


def _bridge_analysis(edges, faculty, out, include_flagged=True):
    names = _faculty_names(faculty)
    e = edges[edges["author_a"].isin(names) & edges["author_b"].isin(names)].copy()
    if not include_flagged:
        e = e[~e["paper_authors_gt_12"]]
    e["cross_iisc_tifr"] = (
        e["inst_a"].isin(["IISc", "TIFR"]) &
        e["inst_b"].isin(["IISc", "TIFR"]) &
        (e["inst_a"] != e["inst_b"])
    )
    cross = e[e["cross_iisc_tifr"]].copy()
    graph = _faculty_graph(edges, names, True)
    without_cross = graph.copy()
    without_cross.remove_edges_from(
        [(r.author_a, r.author_b) for r in cross.itertuples()]
    )
    components = sorted((len(c) for c in nx.connected_components(graph)), reverse=True)
    remaining = sorted((len(c) for c in nx.connected_components(without_cross)), reverse=True)
    counts = pd.concat([
        cross["author_a"].value_counts().rename("cross_institute_edges"),
        cross["author_b"].value_counts().rename("cross_institute_edges"),
    ], axis=1).fillna(0).sum(axis=1)
    bridge = faculty[faculty["name"].isin(counts.index)][["person", "name", "inst", "department"]].copy()
    bridge["cross_institute_edges"] = bridge["name"].map(counts).fillna(0).astype(int)
    partner_sets = {}
    for row in cross.itertuples():
        partner_sets.setdefault(row.author_a, set()).add(row.author_b)
        partner_sets.setdefault(row.author_b, set()).add(row.author_a)
    bridge["cross_institute_partners"] = bridge["name"].map(
        lambda name: len(partner_sets.get(name, set()))
    )
    bridge = bridge[bridge["cross_institute_edges"] > 0].sort_values(
        ["cross_institute_edges", "cross_institute_partners", "name"],
        ascending=[False, False, True],
    )
    bridge.to_csv(out / "bridge_nodes.csv", index=False)
    summary = pd.DataFrame([{
        "faculty_nodes": graph.number_of_nodes(),
        "faculty_edges": graph.number_of_edges(),
        "cross_institute_edges": len(cross),
        "largest_component_all": components[0] if components else 0,
        "components_all": len(components),
        "largest_component_without_iisc_tifr_edges": remaining[0] if remaining else 0,
        "components_without_iisc_tifr_edges": len(remaining),
    }])
    summary.to_csv(out / "bridge_network_summary.csv", index=False)


def _centrality_analysis(faculty_metrics, faculty, out, edges):
    names = _faculty_names(faculty)
    graph = _faculty_graph(
        edges,
        names,
        True,
    )
    coreness = nx.core_number(graph) if graph.number_of_edges() else {}
    metrics = faculty_metrics.merge(
        faculty[["person", "q1_share", "high_impact_share", "h_index", "citations"]],
        on="person",
        how="inner",
    )
    metrics["coreness"] = metrics["name"].map(coreness).fillna(0).astype(int)
    numeric = ["degree_centrality", "betweenness", "n_faculty_coauthors",
               "coreness", "q1_share", "high_impact_share", "h_index", "citations"]
    correlations = []
    for centrality, prestige in itertools.product(
        ["degree_centrality", "betweenness", "coreness"],
        ["q1_share", "high_impact_share", "h_index", "citations"],
    ):
        pair = metrics[[centrality, prestige]].dropna()
        correlations.append({
            "centrality": centrality,
            "prestige": prestige,
            "n": len(pair),
            "pearson": pair[centrality].corr(pair[prestige], method="pearson"),
            "spearman": pair[centrality].corr(pair[prestige], method="spearman"),
        })
    metrics[numeric].to_csv(out / "centrality_vs_prestige_faculty.csv", index=False)
    pd.DataFrame(correlations).to_csv(out / "centrality_vs_prestige_correlations.csv", index=False)


def _rich_club_analysis(edges, faculty, out):
    names = _faculty_names(faculty)
    rows = []
    for label, include_flagged in [("with_flagged", True), ("without_flagged", False)]:
        graph = _faculty_graph(edges, names, include_flagged)
        assortativity = nx.degree_assortativity_coefficient(graph) if graph.number_of_edges() else None
        rich = nx.rich_club_coefficient(graph, normalized=False) if graph.number_of_edges() else {}
        for degree, coefficient in sorted(rich.items()):
            rows.append({
                "variant": label,
                "degree_threshold": degree,
                "rich_club_coefficient": coefficient,
                "nodes": graph.number_of_nodes(),
                "edges": graph.number_of_edges(),
                "degree_assortativity": assortativity,
            })
    pd.DataFrame(rows).to_csv(out / "rich_club_coefficients.csv", index=False)
    summary = []
    for label, include_flagged in [("with_flagged", True), ("without_flagged", False)]:
        graph = _faculty_graph(edges, names, include_flagged)
        summary.append({
            "variant": label,
            "nodes": graph.number_of_nodes(),
            "edges": graph.number_of_edges(),
            "degree_assortativity": (
                nx.degree_assortativity_coefficient(graph)
                if graph.number_of_edges() else None
            ),
            "max_degree": max(dict(graph.degree()).values(), default=0),
        })
    pd.DataFrame(summary).to_csv(out / "rich_club_summary.csv", index=False)


def run(output_dir=None, source_dir=None, include_flagged=True):
    """Compute all three analyses from the existing generated outputs."""
    output_dir = Path(output_dir or config.OUTPUTS) / "stats"
    output_dir.mkdir(parents=True, exist_ok=True)
    base = Path(source_dir or Path(output_dir).parent)
    faculty = pd.read_csv(base / "faculty_list.csv")
    faculty_metrics = pd.read_csv(base / "faculty_network_metrics.csv")
    edges = pd.read_csv(base / "authorship_network.csv")
    _bridge_analysis(edges, faculty, output_dir, include_flagged)
    _centrality_analysis(faculty_metrics, faculty, output_dir, edges)
    _rich_club_analysis(edges, faculty, output_dir)
    print(f"advanced network analyses written to {output_dir}")


def load_results(output_dir=None):
    """Load the generated analysis tables into the dashboard statistics shape."""
    output_dir = Path(output_dir or config.OUTPUTS) / "stats"

    def read(name):
        path = output_dir / name
        frame = pd.read_csv(path)
        return frame.where(pd.notna(frame), None).to_dict("records")

    summary = read("bridge_network_summary.csv")
    return {
        "bridge": {
            "summary": summary[0] if summary else {},
            "nodes": read("bridge_nodes.csv")[:25],
        },
        "centrality": {
            "correlations": read("centrality_vs_prestige_correlations.csv"),
            "faculty": read("centrality_vs_prestige_faculty.csv")[:100],
        },
        "rich_club": {
            "summary": read("rich_club_summary.csv"),
            "coefficients": read("rich_club_coefficients.csv"),
        },
    }
