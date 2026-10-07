#!/usr/bin/env python3
"""Wrapper executável do log-analyzer (delega para src/log_analyzer.py)."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from log_analyzer import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
