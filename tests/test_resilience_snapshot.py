"""Read-only checks against exact faculty edges embedded in committed dashboard.

No project config/build import, APIs, or committed output writes. Full raw-data
integration remains a separate integrator check when the historical snapshot exists.
"""
import csv
from collections import Counter, defaultdict
import itertools
import json
from pathlib import Path
import re
import unittest

from pipeline.resilience import analyze_resilience

ROOT = Path(__file__).resolve().parents[1]


def snapshot_result(name):
    html = (ROOT/"dashboard/index.html").read_text(encoding="utf-8")
    match = re.search(r"^const " + name + r" = (.*);[^\r\n]*$", html, re.M)
    payload = json.loads(match.group(1))
    folder = ROOT/"outputs"
    if name == "DATA_NF":
        folder = folder/"without_flagged"
    with (folder/"faculty_network_metrics.csv").open(encoding="utf-8", newline="") as f:
        metrics = {r["person"]: dict(r, community=int(r["community"]), betweenness=float(r["betweenness"]))
                   for r in csv.DictReader(f)}
    nodes = {p: dict(name=r["name"], inst=r["inst"], dept=r["department"]) for p, r in metrics.items()}
    edges = [(a, b, dict(weight=w)) for a, b, w in payload["authorship"]["vis"]["edges"]]
    return analyze_resilience(nodes, edges, metrics), payload, metrics


class SnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.results = {name: snapshot_result(name) for name in ["DATA_ALL", "DATA_NF"]}

    def test_both_variants_use_exact_committed_graph_and_ids(self):
        for name, (result, payload, metrics) in self.results.items():
            with self.subTest(name=name):
                b = result["baseline"]
                s = payload["authorship"]["summary"]
                self.assertEqual(b["nodes"], s["faculty_nodes"])
                self.assertEqual(b["edges"], s["faculty_edges"])
                self.assertEqual(b["largest_component"], s["largest_cc"])
                self.assertEqual(sum(size == 1 for size in b["component_sizes"]), s["isolated_faculty"])
                self.assertEqual({r["person"] for r in result["researchers"]}, set(metrics))
                for r in result["researchers"]:
                    self.assertEqual(r["degree"], int(metrics[r["person"]]["n_faculty_coauthors"]))
                    self.assertEqual(r["community"], metrics[r["person"]]["community"])
                    self.assertGreaterEqual(r["lost_connected_pairs"], 0)
                    self.assertLessEqual(r["lost_connected_pairs"], r["connected_pairs_before_remaining"])

    def test_variant_changes_are_preserved(self):
        all_r = self.results["DATA_ALL"][0]
        nf_r = self.results["DATA_NF"][0]
        self.assertLessEqual(nf_r["baseline"]["nodes"], all_r["baseline"]["nodes"])
        self.assertLess(nf_r["baseline"]["edges"], all_r["baseline"]["edges"])
        self.assertNotEqual(nf_r["researchers"], all_r["researchers"])

    def test_graphs_match_independent_dataset_attributions(self):
        # Reconcile the dashboard graph with a separate committed deliverable,
        # including node isolates and exact per-paper joint-collaboration weights.
        with (ROOT/"outputs/faculty_list.csv").open(encoding="utf-8", newline="") as f:
            lookup, faculty = {}, {}
            for r in csv.DictReader(f):
                faculty[r["person"]] = r
                for aid in filter(None, r["openalex_ids"].split(";")):
                    key = (r["inst"], aid)
                    self.assertTrue(key not in lookup or lookup[key] == r["person"])
                    lookup[key] = r["person"]
        with (ROOT/"outputs/group18_data.csv").open(encoding="utf-8", newline="") as f:
            dataset = list(csv.DictReader(f))
        for name, (result, payload, metrics) in self.results.items():
            with self.subTest(name=name):
                papers, nodes = defaultdict(set), set()
                limit = 12 if name == "DATA_NF" else 50
                for r in dataset:
                    if r["is_faculty"] != "True":
                        continue
                    person = lookup[(r["institution"], r["author_openalex_id"])]
                    if name == "DATA_ALL" or int(r["n_authors"]) <= limit:
                        nodes.add(person)
                    if int(r["n_authors"]) <= limit:
                        papers[r["openalex_work_id"]].add(person)
                weights = Counter(pair for people in papers.values()
                                  for pair in itertools.combinations(sorted(people), 2))
                embedded = {tuple(sorted((a, b))): w
                            for a, b, w in payload["authorship"]["vis"]["edges"]}
                self.assertEqual(nodes, set(metrics))
                self.assertEqual(dict(weights), embedded)
                for r in result["researchers"]:
                    original = faculty[r["person"]]
                    for field in ("name", "inst", "department"):
                        self.assertEqual(r[field], original[field])
                    self.assertEqual(r["betweenness"], metrics[r["person"]]["betweenness"])

    def test_all_removal_metrics_against_independent_union_find(self):
        # Independent oracle: union remaining edge endpoints, then count roots.
        # This does not call the analyzer's component traversal or pair helpers.
        def components(nodes, edges):
            parents = {n: n for n in nodes}

            def root(node):
                while parents[node] != node:
                    parents[node] = parents[parents[node]]
                    node = parents[node]
                return node

            for a, b, _ in edges:
                if a in parents and b in parents:
                    parents[root(a)] = root(b)
            return {n: root(n) for n in parents}

        def pairs(sizes):
            return sum(n * (n - 1) // 2 for n in sizes)

        for name, (result, payload, metrics) in self.results.items():
            edges = payload["authorship"]["vis"]["edges"]
            original = components(metrics, edges)
            n = len(metrics)
            original_connected = pairs(Counter(original.values()).values())
            for row in result["researchers"]:
                with self.subTest(name=name, person=row["person"]):
                    remaining = set(metrics) - {row["person"]}
                    roots = components(remaining, edges)
                    sizes = list(Counter(roots.values()).values())
                    eligible = pairs(Counter(original[v] for v in remaining).values())
                    after = pairs(sizes)
                    possible = (n - 1) * (n - 2) // 2
                    self.assertEqual(row["nodes_after"], n - 1)
                    self.assertEqual(row["edges_after"], sum(a in remaining and b in remaining for a, b, _ in edges))
                    self.assertEqual(row["components_after"], len(sizes))
                    self.assertEqual(row["largest_component_after"], max(sizes, default=0))
                    self.assertAlmostEqual(row["largest_component_share_after"], max(sizes, default=0)/(n-1))
                    self.assertEqual(row["connected_pairs_before_remaining"], eligible)
                    self.assertEqual(row["connected_pairs_after"], after)
                    self.assertEqual(row["lost_connected_pairs"], eligible - after)
                    self.assertAlmostEqual(row["lost_pair_fraction"], (eligible-after)/eligible if eligible else 0)
                    self.assertAlmostEqual(row["connected_pair_fraction_after"], after/possible)
                    self.assertAlmostEqual(row["connected_pair_fraction_loss"], (eligible-after)/possible)
                    self.assertAlmostEqual(row["connected_pair_fraction_change"], after/possible-original_connected/(n*(n-1)//2))
                    self.assertEqual(row["is_critical_bridge"], eligible > 0 and 100*(eligible-after) >= eligible and after < eligible)


if __name__ == "__main__":
    unittest.main()
