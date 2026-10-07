"""Regressões dos achados da revisão do PR."""

from __future__ import annotations

import math
import subprocess
import sys
import unittest
from pathlib import Path

from harness import ROOT, json_out, run


class ReviewRegressionsTest(unittest.TestCase):
    @unittest.skipUnless(sys.platform.startswith("linux"), "RLIMIT_AS requer Linux")
    def test_sparse_windows_under_memory_limit(self):
        wrapper = (
            "import resource,runpy,sys; "
            "resource.setrlimit(resource.RLIMIT_AS,(128*1024**2,128*1024**2)); "
            "sys.argv=['app',*sys.argv[1:]]; "
            "runpy.run_path('src/log_analyzer.py',run_name='__main__')"
        )
        for metric, value in (("errors", 1), ("count", 2), ("errors_rate", 0.5)):
            with self.subTest(metric=metric):
                proc = subprocess.run(
                    [sys.executable, "-c", wrapper, "anomalies", "--json", "--metric", metric],
                    input=(
                        '{"timestamp":0,"status":500}\n'
                        '{"timestamp":0,"status":200}\n'
                        '{"timestamp":1767225600000,"status":500}\n'
                        '{"timestamp":1767225600000,"status":200}\n'
                    ),
                    text=True, capture_output=True, cwd=ROOT, timeout=15, check=False,
                )
                self.assertEqual(proc.returncode, 0, proc.stderr)
                data = json_out(proc)
                n = 29453761
                self.assertEqual(data["windows_total"], n)
                self.assertEqual(data["mean"], round(2 * value / n, 6))
                sigma = math.sqrt((2 * (value - 2 * value / n) ** 2
                                   + (n - 2) * (2 * value / n) ** 2) / n)
                self.assertAlmostEqual(data["stddev"], sigma, delta=1e-6)
                self.assertEqual([a["value"] for a in data["anomalies"]], [value, value])
                self.assertEqual(data["anomalies"][0]["start"], "1970-01-01T00:00:00Z")
                self.assertEqual(data["anomalies"][1]["start"], "2026-01-01T00:00:00Z")

    def test_large_finite_latency(self):
        for value in ("1e30", "1e308"):
            for args in (("summary", "--json"), ("summary",), ("report", "--out", "-")):
                with self.subTest(value=value, args=args):
                    proc = run(*args, stdin=f'{{"latency_ms":{value}}}\n' * 2)
                    self.assertEqual(proc.returncode, 0, proc.stderr)
                    if "--json" in args:
                        stats = json_out(proc)["latency_ms"]
                        for key in ("min", "max", "mean", "p50", "p95", "p99"):
                            self.assertEqual(stats[key], float(value))

    def test_nonfinite_latency_is_invalid(self):
        for value in ("1e999", "Infinity", "-Infinity", "NaN", "1" + "0" * 400):
            with self.subTest(value=value):
                proc = run("summary", "--json", stdin=f'{{"latency_ms":{value}}}\n')
                self.assertEqual(proc.returncode, 3, proc.stderr)
                self.assertEqual(json_out(proc)["input"]["lines_invalid"], 1)
        for fmt, suffix in (("apache", ""), ("nginx", ' "-" "curl"')):
            with self.subTest(format=fmt):
                line = ('127.0.0.1 - - [10/Oct/2000:13:55:36 -0700] '
                        '"GET / HTTP/1.0" 200 1' + suffix + ' 1e999\n')
                proc = run("summary", "--json", "--format", fmt, stdin=line)
                self.assertEqual(proc.returncode, 3, proc.stderr)
                self.assertEqual(json_out(proc)["input"]["lines_invalid"], 1)

    def test_readme_describes_buffered_input(self):
        readme = (Path(ROOT) / "README.md").read_text()
        self.assertNotIn("streaming from a file", readme)
        self.assertIn("Memory usage grows with the input size", readme)


if __name__ == "__main__":
    unittest.main()
