"""log-analyzer — normaliza logs de acesso/serviço e produz agregações.

Implementação da SPEC v0.1 (ver SPEC.md). Somente biblioteca padrão.

O modelo interno (normalized record) é um dict com as chaves
``timestamp_ms``, ``level``, ``message``, ``status``, ``path`` e
``latency_ms``; campos ausentes são ``None``.
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
import tempfile
from datetime import UTC, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

VERSION = "0.1.0"
SCHEMA_VERSION = "0.1"
PRODUCT = "log-analyzer"

KNOWN_FIELDS = ("timestamp", "level", "message", "status", "path", "latency_ms")
# Chaves do modelo interno normalizado (timestamp -> timestamp_ms).
RECORD_FIELDS = ("timestamp_ms", "level", "message", "status", "path", "latency_ms")
FORMAT_PRIORITY = ("jsonl", "nginx", "apache")
METRICS = ("errors", "errors_rate", "count")
TOP_FIELDS = ("path", "level", "status", "message")
SUBCOMMANDS = ("summary", "top", "anomalies", "report")

VALUE_FLAGS = {
    "--format",
    "--top",
    "--by",
    "--n",
    "--window",
    "--k",
    "--metric",
    "--out",
    "--now",
}
BOOL_FLAGS = {"--json", "--strict", "--quiet", "--help", "--version"}

HELP = f"""\
{PRODUCT} {VERSION} — analisador de logs de acesso/serviço.

Uso: ./app <subcommand> [options] [FILE]

Subcomandos:
  summary    resumo agregado (total, levels, statuses, top_paths, latency)
  top        ranking por campo (--by path|level|status|message)
  anomalies  detecção de anomalias por janela temporal
  report     relatório Markdown (--out <path.md>; use '-' para stdout)

Flags globais:
  --format auto|jsonl|nginx|apache   força o parser (default: auto)
  --json                             saída JSON compacta
  --strict                           linha inválida => exit 3
  --quiet                            suprime avisos em stderr
  --help                             mostra esta ajuda e sai
  --version                          mostra a versão e sai

Opções:
  --top N        (summary) quantos paths em top_paths (default 10)
  --by FIELD     (top) campo do ranking (obrigatório)
  --n N          (top) quantos itens (default 10)
  --window DUR   (anomalies/report) janela, ex. 30s, 5m, 1h (default 60s)
  --k K          (anomalies/report) fator do threshold (default 2.0)
  --metric M     (anomalies/report) errors|errors_rate|count (default errors)
  --out PATH     (report) destino do Markdown (obrigatório)
  --now ISO8601  (report) instante de geração (UTC)

