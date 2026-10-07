"""Testes caixa-preta do subcomando ``top`` (AC-3, AC-4, AC-12, AC-14)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness import json_out, run  # noqa: E402

SIMPLE = (
    '{"path":"/b"}\n{"path":"/a"}\n{"path":"/b"}\n{"path":"/a"}\n{"path":"/c"}\n'
)


class TopTest(unittest.TestCase):
    def test_ac_3_nginx_parsing(self):
        proc = run("top", "--by", "path", "--json", "tests/fixtures/ac3.log")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json_out(proc)
        self.assertEqual(data["input"]["format"], "nginx")
        self.assertEqual(data["input"]["lines_valid"], 1)
        self.assertEqual(data["input"]["formats_seen"], {"nginx": 1})
        self.assertEqual(data["entries"], [{"value": "/index.html", "count": 1}])

    def test_ac_4_top_by_status(self):
        proc = run("top", "--by", "status", "--json", "tests/fixtures/ac4.log")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json_out(proc)
        self.assertEqual(data["input"]["format"], "apache")
        self.assertEqual(
            data["entries"],
            [{"value": "404", "count": 1}, {"value": "500", "count": 1}],
        )

    def test_ac_4_top_by_path_strips_query(self):
        proc = run("top", "--by", "path", "--json", "tests/fixtures/ac4.log")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json_out(proc)
        self.assertEqual(
            data["entries"],
            [{"value": "/health", "count": 1}, {"value": "/login", "count": 1}],
        )

    def test_ac_12_tie_breaks_by_value_ascending(self):
        proc = run("top", "--by", "path", "--n", "3", "--json", "tests/fixtures/ac12.jsonl")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json_out(proc)
        self.assertEqual(
            data["entries"],
            [
                {"value": "/a", "count": 2},
                {"value": "/b", "count": 2},
                {"value": "/c", "count": 1},
            ],
        )

    def test_ac_14_missing_by_is_usage_error(self):
        proc = run("top", "tests/fixtures/ac1.jsonl")
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(proc.stdout, "")
        self.assertNotEqual(proc.stderr, "")

    def test_text_output(self):
        proc = run("top", "--by", "path", "--n", "2", stdin=SIMPLE)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, "2\t/a\n2\t/b\n")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
