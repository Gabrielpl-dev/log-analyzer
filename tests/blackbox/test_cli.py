"""Testes caixa-preta do contrato de CLI (AC-14 e convenções de exit code)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import run  # noqa: E402


class CliContractTest(unittest.TestCase):
    def test_ac_14_usage_and_io_errors(self):
        cases = [
            (["frobnicate"], 1),
            (["top", "tests/fixtures/ac1.jsonl"], 1),
            (["report", "tests/fixtures/ac1.jsonl"], 1),
            (["report", "--out", "x.md", "--json", "tests/fixtures/ac1.jsonl"], 1),
            (["summary", "--format", "xml", "tests/fixtures/ac1.jsonl"], 1),
            (["summary", "--top", "0", "tests/fixtures/ac1.jsonl"], 1),
            (["summary", "tests/fixtures/does-not-exist.log"], 2),
        ]
        for args, expected in cases:
            with self.subTest(args=args):
                proc = run(*args)
                self.assertEqual(proc.returncode, expected, proc.stderr)
                self.assertEqual(proc.stdout, "")
                self.assertNotEqual(proc.stderr, "")

    def test_version_string(self):
        proc = run("--version")
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, "log-analyzer 0.1.0\n")

    def test_help_exits_zero(self):
        proc = run("--help")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("summary", proc.stdout + proc.stderr)

    def test_eq_style_flags(self):
        proc = run("summary", "--format=jsonl", "--json", "tests/fixtures/ac1.jsonl")
        self.assertEqual(proc.returncode, 0)
        self.assertIn('"format":"jsonl"', proc.stdout)

    def test_flags_after_file(self):
        proc = run("summary", "tests/fixtures/ac1.jsonl", "--json")
        self.assertEqual(proc.returncode, 0)
        self.assertIn('"command":"summary"', proc.stdout)

    def test_invalid_metric(self):
        proc = run("anomalies", "--metric", "bogus", "tests/fixtures/ac8.jsonl")
        self.assertEqual(proc.returncode, 1)

    def test_invalid_window(self):
        proc = run("anomalies", "--window", "5x", "tests/fixtures/ac8.jsonl")
        self.assertEqual(proc.returncode, 1)

    def test_negative_k(self):
        proc = run("anomalies", "--k", "-1", "tests/fixtures/ac8.jsonl")
        self.assertEqual(proc.returncode, 1)

    def test_unknown_flag(self):
        proc = run("summary", "--bogus", "tests/fixtures/ac1.jsonl")
        self.assertEqual(proc.returncode, 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
