"""Per-id rates and which bytes change in a candump -L log."""

from __future__ import annotations

import argparse
import json
import statistics
from dataclasses import dataclass, field
from pathlib import Path

from f350can.candump import parse_candump_line


@dataclass
class IdStat:
    can_id: int
    count: int = 0
    first_ts: float = 0.0
    last_ts: float = 0.0
    dlc: set[int] = field(default_factory=set)
    last: bytes = b""
    changed: set[int] = field(default_factory=set)
    gaps: list[float] = field(default_factory=list)
    _prev_ts: float | None = None
    _baseline: bytes | None = None

    def add(self, ts: float, data: bytes) -> None:
        if self.count == 0:
            self.first_ts = ts
            self._baseline = data
        else:
            assert self._baseline is not None
            width = min(len(self._baseline), len(data))
            for index in range(width):
                if data[index] != self._baseline[index]:
                    self.changed.add(index)
            if self._prev_ts is not None and len(self.gaps) < 4000:
                gap = ts - self._prev_ts
                if gap >= 0:
                    self.gaps.append(gap)
        self.count += 1
        self.last_ts = ts
        self._prev_ts = ts
        self.last = data
        self.dlc.add(len(data))

    def as_dict(self) -> dict:
        span = self.last_ts - self.first_ts
        hz = (self.count - 1) / span if span > 0 and self.count > 1 else 0.0
        period_ms = statistics.median(self.gaps) * 1000 if self.gaps else None
        return {
            "id": self.can_id,
            "id_hex": f"{self.can_id:03X}",
            "count": self.count,
            "hz": hz,
            "period_ms": period_ms,
            "dlc": sorted(self.dlc),
            "changing_bytes": sorted(self.changed),
            "example": self.last.hex().upper(),
        }


def summarize(path: Path) -> list[IdStat]:
    stats: dict[int, IdStat] = {}
    with Path(path).open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            frame = parse_candump_line(line)
            if frame is None:
                continue
            slot = stats.get(frame.can_id)
            if slot is None:
                slot = IdStat(can_id=frame.can_id)
                stats[frame.can_id] = slot
            slot.add(frame.ts, frame.data)
    return [stats[key] for key in sorted(stats)]


def format_table(rows: list[IdStat]) -> str:
    header = f"{'ID':<8} {'count':>8} {'Hz':>8} {'period_ms':>10} {'dlc':<8} {'changing':<16} example"
    lines = [header]
    for row in rows:
        item = row.as_dict()
        period = "-" if item["period_ms"] is None else f"{item['period_ms']:.2f}"
        changing = ",".join(f"b{i}" for i in item["changing_bytes"]) or "-"
        dlc = ",".join(str(n) for n in item["dlc"])
        lines.append(
            f"{item['id_hex']:<8} {item['count']:8d} {item['hz']:8.2f} {period:>10} "
            f"{dlc:<8} {changing:<16} {item['example']}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("logs", nargs="+", type=Path)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    combined: list[dict] = []
    for path in args.logs:
        rows = summarize(path)
        print(f"# {path}")
        print(format_table(rows))
        print()
        combined.append({"file": str(path), "ids": [row.as_dict() for row in rows]})
    if args.json:
        args.json.write_text(json.dumps(combined, indent=2) + "\n", encoding="utf-8")
    return 0