FILE ausente ou '-' lê de stdin. Códigos de saída: 0 ok, 1 uso, 2 I/O,
3 nenhuma linha válida / linha inválida com --strict, 4 erro interno.
"""


class UsageError(Exception):
    """Erro de uso da CLI (exit 1)."""


class InputError(Exception):
    """Erro de I/O (exit 2)."""


# ---------------------------------------------------------------------------
# Arredondamento half-up (a serialização é a única responsável por arredondar)
# ---------------------------------------------------------------------------


def _quantize(value: float, places: int) -> Decimal:
    exp = Decimal(1).scaleb(-places)
    return Decimal(repr(float(value))).quantize(exp, rounding=ROUND_HALF_UP)


def round_json(value: float) -> float:
    """Arredonda para 6 casas (half-up) e devolve float para o JSON."""
    return float(_quantize(value, 6))


def fmt(value: float, places: int) -> str:
    """Formata um float com ``places`` casas decimais (half-up)."""
    return f"{_quantize(value, places):.{places}f}"


# ---------------------------------------------------------------------------
# Tempo
# ---------------------------------------------------------------------------

_MONTHS = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_TIME_LOCAL_RE = re.compile(r"^(\d{2})/([A-Za-z]{3})/(\d{4}):(\d{2}):(\d{2}):(\d{2}) ([+-]\d{4})$")


def to_ms(dt: datetime) -> int:
    """Converte um datetime com tz para epoch ms (sub-ms truncado)."""
    delta = dt - _EPOCH
    return delta.days * 86400000 + delta.seconds * 1000 + delta.microseconds // 1000


def parse_time_local(text: str) -> int | None:
    """``10/Oct/2000:13:55:36 -0700`` -> epoch ms (UTC)."""
    m = _TIME_LOCAL_RE.match(text.strip())
    if not m:
        return None
    day, mon, year, hour, minute, second, off = m.groups()
    month = _MONTHS.get(mon[:1].upper() + mon[1:].lower())
    if month is None:
        return None
    try:
        sign = 1 if off[0] == "+" else -1
        tz = timezone(sign * timedelta(hours=int(off[1:3]), minutes=int(off[3:5])))
        dt = datetime(int(year), month, int(day), int(hour), int(minute), int(second), tzinfo=tz)
    except ValueError:
        return None
    return to_ms(dt)


def parse_iso(text: str) -> int | None:
    """ISO-8601 com offset (ou sem offset => UTC) -> epoch ms."""
    s = text.strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00") if s.endswith("Z") else s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return to_ms(dt)


def iso_utc(ms: int) -> str:
    return (_EPOCH + timedelta(milliseconds=ms)).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Parsers de entrada
# ---------------------------------------------------------------------------

# nginx combined: request em um único grupo para preservar a mensagem original.
_NGINX_RE = re.compile(
    r'^(\S+) (\S+) (\S+) \[([^\]]+)\] "([^"]*)" (\d{3}) (\S+) "([^"]*)" "([^"]*)"'
    r"(?:\s+(\S+))?\s*$"
)
# apache common (sem referer/user-agent), com latência estendida opcional.
_APACHE_RE = re.compile(
    r'^(\S+) (\S+) (\S+) \[([^\]]+)\] "([^"]*)" (\d{3}) (\S+|-)(?:\s+(\S+))?\s*$'
)


def _level_from_status(status: int) -> str:
    if status >= 500:
        return "error"
    if status >= 400:
        return "warn"
    return "info"


def _coerce_status(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        status = value
    elif isinstance(value, str):
        text = value.strip()
        if not text.isdigit():
            return None
        status = int(text)
    else:
        return None
    if 100 <= status <= 599:
        return status
    return None


def _coerce_latency(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        latency = float(value)
    else:
        return None
    if math.isnan(latency) or latency < 0:
        return None
    return latency


def parse_jsonl(line: str) -> dict | None:
    if not line.startswith("{"):
        return None
    try:
        obj = json.loads(line)
    except (ValueError, RecursionError):
        return None
    if not isinstance(obj, dict):
        return None
    present = [key for key in KNOWN_FIELDS if key in obj]
    if not present:
        return None

    record = dict.fromkeys(RECORD_FIELDS)
    for key in present:
        value = obj[key]
        if value is None:
            continue
        if key == "timestamp":
            if isinstance(value, bool):
                return None
            if isinstance(value, int):
                record["timestamp_ms"] = value
            elif isinstance(value, str):
                ms = parse_iso(value)
                if ms is None:
                    return None
                record["timestamp_ms"] = ms
            else:
                return None
        elif key == "level":
            if not isinstance(value, str):
                return None
            record["level"] = value.lower()
        elif key == "message":
            if not isinstance(value, str):
                return None
            record["message"] = value
        elif key == "status":
            status = _coerce_status(value)
            if status is None:
                return None
            record["status"] = status
        elif key == "path":
            if not isinstance(value, str):
                return None
            record["path"] = value
        elif key == "latency_ms":
            latency = _coerce_latency(value)
            if latency is None:
                return None
            record["latency_ms"] = latency
    return record


def _access_data(match: re.Match[str], status_idx: int, request_idx: int, latency_idx: int | None):
    request = match.group(request_idx)
    parts = request.split()
    if len(parts) < 2:
        return None
    ms = parse_time_local(match.group(4))
    if ms is None:
        return None
    status = int(match.group(status_idx))
    latency = None
    if latency_idx is not None:
        token = match.group(latency_idx)
        if token is not None:
            latency = _coerce_latency_token(token)
            if latency is None:
                return None
    record = dict.fromkeys(RECORD_FIELDS)
    record["timestamp_ms"] = ms
    record["level"] = _level_from_status(status)
    record["message"] = request
    record["status"] = status
    record["path"] = parts[1].split("?")[0]
    record["latency_ms"] = latency
    return record


def _coerce_latency_token(token: str) -> float | None:
    try:
        value = float(token)
    except ValueError:
        return None
    if math.isnan(value) or value < 0:
        return None
    return value


def parse_nginx(line: str) -> dict | None:
    match = _NGINX_RE.match(line)
    if not match:
        return None
    return _access_data(match, status_idx=6, request_idx=5, latency_idx=10)


def parse_apache(line: str) -> dict | None:
    match = _APACHE_RE.match(line)
    if not match:
        return None
    return _access_data(match, status_idx=6, request_idx=5, latency_idx=8)


PARSERS = {"jsonl": parse_jsonl, "nginx": parse_nginx, "apache": parse_apache}


def parse_line(line: str, forced_format: str):
    """Devolve ``(record, format)`` ou ``None`` se a linha for inválida."""
    if forced_format == "auto":
        for name in FORMAT_PRIORITY:
            record = PARSERS[name](line)
            if record is not None:
                return record, name
        return None
    record = PARSERS[forced_format](line)
    if record is None:
        return None
    return record, forced_format


# ---------------------------------------------------------------------------
# Carga e agregação
# ---------------------------------------------------------------------------


def read_source(path_arg: str | None) -> tuple[str, str]:
    """Devolve ``(texto, source)``; source é ``file`` ou ``stdin``."""
    if path_arg is None or path_arg == "-":
        try:
            data = sys.stdin.buffer.read()
        except AttributeError:  # pragma: no cover - stdin sem buffer
            data = sys.stdin.read().encode("utf-8", "replace")
        return data.decode("utf-8", "replace"), "stdin"
    try:
        with open(path_arg, "rb") as handle:
            data = handle.read()
    except OSError as exc:
        raise InputError(f"cannot read input file: {path_arg}: {exc}") from exc
    return data.decode("utf-8", "replace"), "file"


def analyze(text: str, path_arg: str | None, source: str, forced_format: str):
    records = []
    invalid = 0
    seen: dict[str, int] = {}
    for raw in text.split("\n"):
        line = raw.strip()
        if line == "":
            continue
        parsed = parse_line(line, forced_format)
        if parsed is None:
            invalid += 1
        else:
            record, name = parsed
            records.append(record)
            seen[name] = seen.get(name, 0) + 1

    if seen:
        fmt = max(seen.items(), key=lambda kv: (kv[1], -FORMAT_PRIORITY.index(kv[0])))[0]
    else:
        fmt = None

    info = {
        "source": source,
        "path": path_arg if source == "file" else None,
        "format": fmt,
        "formats_seen": {name: seen[name] for name in FORMAT_PRIORITY if name in seen},
        "lines_total": len(records) + invalid,
        "lines_valid": len(records),
        "lines_invalid": invalid,
    }
    return records, info


def percentile(sorted_values: list[float], q: float) -> float:
    n = len(sorted_values)
    rank = max(1, math.ceil(q / 100.0 * n))
    return sorted_values[rank - 1]


def latency_stats(records: list[dict]) -> dict | None:
    values = sorted(r["latency_ms"] for r in records if r["latency_ms"] is not None)
    if not values:
        return None
    count = len(values)
    mean = sum(values) / count
    return {
        "count": count,
        "min": values[0],
        "max": values[-1],
        "mean": mean,
        "p50": percentile(values, 50),
        "p95": percentile(values, 95),
        "p99": percentile(values, 99),
    }


def counts_by(records: list[dict], field: str) -> dict:
    counts: dict = {}
    for record in records:
        value = record[field]
        if value is None:
            continue
        counts[value] = counts.get(value, 0) + 1
    return counts


def top_paths(records: list[dict], limit: int) -> list[dict]:
    counts = counts_by(records, "path")
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [{"value": value, "count": count} for value, count in ordered[:limit]]


def top_entries(records: list[dict], field: str, limit: int) -> list[dict]:
    counts = counts_by(records, field)
    str_counts = {str(key): count for key, count in counts.items()}
    ordered = sorted(str_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [{"value": value, "count": count} for value, count in ordered[:limit]]


def parse_duration(text: str) -> int | None:
    """``30s``/``5m``/``1h`` -> milissegundos."""
    m = re.match(r"^(\d+)([smh])$", text.strip())
    if not m:
        return None
    amount = int(m.group(1))
    unit = {"s": 1000, "m": 60000, "h": 3600000}[m.group(2)]
    if amount <= 0:
        return None
    return amount * unit


def compute_anomalies(records: list[dict], window_ms: int, k: float, metric: str) -> dict:
    timed = [r for r in records if r["timestamp_ms"] is not None]
    skipped = len(records) - len(timed)
    if not timed:
        return {
            "window_ms": window_ms,
            "metric": metric,
            "k": k,
            "windows_total": 0,
            "skipped_no_timestamp": skipped,
            "mean": None,
            "stddev": None,
            "anomalies": [],
        }

    timestamps = [r["timestamp_ms"] for r in timed]
    w_first = min(timestamps) // window_ms
    w_last = max(timestamps) // window_ms
    windows_total = w_last - w_first + 1

    totals = [0] * windows_total
    errors = [0] * windows_total
    for record in timed:
        index = record["timestamp_ms"] // window_ms - w_first
        totals[index] += 1
        if record["status"] is not None and 500 <= record["status"] <= 599:
            errors[index] += 1

    if metric == "count":
        values = [float(total) for total in totals]
    elif metric == "errors_rate":
        values = [errors[i] / totals[i] if totals[i] else 0.0 for i in range(windows_total)]
    else:
        values = [float(count) for count in errors]

    mean = sum(values) / windows_total
    variance = sum((value - mean) ** 2 for value in values) / windows_total
    stddev = math.sqrt(variance)
    threshold = mean + k * stddev

    anomalies = []
    if stddev > 0:
        for i, value in enumerate(values):
            if value > threshold:
                start = (w_first + i) * window_ms
                anomalies.append(
                    {
                        "start": iso_utc(start),
                        "end": iso_utc(start + window_ms),
                        "value": int(value) if metric in ("errors", "count") else value,
                        "threshold": threshold,
                    }
                )

    return {
        "window_ms": window_ms,
        "metric": metric,
        "k": k,
        "windows_total": windows_total,
        "skipped_no_timestamp": skipped,
        "mean": mean,
        "stddev": stddev,
        "anomalies": anomalies,
    }


# ---------------------------------------------------------------------------
# Serialização JSON
# ---------------------------------------------------------------------------


def _dump(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, separators=(",", ":"), ensure_ascii=False) + "\n")


def _rounded_latency(stats: dict) -> dict:
    return {
        "count": stats["count"],
        "min": round_json(stats["min"]),
        "max": round_json(stats["max"]),
        "mean": round_json(stats["mean"]),
        "p50": round_json(stats["p50"]),
        "p95": round_json(stats["p95"]),
        "p99": round_json(stats["p99"]),
    }


def emit_summary_json(records: list[dict], info: dict, top: int) -> None:
    stats = latency_stats(records)
    payload = {
        "version": SCHEMA_VERSION,
        "command": "summary",
        "input": info,
        "total": len(records),
        "levels": counts_by(records, "level"),
        "statuses": {str(key): count for key, count in counts_by(records, "status").items()},
        "top_paths": top_paths(records, top),
        "latency_ms": _rounded_latency(stats) if stats else None,
    }
    _dump(payload)


def emit_top_json(records: list[dict], info: dict, by: str, n: int) -> None:
    payload = {
        "version": SCHEMA_VERSION,
        "command": "top",
        "by": by,
        "n": n,
        "input": info,
        "entries": top_entries(records, by, n),
    }
    _dump(payload)


def emit_anomalies_json(data: dict, info: dict) -> None:
    anomalies = [
        {
            "start": item["start"],
            "end": item["end"],
            "value": item["value"]
            if isinstance(item["value"], int)
            else round_json(item["value"]),
            "threshold": round_json(item["threshold"]),
        }
        for item in data["anomalies"]
    ]
    payload = {
        "version": SCHEMA_VERSION,
        "command": "anomalies",
        "input": info,
        "window_seconds": data["window_ms"] // 1000,
        "metric": data["metric"],
        "k": data["k"],
        "windows_total": data["windows_total"],
        "skipped_no_timestamp": data["skipped_no_timestamp"],
        "mean": round_json(data["mean"]) if data["mean"] is not None else None,
        "stddev": round_json(data["stddev"]) if data["stddev"] is not None else None,
        "anomalies": anomalies,
    }
    _dump(payload)


# ---------------------------------------------------------------------------
# Serialização texto
# ---------------------------------------------------------------------------


def emit_summary_text(records: list[dict], info: dict, top: int) -> None:
    lines = [
        f"total: {len(records)}",
        f"invalid_lines: {info['lines_invalid']}",
        f"format: {info['format'] if info['format'] is not None else 'null'}",
    ]
    levels = counts_by(records, "level")
    if levels:
        lines.append("levels:")
        for name in sorted(levels):
            lines.append(f"  {name}\t{levels[name]}")
    statuses = counts_by(records, "status")
    if statuses:
        lines.append("statuses:")
        for code in sorted(statuses):
            lines.append(f"  {code}\t{statuses[code]}")
    paths = top_paths(records, top)
    if paths:
        lines.append("top_paths:")
        for entry in paths:
            lines.append(f"  {entry['count']}\t{entry['value']}")
    stats = latency_stats(records)
    if stats is None:
        lines.append("latency_ms: null")
    else:
        lines.append("latency_ms:")
        lines.append(f"  count\t{stats['count']}")
        lines.append(f"  min\t{fmt(stats['min'], 2)}")
        lines.append(f"  max\t{fmt(stats['max'], 2)}")
        lines.append(f"  mean\t{fmt(stats['mean'], 2)}")
        lines.append(f"  p50\t{fmt(stats['p50'], 2)}")
        lines.append(f"  p95\t{fmt(stats['p95'], 2)}")
        lines.append(f"  p99\t{fmt(stats['p99'], 2)}")
    sys.stdout.write("\n".join(lines) + "\n")


def emit_top_text(records: list[dict], by: str, n: int) -> None:
    entries = top_entries(records, by, n)
    if not entries:
        return
    sys.stdout.write("\n".join(f"{e['count']}\t{e['value']}" for e in entries) + "\n")


def emit_anomalies_text(data: dict) -> None:
    lines = [
        f"window_seconds: {data['window_ms'] // 1000}",
        f"metric: {data['metric']}",
        f"k: {float(data['k'])}",
        f"windows_total: {data['windows_total']}",
    ]
    if data["mean"] is None:
        lines.append("mean: null")
        lines.append("stddev: null")
    else:
        lines.append(f"mean: {fmt(data['mean'], 6)}")
        lines.append(f"stddev: {fmt(data['stddev'], 6)}")
    if not data["anomalies"]:
        lines.append("anomalies: none")
    else:
        lines.append("anomalies:")
        for item in data["anomalies"]:
            value = (
                str(item["value"])
                if isinstance(item["value"], int)
                else fmt(item["value"], 6)
            )
            lines.append(
                f"  {item['start']}\t{item['end']}\tvalue={value}\t"
                f"threshold={fmt(item['threshold'], 6)}"
            )
    sys.stdout.write("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# Report Markdown
# ---------------------------------------------------------------------------


def build_report(records, info, top, data, generated_at: str) -> str:
    out = []
    out.append("# Log Analyzer report")
    out.append("")
    out.append(f"- Input: `{info['path'] if info['source'] == 'file' else 'stdin'}`")
    out.append(f"- Format: `{info['format'] if info['format'] is not None else 'null'}`")
    out.append(f"- Generated at: `{generated_at}`")
    out.append(f"- Lines: `{info['lines_valid']} valid, {info['lines_invalid']} invalid`")
    out.append("")

    out.append("## Summary")
    out.append("")
    out.append(f"- Total: {len(records)}")
    out.append("")
    levels = counts_by(records, "level")
    out.append("| Level | Count |")
    out.append("|---|---|")
    for name in sorted(levels):
        out.append(f"| {name} | {levels[name]} |")
    out.append("")
    statuses = counts_by(records, "status")
    out.append("| Status | Count |")
    out.append("|---|---|")
    for code in sorted(statuses):
        out.append(f"| {code} | {statuses[code]} |")
    out.append("")
    stats = latency_stats(records)
    if stats is None:
        out.append("no latency data")
    else:
        out.append("| Metric | Value |")
        out.append("|---|---|")
        out.append(f"| count | {stats['count']} |")
        out.append(f"| min | {fmt(stats['min'], 2)} |")
        out.append(f"| max | {fmt(stats['max'], 2)} |")
        out.append(f"| mean | {fmt(stats['mean'], 2)} |")
        out.append(f"| p50 | {fmt(stats['p50'], 2)} |")
        out.append(f"| p95 | {fmt(stats['p95'], 2)} |")
        out.append(f"| p99 | {fmt(stats['p99'], 2)} |")
    out.append("")

    out.append("## Top paths")
    out.append("")
    out.append("| Path | Count |")
    out.append("|---|---|")
    for entry in top_paths(records, top):
        out.append(f"| {entry['value']} | {entry['count']} |")
    out.append("")

    out.append("## Anomalies")
    out.append("")
    out.append(f"- Window: {data['window_ms'] // 1000}s")
    out.append(f"- Metric: {data['metric']}")
    out.append(f"- K: {float(data['k'])}")
    out.append("")
    if not data["anomalies"]:
        out.append("No anomalies detected.")
    else:
        out.append("| Start | End | Value | Threshold |")
        out.append("|---|---|---|---|")
        for item in data["anomalies"]:
            value = (
                str(item["value"])
                if isinstance(item["value"], int)
                else fmt(item["value"], 6)
            )
            out.append(
                f"| {item['start']} | {item['end']} | {value} | "
                f"{fmt(item['threshold'], 6)} |"
            )
    out.append("")
    return "\n".join(out)


def write_report(path: str, content: str) -> None:
    if path == "-":
        sys.stdout.write(content)
        return
    if os.path.isdir(path):
        raise InputError(f"cannot write output file: {path}: is a directory")
    directory = os.path.dirname(os.path.abspath(path))
    try:
        fd, tmp = tempfile.mkstemp(dir=directory, prefix=".log-analyzer-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(content)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except OSError as exc:
        raise InputError(f"cannot write output file: {path}: {exc}") from exc


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_argv(argv: list[str]) -> tuple[dict, list[str]]:
    flags: dict = {}
    positionals: list[str] = []
    index = 0
    while index < len(argv):
        token = argv[index]
        index += 1
        if token == "--":
            positionals.extend(argv[index:])
            break
        if token.startswith("--"):
            name, sep, inline = token.partition("=")
            if name in BOOL_FLAGS:
                if sep:
                    raise UsageError(f"flag does not take a value: {name}")
                flags[name] = True
            elif name in VALUE_FLAGS:
                if sep:
                    value = inline
                else:
                    if index >= len(argv):
                        raise UsageError(f"missing value for {name}")
                    value = argv[index]
                    index += 1
                flags[name] = value
            else:
                raise UsageError(f"unknown flag: {name}")
        elif token.startswith("-") and token != "-":
            raise UsageError(f"unknown flag: {token}")
        else:
            positionals.append(token)
    return flags, positionals


def _positive_int(flags: dict, name: str, default: int) -> int:
    raw = flags.get(name)
    if raw is None:
        return default
    if not re.match(r"^\d+$", raw.strip()):
        raise UsageError(f"{name} must be a positive integer")
    value = int(raw)
    if value < 1:
        raise UsageError(f"{name} must be >= 1")
    return value


def _float_flag(flags: dict, name: str, default: float) -> float:
    raw = flags.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise UsageError(f"{name} must be a number") from exc
    if math.isnan(value) or value < 0:
        raise UsageError(f"{name} must be >= 0")
    return value


def _duration_flag(flags: dict, name: str, default_ms: int) -> int:
    raw = flags.get(name)
    if raw is None:
        return default_ms
    value = parse_duration(raw)
    if value is None:
        raise UsageError(f"{name} must look like 30s, 5m or 1h")
    return value


def run(argv: list[str]) -> int:
    flags, positionals = parse_argv(argv)

    if flags.get("--version"):
        sys.stdout.write(f"{PRODUCT} {VERSION}\n")
        return 0
    if flags.get("--help"):
        sys.stdout.write(HELP)
        return 0

    if not positionals:
        raise UsageError("missing subcommand")
    command = positionals[0]
    if command not in SUBCOMMANDS:
        raise UsageError(f"unknown subcommand: {command}")
    if len(positionals) > 2:
        raise UsageError("too many arguments")
    file_arg = positionals[1] if len(positionals) == 2 else None

    json_mode = bool(flags.get("--json"))
    strict = bool(flags.get("--strict"))
    quiet = bool(flags.get("--quiet"))

    forced_format = flags.get("--format", "auto")
    if forced_format not in ("auto", *FORMAT_PRIORITY):
        raise UsageError(f"invalid --format value: {forced_format}")

    top = 10
    n = 10
    by = None
    window_ms = 60000
    k = 2.0
    metric = "errors"
    out_path = None
    generated_at = None

    if command == "summary":
        top = _positive_int(flags, "--top", 10)
    elif command == "top":
        by = flags.get("--by")
        if by is None:
            raise UsageError("--by is required for top")
        if by not in TOP_FIELDS:
            raise UsageError(f"invalid --by value: {by}")
        n = _positive_int(flags, "--n", 10)
    elif command == "anomalies":
        window_ms = _duration_flag(flags, "--window", 60000)
        k = _float_flag(flags, "--k", 2.0)
        metric = flags.get("--metric", "errors")
        if metric not in METRICS:
            raise UsageError(f"invalid --metric value: {metric}")
    elif command == "report":
        if json_mode:
            raise UsageError("--json is not allowed with report")
        out_path = flags.get("--out")
        if out_path is None:
            raise UsageError("--out is required for report")
        top = _positive_int(flags, "--top", 10)
        window_ms = _duration_flag(flags, "--window", 60000)
        k = _float_flag(flags, "--k", 2.0)
        metric = flags.get("--metric", "errors")
        if metric not in METRICS:
            raise UsageError(f"invalid --metric value: {metric}")
        now_raw = flags.get("--now")
        if now_raw is not None:
            ms = parse_iso(now_raw)
            if ms is None:
                raise UsageError(f"invalid --now value: {now_raw}")
            generated_at = iso_utc(ms)

    text, source = read_source(file_arg)
    records, info = analyze(text, file_arg, source, forced_format)

    if info["lines_invalid"] > 0 and not quiet:
        sys.stderr.write(
            f"warning: {info['lines_invalid']} invalid line(s) skipped\n"
        )

    if command == "summary":
        if json_mode:
            emit_summary_json(records, info, top)
        else:
            emit_summary_text(records, info, top)
    elif command == "top":
        if json_mode:
            emit_top_json(records, info, by, n)
        else:
            emit_top_text(records, by, n)
    elif command == "anomalies":
        data = compute_anomalies(records, window_ms, k, metric)
        if json_mode:
            emit_anomalies_json(data, info)
        else:
            emit_anomalies_text(data)
    else:  # report
        data = compute_anomalies(records, window_ms, k, metric)
        content = build_report(
            records, info, top, data, generated_at or now_iso()
        )
        write_report(out_path, content)

    if strict and command != "report" and info["lines_invalid"] > 0:
        return 3
    if info["lines_valid"] == 0 and info["lines_total"] > 0:
        return 3
    return 0


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    try:
        return run(argv)
    except UsageError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 1
    except InputError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2
    except BrokenPipeError:  # pragma: no cover
        return 2
    except Exception as exc:  # pragma: no cover - erro interno inesperado
        sys.stderr.write(f"internal error: {exc}\n")
        return 4


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
