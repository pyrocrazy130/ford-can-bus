"""Propose CAN signal candidates by correlating a candump with a FORScan CSV.

FORScan columns are the known physical values (ECT, RPM, VSS, ...). Each
byte and each big-endian 16-bit field in each CAN id is compared with those
columns. A high Pearson r and a fitted scale/offset is a candidate, not a
confirmed signal. Write a DBC fragment only as a hypothesis file.
"""

from __future__ import annotations

import argparse
import bisect
import json
import math
from dataclasses import dataclass
from pathlib import Path

from f350can.candump import parse_candump_line
from f350can.forscan import load_forscan_csv


@dataclass(frozen=True)
class FieldSample:
    name: str
    start_bit: int
    length: int
    raw: int


def fields_of(data: bytes) -> list[FieldSample]:
    found: list[FieldSample] = []
    for index, byte in enumerate(data):
        found.append(FieldSample(f"b{index}", 8 * index + 7, 8, byte))
    for index in range(0, max(0, len(data) - 1)):
        raw = (data[index] << 8) | data[index + 1]
        found.append(FieldSample(f"be16@b{index}", 8 * index + 7, 16, raw))
    if len(data) >= 2:
        # 2005 6.0 RPM layout: low nibble of byte 0 plus byte 1. Tested as a
        # candidate shape, not assumed for the 2008.
        raw12 = ((data[0] & 0x0F) << 8) | data[1]
        found.append(FieldSample("be12_b0lo_b1", 3, 12, raw12))
    return found


@dataclass
class Candidate:
    pid: str
    can_id: int
    field: str
    start_bit: int
    length: int
    r: float
    scale: float
    offset: float
    n: int

    def as_dict(self) -> dict:
        return {
            "pid": self.pid,
            "can_id": self.can_id,
            "can_id_hex": f"{self.can_id:03X}",
            "field": self.field,
            "start_bit": self.start_bit,
            "length": self.length,
            "r": self.r,
            "scale": self.scale,
            "offset": self.offset,
            "n": self.n,
            "confidence": "hypothesis",
        }


def _fit(xs: list[float], ys: list[float]) -> tuple[float, float, float] | None:
    n = len(xs)
    if n < 2:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    if sxx <= 0 or syy <= 0:
        return None
    r = sxy / math.sqrt(sxx * syy)
    scale = sxy / sxx
    offset = my - scale * mx
    return r, scale, offset


def _load_can(path: Path, min_interval: float) -> dict[int, list[tuple[float, bytes]]]:
    series: dict[int, list[tuple[float, bytes]]] = {}
    last: dict[int, float] = {}
    with Path(path).open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            frame = parse_candump_line(line)
            if frame is None:
                continue
            prev = last.get(frame.can_id)
            if prev is not None and frame.ts - prev < min_interval:
                continue
            last[frame.can_id] = frame.ts
            series.setdefault(frame.can_id, []).append((frame.ts, frame.data))
    return series


def correlate(
    candump: Path,
    csv_path: Path,
    *,
    ref_offset: float,
    max_gap: float = 0.5,
    min_points: int = 8,
    min_interval: float = 0.0,
    top: int = 5,
) -> list[Candidate]:
    """``ref_offset`` is the Unix epoch of FORScan CSV t=0."""
    csv_series = load_forscan_csv(csv_path, start_epoch=ref_offset)
    epochs = [ref_offset + ms / 1000.0 for ms in csv_series.times_ms]
    can = _load_can(candump, min_interval)
    results: list[Candidate] = []
    for pid in csv_series.columns:
        column = csv_series.values[pid]
        for can_id, samples in can.items():
            buckets: dict[str, tuple[FieldSample, list[float], list[float]]] = {}
            for ts, data in samples:
                pos = bisect.bisect_left(epochs, ts)
                best_i = None
                best_gap = max_gap
                for probe in (pos - 1, pos):
                    if 0 <= probe < len(epochs):
                        gap = abs(epochs[probe] - ts)
                        if gap <= best_gap:
                            best_gap = gap
                            best_i = probe
                if best_i is None:
                    continue
                physical = column[best_i]
                if physical is None:
                    continue
                for field in fields_of(data):
                    slot = buckets.get(field.name)
                    if slot is None:
                        buckets[field.name] = (field, [float(field.raw)], [physical])
                    else:
                        slot[1].append(float(field.raw))
                        slot[2].append(physical)
            for field, xs, ys in buckets.values():
                if len(xs) < min_points:
                    continue
                fit = _fit(xs, ys)
                if fit is None:
                    continue
                r, scale, offset = fit
                results.append(
                    Candidate(
                        pid=pid,
                        can_id=can_id,
                        field=field.name,
                        start_bit=field.start_bit,
                        length=field.length,
                        r=r,
                        scale=scale,
                        offset=offset,
                        n=len(xs),
                    )
                )
    results.sort(key=lambda item: (item.pid, -abs(item.r), item.length, item.can_id))
    trimmed: list[Candidate] = []
    seen: dict[str, int] = {}
    for item in results:
        seen[item.pid] = seen.get(item.pid, 0) + 1
        if seen[item.pid] <= top:
            trimmed.append(item)
    return trimmed


