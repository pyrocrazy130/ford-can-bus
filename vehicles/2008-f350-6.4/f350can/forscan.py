"""FORScan CSV timing and overlap with CAN session metadata.

FORScan ``time(ms)`` is relative to when the CSV recording started, not wall
clock. This helper estimates that start from the filename when it contains a
clock time, otherwise from file mtime minus the CSV duration (mtime is usually
when the log was closed). That estimate is approximate. The 2005 captures in
this repo needed a hand-checked ref-offset; use the suggested value as a
starting point for correlate_forscan, then confirm against RPM.
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from f350can import TZ_NAME

TZ = ZoneInfo(TZ_NAME)

_FILENAME_CLOCKS = (
    "%m-%d-%Y %I-%M-%S %p",
    "%m-%d-%Y %I.%M.%S %p",
    "%m-%d-%Y %H-%M-%S",
    "%Y-%m-%d %H-%M-%S",
    "%Y-%m-%d_%H-%M-%S",
    "%Y%m%d_%H%M%S",
    "%Y%m%d-%H%M%S",
)


@dataclass
class CsvSeries:
    path: Path
    columns: list[str]
    times_ms: list[float]
    values: dict[str, list[float | None]]
    duration_s: float
    start_epoch: float
    end_epoch: float
    start_source: str


def _delimiter(header_line: str) -> str:
    if header_line.count(";") >= header_line.count(","):
        return ";"
    return ","


def _numeric(text: str) -> float | None:
    raw = text.strip()
    if raw in {"", "-", "—", "–"}:
        return None
    raw = raw.replace(",", "") if raw.count(",") > 1 else raw
    try:
        return float(raw)
    except ValueError:
        return None


def filename_start_epoch(path: Path) -> float | None:
    stem = path.stem.replace("_", " ")
    for fmt in _FILENAME_CLOCKS:
        try:
            dt = datetime.strptime(stem, fmt)
        except ValueError:
            continue
        return dt.replace(tzinfo=TZ).timestamp()
    # A date plus a clock buried in a longer name: "11-26-2026 2008 F350 2-15-00 PM"
    match = re.search(
        r"(\d{1,2}-\d{1,2}-\d{4})\s+(\d{1,2})[:.\-](\d{2})[:.\-](\d{2})\s*([AaPp][Mm])?",
        path.stem,
    )
    if not match:
        return None
    month, day, year = (int(p) for p in match.group(1).split("-"))
    hour, minute, second = (int(match.group(i)) for i in (2, 3, 4))
    ampm = match.group(5)
    if ampm:
        ampm = ampm.lower()
        hour = hour % 12
        if ampm == "pm":
            hour += 12
    try:
        dt = datetime(year, month, day, hour, minute, second, tzinfo=TZ)
    except ValueError:
        return None
    return dt.timestamp()


def load_forscan_csv(path: Path, *, start_epoch: float | None = None) -> CsvSeries:
    raw = Path(path).read_text(encoding="utf-8", errors="replace")
    lines = raw.splitlines()
    if not lines:
        raise ValueError(f"{path} is empty")
    delim = _delimiter(lines[0])
    rows = list(csv.reader(lines, delimiter=delim))
    header = [h.strip() for h in rows[0]]
    if not header:
        raise ValueError(f"{path} has no header")
    columns = header[1:]
    times: list[float] = []
    values: dict[str, list[float | None]] = {col: [] for col in columns}
    for row in rows[1:]:
        if not row or not row[0].strip():
            continue
        t = _numeric(row[0])
        if t is None:
            continue
        times.append(t)
        for idx, col in enumerate(columns):
            cell = row[idx + 1] if idx + 1 < len(row) else ""
            values[col].append(_numeric(cell))
    duration_s = (times[-1] / 1000.0) if times else 0.0
    source = "argument"
    if start_epoch is None:
        named = filename_start_epoch(Path(path))
        if named is not None:
            start_epoch = named
            source = "filename"
        else:
            end = Path(path).stat().st_mtime
            start_epoch = end - duration_s
            source = "mtime minus duration"
    return CsvSeries(
        path=Path(path),
        columns=columns,
        times_ms=times,
        values=values,
        duration_s=duration_s,
        start_epoch=start_epoch,
        end_epoch=start_epoch + duration_s,
        start_source=source,
    )


@dataclass
class Overlap:
    session_json: Path
    session: str
    overlap_s: float
    session_start: float
    session_stop: float
    csv_start: float
    csv_end: float
    csv_start_source: str
    suggested_ref_offset: float


def _session_bounds(doc: dict) -> tuple[float, float, str] | None:
    start = doc.get("start")
    stop = doc.get("stop")
    if not start or not stop:
        return None
    try:
        a = datetime.fromisoformat(start).timestamp()
        b = datetime.fromisoformat(stop).timestamp()
    except ValueError:
        return None
    if b < a:
        return None
    return a, b, str(doc.get("session") or "")


def find_overlapping_sessions(csv_path: Path, log_root: Path) -> list[Overlap]:
    series = load_forscan_csv(csv_path)
    found: list[Overlap] = []
    root = Path(log_root)
    if not root.exists():
        return []
    for path in sorted(root.rglob("*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(doc, dict) or "start" not in doc:
            continue
        bounds = _session_bounds(doc)
        if bounds is None:
            continue
        a, b, name = bounds
        overlap = min(b, series.end_epoch) - max(a, series.start_epoch)
        if overlap <= 0:
            continue
        found.append(
            Overlap(
                session_json=path,
                session=name,
                overlap_s=overlap,
                session_start=a,
                session_stop=b,
                csv_start=series.start_epoch,
                csv_end=series.end_epoch,
                csv_start_source=series.start_source,
                suggested_ref_offset=series.start_epoch,
            )
        )
    found.sort(key=lambda item: item.overlap_s, reverse=True)
    return found


def format_overlaps(csv_path: Path, matches: list[Overlap]) -> str:
    if not matches:
        return (
            f"No CAN session under the log folder overlaps {csv_path.name}. "
            "FORScan time is relative; this match uses filename clock or "
            "mtime minus duration, which can be off by the time the file sat open."
        )
    lines = [
        f"{csv_path.name}: CSV t=0 estimated from {matches[0].csv_start_source}.",
        "Suggested correlate --ref-offset is that CSV start (epoch seconds).",
        "Confirm it against RPM before trusting a candidate signal.",
        "",
    ]
    for item in matches:
        lines.append(
            f"{item.overlap_s:.1f}s overlap  {item.session}  {item.session_json}"
        )
        lines.append(f"    --ref-offset {item.suggested_ref_offset:.3f}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Find a CAN session whose wall clock overlaps a FORScan CSV."
    )
    parser.add_argument("csv", type=Path)
    parser.add_argument(
        "--log-root",
        type=Path,
        default=Path.home() / "truck-logs",
        help="Session tree (default ~/truck-logs)",
    )
    args = parser.parse_args(argv)
    matches = find_overlapping_sessions(args.csv, args.log_root)
    print(format_overlaps(args.csv, matches))
    return 0 if matches else 1
