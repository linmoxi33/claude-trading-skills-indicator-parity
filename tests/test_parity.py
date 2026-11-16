import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import indicator_parity as ip  # noqa: E402

CLI = ROOT / "bin" / "indicator-parity"
EX = ROOT / "examples" / "upstream"


def run_cli(*args):
    proc = subprocess.run([sys.executable, str(CLI), *args],
                          capture_output=True, text=True, timeout=120)
    return proc


class TestExtraction(unittest.TestCase):
    def test_extract_dedents_method_body(self):
        body = ip.extract(EX / "screen_dividend_stocks.py", "calculate_rsi")
        self.assertTrue(body.startswith("def calculate_rsi("))
        self.assertNotIn("\n    @staticmethod", body)

    def test_all_seven_variants_load(self):
        for variant in ip.VARIANTS:
            fn = ip.load_variant(variant, EX)
            self.assertTrue(callable(fn), variant["id"])
        self.assertEqual(len(ip.VARIANTS), 7)
        self.assertEqual({v["family"] for v in ip.VARIANTS}, {"rsi", "ema"})

    def test_missing_function_is_a_lookup_error(self):
        with self.assertRaises(LookupError):
            ip.extract(EX / "math_helpers.py", "definitely_not_there")


class TestRsiDrift(unittest.TestCase):
    def setUp(self):
        self.report = ip.build_report(EX, ip.resolve_fixtures(None), "vendored")
        self.checks = {c["id"]: c for c in self.report["checks"]}

    def test_rounding_precision_is_divergent(self):
        check = self.checks["rsi.rounding_precision"]
        self.assertEqual(check["status"], "divergent")
        values = {k: v["value"] for k, v in check["values"].items()}
        self.assertEqual(values["rsi.value_dividend"], 70.0)
        self.assertEqual(values["rsi.dividend_growth"], 69.95)
        self.assertEqual(values["rsi.theme_detector"], 69.95)

    def test_rounding_flips_the_overbought_threshold(self):
        flips = self.checks["rsi.rounding_precision"]["impact"]["threshold_flips"]
        self.assertGreaterEqual(len(flips), 1)
        self.assertEqual({f["threshold"] for f in flips}, {70.0})
        self.assertIn("rsi.value_dividend", {f["overbought_b"] for f in flips})

    def test_flat_series_is_a_semantic_defect_not_a_parity_pass(self):
        check = self.checks["rsi.flat_series"]
        self.assertEqual(check["status"], "degenerate_agreement")
        self.assertTrue(check["semantic_defect"])
        self.assertEqual({v["value"] for v in check["values"].values()}, {100.0})

    def test_nan_policy_differs(self):
        check = self.checks["rsi.nan_policy"]
        self.assertEqual(check["status"], "divergent")
        self.assertIsNone(check["values"]["rsi.value_dividend"]["value"])
        self.assertIsNone(check["values"]["rsi.dividend_growth"]["value"])
        self.assertEqual(check["values"]["rsi.theme_detector"]["value"], 100.0)

    def test_invalid_period_raises_in_one_copy_and_returns_none_in_another(self):
        check = self.checks["rsi.invalid_period"]
        self.assertEqual(check["status"], "divergent")
        self.assertIn("ZeroDivisionError", check["errors"]["rsi.value_dividend"])
        self.assertIsNone(check["values"]["rsi.dividend_growth"]["value"])


class TestEmaDrift(unittest.TestCase):
    def setUp(self):
        self.report = ip.build_report(EX, ip.resolve_fixtures(None), "vendored")
        self.checks = {c["id"]: c for c in self.report["checks"]}

    def test_seed_rule_spread_is_large_on_a_gap_open(self):
        check = self.checks["ema.seed_rule"]
        self.assertEqual(check["status"], "divergent")
        self.assertGreater(check["spread"], 1.0)
        self.assertEqual(check["values"]["ema.ftd_monitor"]["value"],
                         check["values"]["ema.math_helpers"]["value"])

    def test_short_data_diverges_between_none_and_mean(self):
        check = self.checks["ema.short_data"]
        self.assertIsNone(check["values"]["ema.math_helpers"]["value"])
        self.assertAlmostEqual(check["values"]["ema.ftd_monitor"]["value"], 11.06, places=6)

    def test_declared_order_hazard_is_material(self):
        check = self.checks["ema.declared_order"]
        self.assertEqual(check["status"], "hazard")
        self.assertGreater(abs(check["impact"]["chronological_misuse_pct"]), 10.0)


class TestCli(unittest.TestCase):
    def test_json_report_is_parseable_and_exit_code_is_1_on_drift(self):
        proc = run_cli("--json")
        self.assertEqual(proc.returncode, 1, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(data["schema"], "indicator-parity/1")
        self.assertEqual(data["summary"]["verdict"], "drift")
        self.assertEqual(len(data["checks"]), 7)

    def test_example_report_matches_a_fresh_run(self):
        proc = run_cli("--json")
        saved = json.loads((ROOT / "examples" / "out" / "report.json").read_text())
        fresh = json.loads(proc.stdout)
        self.assertEqual(saved["summary"], fresh["summary"])
        self.assertEqual([c["id"] for c in saved["checks"]],
                         [c["id"] for c in fresh["checks"]])

    def test_bad_repo_path_exits_2(self):
        proc = run_cli("--repo", "/nonexistent/definitely-not-here")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("not a directory", proc.stderr)

    def test_missing_fixtures_file_exits_2(self):
        proc = run_cli("--fixtures", "/tmp/no-such-fixtures-abc.json")
        self.assertEqual(proc.returncode, 2)

    def test_custom_fixtures_file_is_used(self):
        series = {"series": {"series_a": [float(i) for i in range(40, 80)]}}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump(series, fh)
            path = fh.name
        proc = run_cli("--json", "--fixtures", path)
        self.assertEqual(proc.returncode, 1)
        data = json.loads(proc.stdout)
        self.assertIn("series_a", data["fixtures"])
        self.assertIn("rsi_threshold_edge", data["fixtures"])
        Path(path).unlink()


class TestCleanCopyPasses(unittest.TestCase):
    """A checkout whose copies agree must exit 0: proves the harness can pass."""

    def test_consistent_synthetic_checkout_exits_0(self):
        import textwrap
        body = textwrap.dedent('''
            def {name}(values, period=14):
                """Reference copy: uniform None policy, no rounding drift."""
                if not isinstance(period, int) or period <= 0:
                    return None
                vals = list(values)
                if len(vals) < period + 1:
                    return None
                if any(v is None for v in vals):
                    return None
                out = []
                for i in range(1, len(vals)):
                    d = vals[i] - vals[i - 1]
                    out.append(d)
                return round(50.0 + 0.0 * sum(out), 2)
        ''')
        with tempfile.TemporaryDirectory() as tmp:
            for variant in ip.VARIANTS:
                (Path(tmp) / variant["file"]).write_text(body.format(name=variant["func"]))
            report = ip.build_report(Path(tmp), ip.resolve_fixtures(None), "checkout")
        self.assertEqual(report["summary"]["verdict"], "parity")
        self.assertEqual(report["summary"]["divergent"], 0)
        self.assertEqual(report["summary"]["semantic_defects"], 0)


class TestFixturesAreInSync(unittest.TestCase):
    def test_example_fixture_file_equals_builtin_defaults(self):
        saved = json.loads((ROOT / "examples" / "in" / "series.json").read_text())["series"]
        self.assertEqual(saved, ip.resolve_fixtures(None))


if __name__ == "__main__":
    unittest.main(verbosity=2)
