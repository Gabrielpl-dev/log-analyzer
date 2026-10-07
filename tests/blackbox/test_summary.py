"""Testes caixa-preta do subcomando ``summary`` (AC-1, AC-2, AC-5..AC-7, AC-15)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import json_out, run  # noqa: E402


class SummaryJsonTest(unittest.TestCase):
    def test_ac_1_summary_json_pure_jsonl(self):
        proc = run("summary", "--json", "tests/fixtures/ac1.jsonl")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json_out(proc)
        self.assertEqual(data["version"], "0.1")
        self.assertEqual(data["command"], "summary")
        self.assertEqual(data["input"]["source"], "file")
        self.assertEqual(data["input"]["path"], "tests/fixtures/ac1.jsonl")
        self.assertEqual(data["input"]["format"], "jsonl")
        self.assertEqual(data["input"]["formats_seen"], {"jsonl": 5})
        self.assertEqual(data["input"]["lines_total"], 5)
        self.assertEqual(data["input"]["lines_valid"], 5)
        self.assertEqual(data["input"]["lines_invalid"], 0)
        self.assertEqual(data["total"], 5)
        self.assertEqual(data["levels"], {"info": 3, "error": 2})
        self.assertEqual(data["statuses"], {"200": 3, "500": 1, "503": 1})
        self.assertEqual(
            data["top_paths"],
            [{"value": "/a", "count": 3}, {"value": "/b", "count": 2}],
        )
        latency = data["latency_ms"]
        self.assertEqual(latency["count"], 5)
        for key, expected in (
            ("min", 10.0),
            ("max", 50.0),
            ("mean", 30.0),
            ("p50", 30.0),
            ("p95", 50.0),
            ("p99", 50.0),
        ):
            self.assertAlmostEqual(latency[key], expected, delta=1e-6)

    def test_ac_5_invalid_lines_do_not_abort(self):
        proc = run("summary", "--json", "tests/fixtures/ac5.jsonl")
        self.assertEqual(proc.returncode, 0)
        data = json_out(proc)
        self.assertEqual(data["input"]["lines_total"], 3)
        self.assertEqual(data["input"]["lines_valid"], 1)
        self.assertEqual(data["input"]["lines_invalid"], 2)
        self.assertEqual(data["total"], 1)
        self.assertIn("warning: 2 invalid line(s) skipped", proc.stderr)

    def test_ac_6_all_invalid_exit_3(self):
        proc = run("summary", "--json", "tests/fixtures/ac5_all_invalid.txt")
        self.assertEqual(proc.returncode, 3)
        data = json_out(proc)
        self.assertEqual(data["input"]["lines_valid"], 0)
        self.assertEqual(data["input"]["lines_invalid"], 2)
        self.assertEqual(data["total"], 0)

    def test_ac_7_empty_stdin_exit_0(self):
        proc = run("summary", "--json", stdin="")
        self.assertEqual(proc.returncode, 0)
        data = json_out(proc)
        self.assertEqual(data["input"]["source"], "stdin")
        self.assertIsNone(data["input"]["path"])
        self.assertEqual(data["input"]["lines_total"], 0)
        self.assertEqual(data["total"], 0)
        self.assertIsNone(data["input"]["format"])
        self.assertEqual(data["input"]["formats_seen"], {})
        self.assertIsNone(data["latency_ms"])

    def test_whitespace_only_input(self):
        proc = run("summary", "--json", stdin="  \n\t\n\n")
        self.assertEqual(proc.returncode, 0)
        data = json_out(proc)
        self.assertEqual(data["input"]["lines_total"], 0)
        self.assertEqual(data["total"], 0)

    def test_ac_11_mixed_formats_dominant(self):
        proc = run("summary", "--json", "tests/fixtures/ac11.mixed")
        self.assertEqual(proc.returncode, 0)
        data = json_out(proc)
        self.assertEqual(data["input"]["lines_valid"], 4)
        self.assertEqual(data["input"]["format"], "jsonl")
        self.assertEqual(
            data["input"]["formats_seen"], {"jsonl": 2, "nginx": 1, "apache": 1}
        )

    def test_forced_format_incompatible_lines_become_invalid(self):
        proc = run("summary", "--json", "--format", "nginx", "tests/fixtures/ac1.jsonl")
        self.assertEqual(proc.returncode, 3)
        data = json_out(proc)
        self.assertEqual(data["input"]["lines_valid"], 0)
        self.assertEqual(data["input"]["lines_invalid"], 5)
        self.assertIsNone(data["input"]["format"])
        self.assertEqual(data["input"]["formats_seen"], {})


class SummaryTextTest(unittest.TestCase):
    EXPECTED = """\
total: 5
invalid_lines: 0
format: jsonl
levels:
  error\t2
  info\t3
statuses:
  200\t3
  500\t1
  503\t1
top_paths:
  3\t/a
  2\t/b
latency_ms:
  count\t5
  min\t10.00
  max\t50.00
  mean\t30.00
  p50\t30.00
  p95\t50.00
  p99\t50.00
"""

    def test_ac_2_summary_text(self):
        proc = run("summary", "tests/fixtures/ac1.jsonl")
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, self.EXPECTED)


class StrictTest(unittest.TestCase):
    def test_ac_15_strict_with_invalid_lines(self):
        proc = run("summary", "--strict", "tests/fixtures/ac5.jsonl")
        self.assertEqual(proc.returncode, 3)
        self.assertIn("invalid_lines: 2", proc.stdout)

    def test_quiet_suppresses_warning(self):
        proc = run("summary", "--quiet", "tests/fixtures/ac5.jsonl")
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stderr, "")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
