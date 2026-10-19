"""Run with python -B -m unittest discover -s tests -p 'test_resilience*.py'."""
import copy
import csv
import itertools
import json
from pathlib import Path
import random
import tempfile
import unittest

from pipeline.resilience import analyze_resilience, classify_roles, write_resilience_csv


def analyze(ids, pairs, metrics=None):
    nodes = {str(i): dict(name=f"Researcher {i}", inst="IISc", dept="Physics") for i in ids}
    return analyze_resilience(nodes, [(str(a), str(b), {"weight": 1}) for a, b in pairs], metrics)


def by_id(result):
    return {r["person"]: r for r in result["researchers"]}


class ResilienceTests(unittest.TestCase):
    def test_path_exact_counts(self):
        r = analyze(range(5), zip(range(4), range(1, 5)))
        self.assertEqual(r["baseline"]["connected_pairs"], 10)
        middle = by_id(r)["2"]
        self.assertEqual(middle["lost_connected_pairs"], 4)
        self.assertEqual(middle["connected_pairs_before_remaining"], 6)
        self.assertAlmostEqual(middle["lost_pair_fraction"], 4/6)
        self.assertAlmostEqual(middle["connected_pair_fraction_after"], 2/6)
        self.assertEqual(middle["fragment_sizes"], [2, 2])
        self.assertEqual(middle["components_after"], 2)
        self.assertEqual(middle["nodes_after"], 4)
        self.assertEqual(middle["edges_after"], 2)
        self.assertEqual(by_id(r)["0"]["lost_connected_pairs"], 0)

    def test_star_center_vs_leaf(self):
        r = by_id(analyze(range(6), [(0, i) for i in range(1, 6)]))
        self.assertEqual(r["0"]["lost_connected_pairs"], 10)
        self.assertEqual(r["0"]["lost_pair_fraction"], 1)
        self.assertEqual(r["0"]["components_after"], 5)
        self.assertEqual(r["1"]["lost_connected_pairs"], 0)
        self.assertEqual(r["1"]["components_after"], 1)
        self.assertTrue(r["0"]["is_hub"])
        self.assertTrue(r["0"]["is_critical_bridge"])

    def test_complete_graph_hub_is_redundant(self):
        result = analyze(range(6), itertools.combinations(range(6), 2))
        for r in result["researchers"]:
            self.assertEqual(r["lost_connected_pairs"], 0)
            self.assertEqual(r["connected_pair_fraction_after"], 1)
            self.assertEqual(r["largest_component_share_after"], 1)
            self.assertIn("Hub, low fragmentation", r["roles"])
            self.assertIn("Redundant connector", r["roles"])
            self.assertFalse(r["is_critical_bridge"])

    def test_two_cliques_with_bridge_researcher(self):
        pairs = list(itertools.combinations(range(3), 2)) + list(itertools.combinations(range(4, 7), 2))
        pairs += [(2, 3), (3, 4)]
        result = by_id(analyze(range(7), pairs))
        self.assertEqual(result["3"]["degree"], 2)
        self.assertEqual(result["3"]["lost_connected_pairs"], 9)
        self.assertAlmostEqual(result["3"]["lost_pair_fraction"], 9/15)
        self.assertEqual(result["3"]["fragment_sizes"], [3, 3])
        self.assertTrue(result["3"]["is_critical_bridge"])
        self.assertEqual(result["0"]["lost_connected_pairs"], 0)

    def test_disconnected_graph_and_isolate_denominators(self):
        result = analyze(range(6), [(0, 1), (1, 2), (3, 4)])
        self.assertEqual(result["baseline"]["components"], 3)
        self.assertAlmostEqual(result["baseline"]["connected_pair_fraction"], 4/15)
        bridge = by_id(result)["1"]
        self.assertEqual(bridge["connected_pairs_before_remaining"], 2)
        self.assertEqual(bridge["connected_pairs_after"], 1)
        self.assertEqual(bridge["lost_connected_pairs"], 1)
        self.assertAlmostEqual(bridge["lost_pair_fraction"], .5)
        self.assertAlmostEqual(bridge["survivor_connected_pair_fraction_before"], .2)
        self.assertAlmostEqual(bridge["connected_pair_fraction_after"], .1)
        self.assertEqual(bridge["components_after"], 4)
        isolate = by_id(result)["5"]
        self.assertEqual(isolate["lost_connected_pairs"], 0)
        self.assertGreater(isolate["connected_pair_fraction_change"], 0)
        self.assertEqual(isolate["connected_pair_fraction_loss"], 0)
        self.assertEqual(isolate["components_after"], 2)

    def test_empty_singleton_pair_and_edgeless(self):
        empty = analyze([], [])
        self.assertEqual(empty["researchers"], [])
        self.assertEqual(empty["baseline"]["largest_component_share"], 0)
        self.assertEqual(empty["summary"]["max_lost_pair_fraction"], 0)
        single = analyze(["R:IISc:1"], [])["researchers"][0]
        self.assertEqual(single["person"], "R:IISc:1")
        self.assertEqual(single["nodes_after"], 0)
        self.assertEqual(single["components_after"], 0)
        self.assertEqual(single["lost_pair_fraction"], 0)
        self.assertEqual(single["connected_pair_fraction_after"], 0)
        for r in analyze([0, 1], [(0, 1)])["researchers"]:
            self.assertEqual(r["connected_pairs_before_remaining"], 0)
            self.assertEqual(r["lost_connected_pairs"], 0)
        for r in analyze(range(4), [])["researchers"]:
            self.assertEqual(r["components_after"], 3)
            self.assertEqual(r["largest_component_share_after"], 1/3)

    def test_community_metadata_and_stable_identity(self):
        metrics = {"R:IISc:0": {"community": 0, "betweenness": .25},
                   "R:IISc:1": {"community": 0}, "H:TIFR:A9": {"community": 1}}
        nodes = {p: dict(name="Same name", inst="TIFR" if p.startswith("H:") else "IISc", dept="Physics") for p in metrics}
        edges = [("R:IISc:0", p, {"weight": 2}) for p in ["R:IISc:1", "H:TIFR:A9"]]
        result = analyze_resilience(nodes, edges, metrics)
        r = by_id(result)["R:IISc:0"]
        self.assertEqual(r["neighbor_communities"], 2)
        self.assertEqual(r["cross_community_edges"], 1)
        self.assertEqual(r["cross_community_fraction"], .5)
        self.assertEqual(r["cross_institution_edges"], 1)
        self.assertEqual(r["betweenness"], .25)
        self.assertIn("Cross-community connector", r["roles"])
        self.assertEqual(len({r["person"] for r in result["researchers"]}), 3)
        unknown = by_id(analyze_resilience(nodes, edges))["R:IISc:0"]
        self.assertIsNone(unknown["cross_community_fraction"])
        self.assertIsNone(unknown["community"])
        self.assertIsNone(unknown["betweenness"])

    def test_classification_boundaries_and_overlaps(self):
        self.assertIn("Critical bridge", classify_roles(10, 1, .01, 2, 1, 10))
        self.assertIn("Hub", classify_roles(10, 1, .01, 2, 1, 10))
        roles = classify_roles(10, 1, .00999, 2, 1, 10)
        self.assertNotIn("Critical bridge", roles)
        self.assertIn("Local bridge", roles)
        self.assertIn("Hub, low fragmentation", roles)
        self.assertIn("Redundant connector", classify_roles(3, 0, 0, 1, 0, 3))
        self.assertEqual(classify_roles(0, 0, 0, 0, 0, 3), ["Limited measured structural impact"])

    def test_determinism_independence_and_no_mutation(self):
        nodes = {str(i): dict(name=str(i)) for i in range(10)}
        edges = [(str(i), str(i+1), {"weight": i+1}) for i in range(9)]
        original = copy.deepcopy((nodes, edges))
        expected = analyze_resilience(nodes, edges)
        random.Random(42).shuffle(edges)
        actual = analyze_resilience(dict(reversed(list(nodes.items()))), edges)
        self.assertEqual(expected, actual)
        self.assertEqual(nodes, original[0])
        self.assertEqual(sorted(edges), sorted(original[1]))
        # Repeated runs and each removal use the full original graph.
        self.assertEqual(actual, analyze_resilience(nodes, edges))
        self.assertTrue(all(r["nodes_after"] == 9 for r in actual["researchers"]))
        json.dumps(actual, allow_nan=False)

    def test_simple_graph_contract(self):
        with self.assertRaises(ValueError):
            analyze([0, 1], [(0, 1), (1, 0)])
        with self.assertRaises(ValueError):
            analyze([0], [(0, 0)])
        with self.assertRaises(ValueError):
            analyze([0], [(0, 1)])

    def test_exhaustive_five_node_graphs_against_pair_reachability(self):
        # Independent pair-by-pair oracle, including every disconnected shape.
        ids = list(range(5))
        candidates = list(itertools.combinations(ids, 2))
        for mask in range(1 << len(candidates)):
            pairs = [p for i, p in enumerate(candidates) if mask & (1 << i)]
            reach = [[i == j or (min(i,j), max(i,j)) in pairs for j in ids] for i in ids]
            for k in ids:
                for i in ids:
                    for j in ids:
                        reach[i][j] |= reach[i][k] and reach[k][j]
            result = by_id(analyze(ids, pairs))
            for removed in ids:
                remain = [i for i in ids if i != removed]
                after = [[i == j or ((min(i,j), max(i,j)) in pairs and removed not in (i,j))
                          for j in ids] for i in ids]
                for k in remain:
                    for i in remain:
                        for j in remain:
                            after[i][j] |= after[i][k] and after[k][j]
                lost = sum(reach[i][j] and not after[i][j] for i,j in itertools.combinations(remain, 2))
                row = result[str(removed)]
                self.assertEqual(row["lost_connected_pairs"], lost, (mask, removed))

    def test_known_community_denominator_and_weights(self):
        nodes = {"a": {}, "b": {}, "c": {}}
        edges = [("a", "b", {"weight": 1}), ("a", "c", {"weight": 99})]
        metrics = {"a": {"community": 0}, "b": {"community": 1}, "c": {"community": -1}}
        r = by_id(analyze_resilience(nodes, edges, metrics))["a"]
        self.assertEqual(r["comparable_community_edges"], 1)
        self.assertEqual(r["cross_community_fraction"], 1)
        self.assertEqual(r["neighbor_communities"], 1)
        self.assertNotIn("Cross-community connector", r["roles"])
        unweighted = [(a, b, {"weight": 1}) for a,b,_ in edges]
        self.assertEqual(analyze_resilience(nodes, edges, metrics)["researchers"],
                         analyze_resilience(nodes, unweighted, metrics)["researchers"])

    def test_csv_exports_in_explicit_temporary_destination(self):
        result = analyze(range(5), [(i, i+1) for i in range(4)])
        with tempfile.TemporaryDirectory() as tmp:
            write_resilience_csv(result, Path(tmp))
            with (Path(tmp)/"faculty_resilience.csv").open(encoding="utf-8", newline="") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 5)
            self.assertEqual(rows[0]["person"], result["researchers"][0]["person"])
            self.assertEqual(int(rows[0]["lost_connected_pairs"]), result["researchers"][0]["lost_connected_pairs"])
            with (Path(tmp)/"resilience_summary.csv").open(encoding="utf-8", newline="") as f:
                summary = next(csv.DictReader(f))
            self.assertEqual(int(summary["nodes"]), 5)
            self.assertEqual(float(summary["critical_loss_fraction"]), .01)


if __name__ == "__main__":
    unittest.main()
