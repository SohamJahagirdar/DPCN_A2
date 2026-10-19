"""Independent faculty-removal experiments on the existing co-authorship graph.

No config import, fetching, graph construction, or file writes during analysis.
Connectivity is unweighted; original joint-paper weights are retained for display.
"""
import csv
import math
from collections import Counter


CRITICAL_LOSS_FRACTION = 0.01
HUB_QUANTILE = 0.90

REMOVAL_COLUMNS = [
    "person", "name", "inst", "department", "degree", "betweenness", "community",
    "neighbor_communities", "comparable_community_edges", "cross_community_edges",
    "cross_community_fraction", "neighbor_departments", "cross_institution_edges",
    "original_component_size", "nodes_after", "edges_after", "components_after",
    "largest_component_after", "largest_component_share_after",
    "connected_pairs_before_remaining", "possible_pairs_after", "connected_pairs_after",
    "survivor_connected_pair_fraction_before", "connected_pair_fraction_after",
    "connected_pair_fraction_change", "connected_pair_fraction_loss",
    "lost_connected_pairs", "lost_pair_fraction", "is_articulation", "is_hub",
    "is_critical_bridge", "roles",
]


def _pairs(n):
    return n * (n - 1) // 2


def _components(adj, excluded=None):
    """Connected components in the original adjacency, ignoring one node."""
    unseen = set(adj)
    unseen.discard(excluded)
    parts = []
    while unseen:
        start = min(unseen)
        unseen.remove(start)
        part, stack = {start}, [start]
        while stack:
            node = stack.pop()
            found = adj[node] & unseen
            unseen.difference_update(found)
            part.update(found)
            stack.extend(found)
        parts.append(part)
    return sorted(parts, key=lambda c: (-len(c), min(c)))


def _known_community(value):
    return value is not None and value >= 0


def classify_roles(degree, lost_pairs, loss_fraction, neighbor_communities,
                   cross_community_edges, hub_min_degree):
    """Overlapping operational roles; a hub is not automatically a bridge."""
    roles = []
    critical = lost_pairs > 0 and loss_fraction >= CRITICAL_LOSS_FRACTION
    if critical:
        roles.append("Critical bridge")
    elif lost_pairs > 0:
        roles.append("Local bridge")
    if degree >= hub_min_degree:
        roles.append("Hub" if critical else "Hub, low fragmentation")
    if neighbor_communities >= 2 and cross_community_edges > 0:
        roles.append("Cross-community connector")
    if degree >= 2 and lost_pairs == 0:
        roles.append("Redundant connector")
    if not roles:
        roles.append("Limited measured structural impact")
    return roles


