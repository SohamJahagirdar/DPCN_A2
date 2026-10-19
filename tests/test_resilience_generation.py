"""Test actual generators offline with isolated configuration, never real config."""
import copy
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import re
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load_source(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "pipeline" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class GenerationTests(unittest.TestCase):
    def test_html_timestamp_is_actual_utc_and_preserves_statistics_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = types.ModuleType("config")
            config.EXTERNAL = Path(tmp)
            config.DASHBOARD_FILE = Path(tmp) / "index.html"
            requests = types.ModuleType("requests")
            requests.RequestException = RuntimeError
            with patch.dict("sys.modules", {"config": config, "requests": requests}):
                module = load_source("isolated_dashboard", "dashboard.py")
                # Vendor embedding is exercised in the real-snapshot preview;
                # this unit test isolates metadata and actual template injection.
                module._inline_scripts = lambda html: html
                st = dict(meta=dict(generated="2026-10-15 23:54", group=18), resilience={"score": 1/3})
                nf = dict(meta=dict(generated="2026-10-15 23:55", group=18), flagged=[1])
                before = copy.deepcopy((st, nf))
                start = datetime.now(timezone.utc).replace(microsecond=0)
                module.write_dashboard(st, nf, [])
                end = datetime.now(timezone.utc)
                html = config.DASHBOARD_FILE.read_text(encoding="utf-8")
                payloads = [json.loads(re.search(r"^const " + name + r" = (.*);[^\r\n]*$", html, re.M).group(1))
                            for name in ("DATA_ALL", "DATA_NF")]
                stamp = datetime.fromisoformat(payloads[0]["meta"]["dashboard_generated_utc"])
                self.assertLessEqual(start, stamp)
                self.assertLessEqual(stamp, end)
                self.assertEqual(stamp.utcoffset().total_seconds(), 0)
                self.assertEqual(payloads[0]["meta"]["dashboard_generated_utc"], payloads[1]["meta"]["dashboard_generated_utc"])
                self.assertEqual(payloads[0]["meta"]["generated"], st["meta"]["generated"])
                self.assertEqual(payloads[1]["meta"]["generated"], nf["meta"]["generated"])
                self.assertEqual((st, nf), before)
                self.assertIn("Corpus snapshot date unrecorded", html)
                module.write_dashboard(st)
                html = config.DASHBOARD_FILE.read_text(encoding="utf-8")
                self.assertRegex(html, r"const DATA_NF = null;")

    def test_statistics_preserve_distinct_loss_scores_and_tie_comparisons(self):
        config = types.ModuleType("config")
        build = types.ModuleType("pipeline.build")
        build.h_index = lambda _: 0
        with patch.dict("sys.modules", {"config": config, "pipeline.build": build}):
            stats = load_source("isolated_stats", "stats.py")
        original = dict(other=1/3, resilience=dict(researchers=[
            dict(person="a", lost_pair_fraction=.01000001),
            dict(person="b", lost_pair_fraction=.01000002)]))
        result = stats.dashboard_payload(original)
        self.assertEqual(result["other"], round(1/3, 6))
        self.assertNotEqual(result["resilience"]["researchers"][0]["lost_pair_fraction"],
                            result["resilience"]["researchers"][1]["lost_pair_fraction"])
        self.assertEqual(json.loads(json.dumps(result))["resilience"], original["resilience"])


if __name__ == "__main__":
    unittest.main()
