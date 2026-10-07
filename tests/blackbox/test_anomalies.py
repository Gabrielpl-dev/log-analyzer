"""Testes caixa-preta do subcomando ``anomalies`` (AC-8..AC-10)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import json_out, run  # noqa: E402

SIGMA_ZERO = (
    '{"timestamp":"2026-01-01T00:00:10Z","status":500}\n'
    '{"timestamp":"2026-01-01T00:00:20Z","status":503}\n'
    '{"timestamp":"2026-01-01T00:00:30Z","status":500}\n'
)

OUT_OF_ORDER = (
    '{"timestamp":"2026-01-01T03:00:00+02:00","status":500}\n'
    '{"timestamp":"2026-01-01T00:30:00Z","status":500}\n'
    '{"timestamp":"2026-01-01T01:00:00Z","status":500}\n'
)


class AnomaliesTest(unittest.TestCase):
    def test_ac_8_exact_formula(self):
        proc = run(
            "anomalies",
            "--window",
            "60s",
            "--k",
            "2",
            "--metric",
            "errors",
            "--json",
            "tests/fixtures/ac8.jsonl",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json_out(proc)
        self.assertEqual(data["window_seconds"], 60)
        self.assertEqual(data["metric"], "errors")
        self.assertEqual(data["k"], 2.0)
        self.assertEqual(data["windows_total"], 6)
        self.assertEqual(data["skipped_no_timestamp"], 0)
        self.assertAlmostEqual(data["mean"], 1.666667, delta=1e-6)
        self.assertAlmostEqual(data["stddev"], 2.867442, delta=1e-6)
        self.assertEqual(len(data["anomalies"]), 1)
        anomaly = data["anomalies"][0]
        self.assertEqual(anomaly["start"], "2026-01-01T00:05:00Z")
        self.assertEqual(anomaly["end"], "2026-01-01T00:06:00Z")
        self.assertEqual(anomaly["value"], 8)
        self.assertAlmostEqual(anomaly["threshold"], 7.401550, delta=1e-6)

    def test_ac_9_sigma_zero_means_no_anomaly(self):
        proc = run("anomalies", "--window", "60s", "--k", "0", "--json", stdin=SIGMA_ZERO)
        self.assertEqual(proc.returncode, 0)
        data = json_out(proc)
        self.assertEqual(data["windows_total"], 1)
        self.assertAlmostEqual(data["stddev"], 0.0, delta=1e-6)
        self.assertEqual(data["anomalies"], [])

    def test_ac_10_out_of_order_and_timezones(self):
        proc = run("anomalies", "--window", "1h", "--k", "2", "--json", stdin=OUT_OF_ORDER)
        self.assertEqual(proc.returncode, 0)
        data = json_out(proc)
        self.assertEqual(data["windows_total"], 2)
        # x = [1, 2] => mean 1.5, sigma 0.5
        self.assertAlmostEqual(data["mean"], 1.5, delta=1e-6)
        self.assertAlmostEqual(data["stddev"], 0.5, delta=1e-6)

    def test_no_timestamps_skipped(self):
        stdin = '{"status":500}\n{"status":500}\n'
        proc = run("anomalies", "--json", stdin=stdin)
        self.assertEqual(proc.returncode, 0)
        data = json_out(proc)
        self.assertEqual(data["windows_total"], 0)
        self.assertEqual(data["skipped_no_timestamp"], 2)
        self.assertIsNone(data["mean"])
        self.assertIsNone(data["stddev"])
        self.assertEqual(data["anomalies"], [])

    def test_errors_rate_metric(self):
        stdin = (
            '{"timestamp":"2026-01-01T00:00:10Z","status":500}\n'
            '{"timestamp":"2026-01-01T00:00:20Z","status":200}\n'
        )
        proc = run("anomalies", "--metric", "errors_rate", "--json", stdin=stdin)
        self.assertEqual(proc.returncode, 0)
        data = json_out(proc)
        self.assertEqual(data["metric"], "errors_rate")
        self.assertEqual(data["windows_total"], 1)

    def test_text_output(self):
        proc = run(
            "anomalies", "--window", "60s", "--k", "2", "tests/fixtures/ac8.jsonl"
        )
        self.assertEqual(proc.returncode, 0)
        self.assertIn("window_seconds: 60", proc.stdout)
        self.assertIn("mean: 1.666667", proc.stdout)
        self.assertIn("stddev: 2.867442", proc.stdout)
        self.assertIn(
            "2026-01-01T00:05:00Z\t2026-01-01T00:06:00Z\tvalue=8\tthreshold=7.401550",
            proc.stdout,
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
