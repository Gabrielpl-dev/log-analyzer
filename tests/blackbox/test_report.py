"""Testes caixa-preta do subcomando ``report`` (AC-13, AC-14)."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import run  # noqa: E402


class ReportTest(unittest.TestCase):
    def test_ac_13_deterministic_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.md"
            before = set(p.name for p in Path(tmp).iterdir())
            proc = run(
                "report",
                "--out",
                str(out),
                "--now",
                "2026-10-06T12:00:00Z",
                "tests/fixtures/ac1.jsonl",
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            after = set(p.name for p in Path(tmp).iterdir())
            self.assertEqual(after - before, {"out.md"})
            content = out.read_text()
            headings = [
                "# Log Analyzer report",
                "## Summary",
                "## Top paths",
                "## Anomalies",
            ]
            positions = [content.index(h) for h in headings]
            self.assertEqual(positions, sorted(positions))
            self.assertIn("- Generated at: `2026-10-06T12:00:00Z`", content)

    def test_out_dash_writes_stdout_without_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = run(
                "report",
                "--out",
                "-",
                "--now",
                "2026-10-06T12:00:00Z",
                "-",
                stdin='{"status":200,"path":"/a"}\n',
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("# Log Analyzer report", proc.stdout)
            self.assertIn("- Input: `stdin`", proc.stdout)
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_ac_14_missing_out_is_usage_error(self):
        proc = run("report", "tests/fixtures/ac1.jsonl")
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(proc.stdout, "")

    def test_ac_14_json_not_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = run(
                "report",
                "--out",
                str(Path(tmp) / "x.md"),
                "--json",
                "tests/fixtures/ac1.jsonl",
            )
            self.assertEqual(proc.returncode, 1)
            self.assertEqual(proc.stdout, "")
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_unwritable_out_is_io_error(self):
        proc = run(
            "report",
            "--out",
            "/nonexistent-dir-xyz/out.md",
            "tests/fixtures/ac1.jsonl",
        )
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(proc.stdout, "")
        self.assertNotEqual(proc.stderr, "")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
