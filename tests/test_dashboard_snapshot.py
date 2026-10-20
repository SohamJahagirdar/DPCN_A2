"""Offline rendering, read-only payload and exact scope semantics."""
import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from pipeline.dashboard import render_dashboard
from pipeline.dashboard_snapshot import (VENDOR_URLS, atomic_write, canonical_rows,
                                       checked_file, generate, scope_summaries, under)
from pipeline.idea_flow import SCHEMA
from pipeline.idea_flow_dashboard import build_payload, render_standalone


def metric(wid, homes, flagged=False):
    return dict(original_id=wid, canonical_id=wid, homes=homes, authors_gt_12=flagged,
                title=wid, query_complete=True, field_id="f1", retrieved_field="F1", known_field_citers=1,
                unknown_field_citers=0, observed_citers=1, cross_field_citers=1, cross_field_share=1.0,
                field_coverage=1.0, original_doi_conflict=False, stored_citations=1, pilot=True,
                age_window=dict(status="eligible"))


class SnapshotGenerationTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        for wid, field in [("W1", "f1"), ("W2", "f2"), ("W3", "f1")]:
            self.db.execute("INSERT INTO works VALUES(?,?,?,?,?,?,?,?,?,?)", (wid, None, wid, 2020, "2020-01-01", "article", field, field.upper(), "{}", "proof.json.gz"))
        for wid in ["W1", "W3"]:
            self.db.execute("INSERT INTO seeds VALUES(?,?,?,?,?)", (wid, wid, "{}", 1, "resolved"))
            self.db.execute("INSERT INTO citations VALUES(?,?,?)", ("W2", wid, "same_year_indeterminate"))
            self.db.execute("INSERT INTO edge_evidence VALUES(?,?,?,?,?)", ("W2", wid, "frontier", "proof.json.gz", "2026-10-19T00:00:00Z"))
        self.rows = [metric("W1", ["IISc", "TIFR"]), metric("W3", ["IISc"], True)]

    def tearDown(self):
        self.db.close()

    def test_scopes_deduplicate_shared_citers_and_retain_joint_membership(self):
        s = scope_summaries(self.db, self.rows)
        self.assertEqual(s["in"]["All"]["direct_edges"], 2)
        self.assertEqual(s["in"]["All"]["distinct_direct_citers"], 1)
        self.assertEqual(s["in"]["IISc"]["original_seeds"], 2)
        self.assertEqual(s["in"]["TIFR"]["original_seeds"], 1)
        self.assertEqual(s["out"]["All"]["direct_edges"], 1)
        self.assertEqual(s["out"]["All"]["cross_denominator"], 1)

    def test_aliases_count_once_in_metrics_and_union_homes(self):
        alias = dict(self.rows[0], original_id="W10", homes=["TIFR"])
        s = scope_summaries(self.db, self.rows + [alias])["in"]["All"]
        self.assertEqual(s["original_seeds"], 3)
        self.assertEqual(s["canonical_seeds"], 2)
        self.assertEqual(s["direct_edges"], 2)
        self.assertEqual(s["distinct_direct_citers"], 1)

    def test_conflicting_alias_flags_fail(self):
        with self.assertRaisesRegex(ValueError, "Conflicting aliased"):
            canonical_rows(self.rows + [dict(self.rows[0], original_id="W10", authors_gt_12=True)])

    def test_unknown_seed_field_never_enters_cross_field_denominator(self):
        rows = copy.deepcopy(self.rows)
        rows[0].update(field_id=None, cross_field_share=None, cross_field_citers=None)
        s = scope_summaries(self.db, rows)["in"]["All"]
        self.assertEqual(s["known_field_citers"], 2)
        self.assertEqual(s["cross_denominator"], 1)
        self.assertEqual(s["cross_numerator"], 1)

    def test_inconsistent_metric_counts_fail(self):
        rows = copy.deepcopy(self.rows)
        rows[0]["observed_citers"] = 99
        with self.assertRaisesRegex(ValueError, "normalized direct pairs"):
            scope_summaries(self.db, rows)

    def test_payload_builder_is_readonly_and_has_exact_direct_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "results").mkdir()
            for name, value in {"seed_metrics": self.rows, "summary": {"full_quality_gate": {"passed": True}}, "g2_summary": {"seeds": []}}.items():
                (root / "results" / (name + ".json")).write_text(json.dumps(value), encoding="utf-8")
            before = {p: p.read_bytes() for p in root.rglob("*.json")}
            changes = self.db.total_changes
            self.db.execute("PRAGMA query_only=ON")
            payload = build_payload(self.db, dict(cutoff="2026-10-15", selected_fields=[], protected_sha256={}), root, "2026-10-20T00:00:00Z")
            self.assertEqual(self.db.total_changes, changes)
            self.assertEqual(before, {p: p.read_bytes() for p in root.rglob("*.json")})
            self.assertEqual(payload["direct_edges"], 2)
            self.assertEqual(payload["distinct_direct_citers"], 1)
            self.assertEqual(payload["paths"]["W1"]["g1"][0]["evidence"]["page"], "proof.json.gz")
            self.assertEqual(payload["seeds"], self.rows)

    def test_deterministic_pure_render_safe_json_and_single_vendor_copies(self):
        st = dict(meta=dict(generated="historical"), flagged=[])
        idea = dict(title="</script><script>bad()</script>\u2028")
        kwargs = dict(idea_flow=idea, build_utc="2026-10-20T00:00:00Z", vendor_sources={u: "/* frozen library */" for u in VENDOR_URLS})
        before = copy.deepcopy((st, idea))
        a = render_dashboard(st, st, [], **kwargs)
        self.assertEqual(a, render_dashboard(st, st, [], **kwargs))
        self.assertEqual((st, idea), before)
        self.assertNotIn('<script src=', a)
        self.assertNotIn('</script><script>bad()', a)
        for u in VENDOR_URLS:
            self.assertEqual(a.count('/* ' + u + ' */'), 1)
        self.assertNotIn('/*__IDEA_', a)
        self.assertIn('id="if-scopeNote"', a)

    def test_missing_vendor_fails_instead_of_cdn_fallback(self):
        with self.assertRaisesRegex(ValueError, "Missing frozen vendor"):
            render_dashboard(dict(meta={}), build_utc="2026-10-20T00:00:00Z", vendor_sources={})

    def test_standalone_uses_shared_controller_and_escapes_script_data(self):
        html = render_standalone({"title": "</script>\u2029"})
        self.assertIn("window.IdeaFlowView.create", html)
        self.assertNotIn('/*__IDEA_', html)
        self.assertNotIn('"title":"</script>', html)

    def test_bad_input_and_timestamp_preserve_outputs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with self.assertRaisesRegex(ValueError, "Required frozen input missing"):
                generate(root / "repo", root / "study", root / "absent.json", root / "baseline.html", root / "new" / "index.html", "2026-10-20T00:00:00Z")
            self.assertFalse((root / "new").exists())
            with self.assertRaisesRegex(ValueError, "Explicit UTC"):
                generate(root / "repo", root / "study", root / "absent.json", root / "baseline.html", root / "index.html", "2026-10-20T00:00:00")
            existing = root / "index.html"
            existing.write_text("preserve", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Preserving existing"):
                generate(root / "repo", root / "study", root / "absent.json", root / "baseline.html", existing, "2026-10-20T00:00:00Z")
            self.assertEqual(existing.read_text(), "preserve")

    def test_output_cannot_replace_repository_or_study(self):
        with tempfile.TemporaryDirectory() as temp:
            r = Path(temp)
            for out in [r / "repo/dashboard/index.html", r / "study/seed.json", r / "baseline.html"]:
                with self.assertRaisesRegex(ValueError, "external staging"):
                    generate(r / "repo", r / "study", r / "release.json", r / "baseline.html", out, "2026-10-20T00:00:00Z")

    def test_hash_mismatch_and_manifest_escape_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / "input"
            p.write_text("changed", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                checked_file(p, "0" * 64)
            with self.assertRaisesRegex(ValueError, "escapes"):
                under(p.parent, "../outside")


if __name__ == "__main__":
    unittest.main()
