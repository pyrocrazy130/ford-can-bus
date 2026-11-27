"""Read SocketCAN link state. Never changes it.

Listen-only and bitrate come from ``ip -details -json link``. A vcan
interface has no bitrate and cannot be placed in listen-only mode; callers
may treat kind ``vcan`` as the only exemption. A real ``can`` interface that
is not listen-only is not exempt, whatever its name is.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass

IFACE_RE = re.compile(r"^(?:can|vcan)\d+$")
REAL_CAN_RE = re.compile(r"^can\d+$")


class IfaceError(RuntimeError):
    pass


@dataclass(frozen=True)
class IfaceStatus:
    name: str
    present: bool
    kind: str
    is_up: bool
    listen_only: bool
    bitrate: int | None
    state: str
    rx_errors: int
    tx_errors: int
    tx_packets: int
    rx_packets: int

    @staticmethod
    def missing(name: str) -> "IfaceStatus":
        return IfaceStatus(
            name=name,
            present=False,
            kind="",
            is_up=False,
            listen_only=False,
            bitrate=None,
            state="MISSING",
            rx_errors=0,
            tx_errors=0,
            tx_packets=0,
            rx_packets=0,
        )


def validate_iface_name(name: str, *, allow_vcan: bool = True) -> str:
    pattern = IFACE_RE if allow_vcan else REAL_CAN_RE
    if not pattern.fullmatch(name):
        kind = "canN or vcanN" if allow_vcan else "canN"
        raise IfaceError(
            f"refusing interface {name!r}; only {kind} is accepted "
            "(this tool does not open serial devices such as the OBDLink EX)"
        )
    return name


def _tokens(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        parts = value.replace(",", " ").split()
        return [p.strip().upper() for p in parts if p.strip()]
    if isinstance(value, (list, tuple)):
        return [str(p).strip().upper() for p in value]
    return [str(value).strip().upper()]


def _int(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _counter(block, key: str) -> int:
    if not isinstance(block, dict):
        return 0
    return _int(block.get(key)) or 0


def parse_ip_link_json(blob: str, ifname: str) -> IfaceStatus:
    """Parse ``ip -details -statistics -json link show dev IFACE``."""
    text = blob.strip()
    if not text:
        return IfaceStatus.missing(ifname)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise IfaceError(f"ip returned non-JSON for {ifname}: {exc}") from exc
    entries = data if isinstance(data, list) else [data]
    entry = None
    for item in entries:
        if isinstance(item, dict) and item.get("ifname") == ifname:
            entry = item
            break
    if entry is None and len(entries) == 1 and isinstance(entries[0], dict):
        entry = entries[0]
    if not isinstance(entry, dict):
        return IfaceStatus.missing(ifname)

    flags = [str(f).upper() for f in entry.get("flags") or []]
    oper = str(entry.get("operstate") or "").upper()
    linkinfo = entry.get("linkinfo") or {}
    kind = str(linkinfo.get("info_kind") or "")
    info = linkinfo.get("info_data") or {}
    if not isinstance(info, dict):
        info = {}
    bittiming = info.get("bittiming") or {}
    if not isinstance(bittiming, dict):
        bittiming = {}
    bitrate = _int(bittiming.get("bitrate"))
    ctrl = _tokens(info.get("ctrlmode"))
    listen_only = any(tok.replace("_", "-") == "LISTEN-ONLY" for tok in ctrl)
    state = str(info.get("state") or oper or "UNKNOWN")
    berr = info.get("berr_counter") or {}
    stats = entry.get("stats64") or entry.get("stats") or {}
    rx = stats.get("rx") if isinstance(stats, dict) else {}
    tx = stats.get("tx") if isinstance(stats, dict) else {}
    down_oper = oper in {"DOWN", "LOWERLAYERDOWN", "NOTPRESENT", "DORMANT"}
    is_up = ("UP" in flags) and not down_oper and oper != "DOWN"
    rx_errors = _counter(rx, "errors")
    if isinstance(berr, dict) and _int(berr.get("rx")):
        # Controller receive error counter, shown in addition to stack errors.
        rx_errors = max(rx_errors, _int(berr.get("rx")) or 0)
    tx_errors = _counter(tx, "errors")
    if isinstance(berr, dict) and _int(berr.get("tx")):
        tx_errors = max(tx_errors, _int(berr.get("tx")) or 0)
    return IfaceStatus(
        name=str(entry.get("ifname") or ifname),
        present=True,
        kind=kind,
        is_up=is_up,
        listen_only=listen_only,
        bitrate=bitrate,
        state=state,
        rx_errors=rx_errors,
        tx_errors=tx_errors,
        tx_packets=_counter(tx, "packets"),
        rx_packets=_counter(rx, "packets"),
    )


def inspect_interface(name: str, runner=None) -> IfaceStatus:
    """Query one interface. ``runner`` is subprocess.run by default."""
    validate_iface_name(name, allow_vcan=True)
    run = runner or subprocess.run
    try:
        proc = run(
            ["ip", "-details", "-statistics", "-json", "link", "show", "dev", name],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise IfaceError("ip(8) is not installed; cannot verify listen-only mode") from exc
    if proc.returncode != 0:
        err = (proc.stderr or "").strip()
        if "does not exist" in err or "not exist" in err or proc.returncode == 1:
            return IfaceStatus.missing(name)
        raise IfaceError(err or f"ip link show {name} failed")
    return parse_ip_link_json(proc.stdout or "", name)
