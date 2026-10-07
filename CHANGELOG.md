# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-10-06

### Added

- `summary` subcommand: totals, per-level and per-status counts, top paths and
  latency statistics (`min`, `max`, `mean`, nearest-rank `p50`/`p95`/`p99`).
- `top` subcommand: rankings by `path`, `level`, `status` or `message`.
- `anomalies` subcommand: epoch-aligned time windows with mean + k·σ threshold
  detection over the `errors`, `errors_rate` and `count` metrics.
- `report` subcommand: deterministic Markdown report, written to `--out` or to
  `stdout` with `--out -`.
- Three input parsers — JSON lines, nginx combined and apache common — with
  per-line auto-detection and dominant-format reporting.
- Global flags `--format`, `--json`, `--strict`, `--quiet`, `--help` and
  `--version`; exact exit-code contract (`0`–`4`).
- Streaming input from files or `stdin`, tolerant of malformed lines.
- Black-box test suite under `tests/blackbox/` driven by `make test`.
- GitHub Actions CI matrix (Linux + macOS) running lint, tests and smoke.

[0.1.0]: https://github.com/Gabrielpl-dev/log-analyzer/releases/tag/v0.1.0