def analyze_resilience(nodes, edges, metrics=None):
    """Return JSON-safe, deterministically ordered results without changing inputs.

    nodes: mapping of existing person keys to name/inst/dept attributes.
    edges: existing graph's (person, person, attribute-dict) edge iterable.
    metrics: mapping keyed by person, with existing betweenness/community values.

    Every experiment ignores one node in the SAME original graph. Lost pairs
    exclude pairs involving that node. Fractions with no eligible pairs are 0.
    """
    metrics = metrics or {}
    if any(not isinstance(n, str) for n in nodes):
        raise ValueError("Researcher identifiers must be existing string person keys")
    ids = sorted(nodes)
    adj = {n: set() for n in ids}
    weights = {}
    for a, b, data in edges:
        if a not in adj or b not in adj or a == b:
            raise ValueError("Edges must join two different existing researchers")
        pair = tuple(sorted((a, b)))
        if pair in weights:
            raise ValueError("Expected the existing simple faculty graph, not duplicate edges")
        weights[pair] = data.get("weight", 1)
        adj[a].add(b)
        adj[b].add(a)
    parts = _components(adj)
    component_of = {node: part for part in parts for node in part}
    sizes = [len(c) for c in parts]
    connected = sum(_pairs(s) for s in sizes)
    n, m = len(ids), len(weights)
    baseline = dict(nodes=n, edges=m, components=len(parts),
                    largest_component=max(sizes, default=0),
                    largest_component_share=max(sizes, default=0) / n if n else 0,
                    possible_pairs=_pairs(n), connected_pairs=connected,
                    connected_pair_fraction=connected / _pairs(n) if n > 1 else 0,
                    component_sizes=sizes)
    positive_degrees = sorted(len(adj[node]) for node in ids if adj[node])
    hub_cutoff = max(3, positive_degrees[math.ceil(HUB_QUANTILE * len(positive_degrees)) - 1]
                     if positive_degrees else 3)
    rows = []
    for person in ids:
        data = nodes[person]
        metric = metrics.get(person, {})
        community = metric.get("community")
        community = int(community) if community is not None else None
        neighbors = adj[person]
        neighbor_comms = [metrics.get(v, {}).get("community") for v in sorted(neighbors)]
        known = [int(c) for c in neighbor_comms if _known_community(c)]
        comparable = len(known) if _known_community(community) else 0
        cross = sum(c != community for c in known) if comparable else 0
        after = _components(adj, person)
        after_sizes = [len(c) for c in after]
        remaining = n - 1
        possible = _pairs(remaining)
        # Subtract exactly the connected pairs involving the removed person.
        original_size = len(component_of[person])
        eligible = connected - (original_size - 1)
        after_connected = sum(_pairs(s) for s in after_sizes)
        lost = eligible - after_connected
        loss_fraction = lost / eligible if eligible else 0
        cpf = after_connected / possible if possible else 0
        roles = classify_roles(len(neighbors), lost, loss_fraction, len(set(known)), cross, hub_cutoff)
        row = dict(
            person=person, name=data.get("name", person), inst=data.get("inst", ""),
            department=data.get("dept", data.get("department", "")), degree=len(neighbors),
            betweenness=float(metric["betweenness"]) if metric.get("betweenness") is not None else None,
            community=community, neighbor_communities=len(set(known)),
            comparable_community_edges=comparable, cross_community_edges=cross,
            cross_community_fraction=cross / comparable if comparable else None,
            neighbor_departments=len({nodes[v].get("dept", nodes[v].get("department")) for v in neighbors
                                      if nodes[v].get("dept", nodes[v].get("department")) not in (None, "", "Unknown")}),
            cross_institution_edges=sum(bool(data.get("inst")) and bool(nodes[v].get("inst"))
                                        and nodes[v]["inst"] != data["inst"] for v in neighbors),
            original_component_size=original_size, nodes_after=remaining, edges_after=m - len(neighbors),
            components_after=len(after), largest_component_after=max(after_sizes, default=0),
            largest_component_share_after=max(after_sizes, default=0) / remaining if remaining else 0,
            connected_pairs_before_remaining=eligible, possible_pairs_after=possible,
            connected_pairs_after=after_connected,
            survivor_connected_pair_fraction_before=eligible / possible if possible else 0,
            connected_pair_fraction_after=cpf,
            connected_pair_fraction_change=cpf - baseline["connected_pair_fraction"],
            connected_pair_fraction_loss=lost / possible if possible else 0,
            lost_connected_pairs=lost, lost_pair_fraction=loss_fraction,
            is_articulation=lost > 0, is_hub=len(neighbors) >= hub_cutoff,
            is_critical_bridge=lost > 0 and loss_fraction >= CRITICAL_LOSS_FRACTION,
            roles="; ".join(roles),
            # Full original-component fragment sizes, not sizes in the sampled drawing.
            fragment_sizes=sorted((len(c & component_of[person]) for c in after
                                   if c & component_of[person]), reverse=True),
        )
        rows.append(row)
    rows.sort(key=lambda r: (-r["lost_pair_fraction"], -r["lost_connected_pairs"], -r["degree"], r["person"]))
    degree_order = sorted(rows, key=lambda r: (-r["degree"], r["person"]))[:10]
    impact_order = rows[:10]
    summary = dict(
        scope="Combined IISc–TIFR faculty graph; institution selection filters researcher rows only",
        simulations=n, articulation_researchers=sum(r["is_articulation"] for r in rows),
        critical_bridges=sum(r["is_critical_bridge"] for r in rows),
        redundant_connectors=sum(r["degree"] >= 2 and not r["lost_connected_pairs"] for r in rows),
        max_lost_pairs=max((r["lost_connected_pairs"] for r in rows), default=0),
        max_lost_pair_fraction=max((r["lost_pair_fraction"] for r in rows), default=0),
        degree_top10_impact_top10_overlap=len({r["person"] for r in degree_order}
                                            & {r["person"] for r in impact_order}) if any(r["lost_connected_pairs"] for r in rows) else 0,
        role_counts=dict(sorted(Counter(role for r in rows for role in r["roles"].split("; ")).items())),
    )
    return dict(baseline=baseline, summary=summary, researchers=rows,
                rules=dict(critical_loss_fraction=CRITICAL_LOSS_FRACTION,
                           hub_quantile=HUB_QUANTILE, hub_min_degree=hub_cutoff),
                edges=[[a, b, int(weights[(a, b)])] for a, b in sorted(weights)])


def write_resilience_csv(result, out_dir):
    """Called by the normal build only; output destination follows its variant."""
    with (out_dir / "faculty_resilience.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=REMOVAL_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(result["researchers"])
    summary = dict(result["baseline"], **result["summary"], **result["rules"])
    summary.pop("component_sizes")
    summary.pop("role_counts")
    with (out_dir / "resilience_summary.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary))
        writer.writeheader()
        writer.writerow(summary)
