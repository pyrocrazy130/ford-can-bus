"""Launch the logger window, or a headless capture with --headless."""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import argparse
import time

from f350can.engine import SessionEngine


HELP = """\
2008 F-350 passive CAN logger

  python3 -m f350can
      open the desktop window (normal user, not root)

  python3 -m f350can --headless --channel can0=500000 --channel can1=125000 \\
      --session "11-26-2026 2008 F350 grade"

Bring-up (root) is a separate helper. See vehicles/2008-f350-6.4/README.md.
"""


def headless(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="f350can --headless")
    parser.add_argument("--session", required=True)
    parser.add_argument("--channel", action="append", required=True, help="can0=500000")
    parser.add_argument("--notes", default="")
    parser.add_argument("--log-root", type=Path, default=Path.home() / "truck-logs")
    parser.add_argument("--duration", type=float, default=0, help="seconds, then stop")
    args = parser.parse_args(argv)
    channels = []
    for spec in args.channel:
        name, _, rate = spec.partition("=")
        if not rate:
            parser.error(f"channel must look like can0=500000, got {spec}")
        channels.append((name, int(rate)))
    engine = SessionEngine(log_root=args.log_root)
    path = engine.start(args.session, channels, notes=args.notes)
    print(path)
    try:
        if args.duration > 0:
            time.sleep(args.duration)
        else:
            print("logging; Ctrl-C to stop", file=sys.stderr)
            while True:
                time.sleep(1)
                snap = engine.status()
                parts = [
                    f"{name} {ch['frames_per_s']:.0f}fr/s {ch['state']}"
                    for name, ch in snap["channels"].items()
                ]
                print(
                    f"{snap['elapsed_s']:.0f}s  " + "  ".join(parts),
                    file=sys.stderr,
                )
    except KeyboardInterrupt:
        pass
    finally:
        engine.stop()
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in {"-h", "--help"}:
        if argv and argv[0] in {"-h", "--help"}:
            print(HELP)
            return 0
    if argv and argv[0] == "--headless":
        return headless(argv[1:])
    if argv:
        print(HELP, file=sys.stderr)
        return 2
    try:
        from f350can.ui import run
    except ModuleNotFoundError as exc:
        print(
            "tkinter is not installed. Install python3-tk, or run with --headless.\n"
            f"({exc})",
            file=sys.stderr,
        )
        return 1
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
