"""Scrub VIN bytes before a log is committed to this public repo.

Known layouts (handled by tools/mask_vin.py):
  0x4FF chunked ASCII on the 2005 6.0
  0x40A mux C100/C101/C102 on the 2011 6.7
  ISO-TP Mode 09 PID 02 and DID F190 on 0x7E8/0x7E9

The 2008 6.4 broadcast VIN id is not known yet. A second pass masks a Ford
WMI (1FT / 1FD / 1FM / 2FT / ...) plus the following VIN-charset bytes in
that same frame when the run is at least 5 characters, which is how the 2005
chunks were split. Text notes are scanned for a full 17-character VIN.

The original VIN is not printed.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

from f350can.candump import format_candump_line, parse_candump_line
from f350can.redact import contains_vin, redact_text

_WMI = {prefix.upper() for prefix in ("1FT", "1FD", "1FM", "2FT", "2FD", "3FT", "3FD", "NM0", "WF0")}
_VIN_CHARS = set("ABCDEFGHJKLMNPRSTUVWXYZ0123456789")


def _mask_vin_module():
    path = Path(__file__).resolve().parents[3] / "tools" / "mask_vin.py"
    spec = importlib.util.spec_from_file_location("ford_mask_vin", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def mask_wmi_payload(data: bytes) -> tuple[bytes, int]:
    """Mask in-frame Ford WMI runs of at least 5 VIN characters."""
    buf = bytearray(data)
    masked = 0
    index = 0
    while index + 3 <= len(buf):
        try:
            prefix = bytes(buf[index : index + 3]).decode("ascii").upper()
        except UnicodeDecodeError:
            index += 1
            continue
        if prefix not in _WMI:
            index += 1
            continue
        end = index
        while end < len(buf):
            try:
                ch = bytes([buf[end]]).decode("ascii").upper()
            except UnicodeDecodeError:
                break
            if ch not in _VIN_CHARS:
                break
            end += 1
        if end - index >= 5:
            for pos in range(index, end):
                if buf[pos] != 0x58:
                    buf[pos] = 0x58
                    masked += 1
            index = end
        else:
            index += 1
    return bytes(buf), masked


def scrub_candump(src: Path, dst: Path) -> dict:
    module = _mask_vin_module()
    tmp = Path(str(dst) + ".pass1")
    module.mask_candump(str(src), str(tmp), quiet=True)
    frames = 0
    wmi_frames = 0
    wmi_bytes = 0
    out_lines: list[str] = []
    for line in tmp.read_text(encoding="latin-1").splitlines(True):
        parsed = parse_candump_line(line)
        if parsed is None:
            out_lines.append(line if line.endswith("\n") else line + "\n")
            continue
        frames += 1
        new_data, n = mask_wmi_payload(parsed.data)
        if n:
            wmi_frames += 1
            wmi_bytes += n
            out_lines.append(
                format_candump_line(
                    parsed.ts,
                    parsed.iface,
                    parsed.can_id,
                    new_data,
                    eff=parsed.eff,
                    err=parsed.err,
                )
            )
        else:
            out_lines.append(line if line.endswith("\n") else line + "\n")
    Path(dst).write_text("".join(out_lines), encoding="latin-1")
    tmp.unlink(missing_ok=True)
    return {"frames": frames, "wmi_frames": wmi_frames, "wmi_bytes": wmi_bytes}


def scrub_text(src: Path, dst: Path) -> dict:
    original = Path(src).read_text(encoding="utf-8", errors="replace")
    cleaned, count = redact_text(original)
    Path(dst).write_text(cleaned, encoding="utf-8")
    return {"vin_tokens": count}


def check_tree(path: Path) -> list[str]:
    """Return files that still contain a full 17-character Ford-style VIN."""
    target = Path(path)
    files = [target] if target.is_file() else [
        p for p in target.rglob("*") if p.is_file() and p.suffix.lower() in {
            ".log", ".txt", ".json", ".md", ".csv", ".dbc"
        }
    ]
    hits = []
    for file in files:
        try:
            text = file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if contains_vin(text):
            hits.append(str(file))
    return hits


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    candump = sub.add_parser("candump", help="scrub a candump -L log")
    candump.add_argument("src", type=Path)
    candump.add_argument("dst", type=Path)
    text = sub.add_parser("text", help="scrub VIN tokens in a text/JSON file")
    text.add_argument("src", type=Path)
    text.add_argument("dst", type=Path)
    check = sub.add_parser("check", help="exit 1 if a full VIN remains")
    check.add_argument("path", type=Path)
    args = parser.parse_args(argv)
    if args.cmd == "candump":
        stats = scrub_candump(args.src, args.dst)
        print(
            f"frames {stats['frames']}; extra WMI frames {stats['wmi_frames']}; "
            f"bytes masked {stats['wmi_bytes']}"
        )
        return 0
    if args.cmd == "text":
        stats = scrub_text(args.src, args.dst)
        print(f"vin tokens replaced {stats['vin_tokens']}")
        return 0
    hits = check_tree(args.path)
    if hits:
        print(f"VIN-like tokens still present in {len(hits)} file(s):", file=sys.stderr)
        for name in hits:
            print(name, file=sys.stderr)
        return 1
    print("no full VIN token found")
    return 0