def _dbc_number(value: float) -> str:
    if abs(value) < 1e-12:
        return "0"
    return f"{value:.8g}"


def write_hypothesis_dbc(path: Path, candidates: list[Candidate], *, min_r: float) -> int:
    """Write one hypothesis signal per PID. Returns how many were written."""
    chosen: dict[str, Candidate] = {}
    for item in candidates:
        if abs(item.r) < min_r:
            continue
        if item.pid not in chosen:
            chosen[item.pid] = item
    lines = [
        'VERSION "forscan_correlation_hypotheses"',
        "",
        "NS_ :",
        "\tCM_",
        "",
        "BS_:",
        "",
        "BU_:",
        "",
    ]
    # Group signals by CAN id. Signals in one message must not share a name.
    by_id: dict[int, list[Candidate]] = {}
    for item in chosen.values():
        by_id.setdefault(item.can_id, []).append(item)
    comments = []
    for can_id, items in sorted(by_id.items()):
        lines.append(f"BO_ {can_id} Hyp_{can_id:03X}: 8 Vector__XXX")
        for item in items:
            signame = "Hyp_" + re_safe(item.pid)
            lines.append(
                f" SG_ {signame} : {item.start_bit}|{item.length}@0+ "
                f"({_dbc_number(item.scale)},{_dbc_number(item.offset)}) "
                f"[0|0] \"\" Vector__XXX"
            )
            comments.append(
                f'CM_ SG_ {can_id} {signame} "[confidence=hypothesis] '
                f"[src=correlate_forscan field {item.field} r={item.r:.4f} "
                f"n={item.n} scale={item.scale:.6g} offset={item.offset:.6g}] "
                f'Candidate only. Confirm on a second capture before raising confidence.";'
            )
        lines.append("")
    lines.extend(comments)
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return len(chosen)


def re_safe(name: str) -> str:
    out = []
    for ch in name:
        if ch.isalnum():
            out.append(ch)
        elif ch in {".", "-"}:
            out.append("_")
    text = "".join(out).strip("_") or "signal"
    if text[0].isdigit():
        text = "P_" + text
    return text[:40]


def format_table(candidates: list[Candidate]) -> str:
    if not candidates:
        return "No candidate with enough paired samples. Check --ref-offset."
    lines = [
        f"{'PID':<16} {'ID':<6} {'field':<14} {'r':>7} {'scale':>12} {'offset':>10} {'n':>5}",
    ]
    for item in candidates:
        lines.append(
            f"{item.pid[:16]:<16} {item.can_id:03X}   {item.field:<14} "
            f"{item.r:7.3f} {item.scale:12.5g} {item.offset:10.3f} {item.n:5d}"
        )
    lines.append("")
    lines.append("These are hypotheses. Do not copy them into the vehicle DBC as confirmed.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candump", type=Path)
    parser.add_argument("csv", type=Path)
    parser.add_argument(
        "--ref-offset",
        type=float,
        required=True,
        help="Unix epoch of FORScan CSV t=0 (see match_forscan)",
    )
    parser.add_argument("--max-gap", type=float, default=0.5)
    parser.add_argument("--min-points", type=int, default=8)
    parser.add_argument("--min-interval", type=float, default=0.02)
    parser.add_argument("--top", type=int, default=5)
    parser.add_argument("--json", type=Path)
    parser.add_argument("--dbc-fragment", type=Path)
    parser.add_argument("--min-r", type=float, default=0.95)
    args = parser.parse_args(argv)
    found = correlate(
        args.candump,
        args.csv,
        ref_offset=args.ref_offset,
        max_gap=args.max_gap,
        min_points=args.min_points,
        min_interval=args.min_interval,
        top=args.top,
    )
    print(format_table(found))
    if args.json:
        args.json.write_text(
            json.dumps([item.as_dict() for item in found], indent=2) + "\n",
            encoding="utf-8",
        )
    if args.dbc_fragment:
        n = write_hypothesis_dbc(args.dbc_fragment, found, min_r=args.min_r)
        print(f"wrote {n} hypothesis signals to {args.dbc_fragment}")
    return 0
