"""Redact Ford VIN strings before they land in a public file.

A full 17-character VIN is replaced in session names, notes, and markers.
Frame scrubbing for unknown VIN-bearing IDs lives in scrub.py. This module
never logs the original value.
"""

from __future__ import annotations

import re

# Ford light-truck / Ford world manufacturer prefixes seen on Super Duty
# buses in this repo and in public Ford docs. Not a complete WMI list.
_WMI = r"(?:1F[TDM]|2F[TD]|3F[TD]|NM0|WF0)"
_VIN = re.compile(
    rf"(?<![A-HJ-NPR-Z0-9]){_WMI}[A-HJ-NPR-Z0-9]{{14}}(?![A-HJ-NPR-Z0-9])",
    re.IGNORECASE,
)


def redact_text(text: str) -> tuple[str, int]:
    """Replace full VIN tokens with 17 X characters. Returns (text, count)."""
    count = 0

    def repl(match: re.Match[str]) -> str:
        nonlocal count
        count += 1
        return "X" * 17

    return _VIN.sub(repl, text), count


def contains_vin(text: str) -> bool:
    return _VIN.search(text) is not None
