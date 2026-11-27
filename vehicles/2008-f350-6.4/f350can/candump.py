"""candump -L lines, matching the 2026 logs already in this repo.

Example::

    (1792947706.972675) can0 225#00FF00000000003D
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass

CAN_EFF_FLAG = 0x80000000
CAN_RTR_FLAG = 0x40000000
CAN_ERR_FLAG = 0x20000000
CAN_SFF_MASK = 0x7FF
CAN_EFF_MASK = 0x1FFFFFFF

# Classical CAN frame is 16 bytes: id, len, three pad bytes, 8 data bytes.
CAN_MTU = 16

_LINE = re.compile(
    r"^\((\d+)\.(\d+)\)\s+(\S+)\s+([0-9A-Fa-f]+)#([0-9A-Fa-f]*)\s*$"
)


@dataclass(frozen=True)
class CanFrame:
    ts: float
    can_id: int
    data: bytes
    eff: bool = False
    rtr: bool = False
    err: bool = False
    iface: str = ""


def format_candump_line(
    ts: float,
    iface: str,
    can_id: int,
    data: bytes,
    *,
    eff: bool = False,
    rtr: bool = False,
    err: bool = False,
) -> str:
    if ts < 0:
        raise ValueError("negative timestamp")
    sec = int(ts)
    usec = int(round((ts - sec) * 1_000_000))
    if usec >= 1_000_000:
        sec += 1
        usec -= 1_000_000
    if err:
        id_txt = f"{(can_id & CAN_EFF_MASK) | CAN_ERR_FLAG:08X}"
    elif eff:
        id_txt = f"{can_id & CAN_EFF_MASK:08X}"
    else:
        id_txt = f"{can_id & CAN_SFF_MASK:03X}"
    payload = "R" if rtr else data.hex().upper()
    return f"({sec}.{usec:06d}) {iface} {id_txt}#{payload}\n"


def parse_candump_line(line: str) -> CanFrame | None:
    raw = line.strip()
    if not raw or raw.startswith("#"):
        return None
    match = _LINE.match(raw)
    if not match:
        return None
    sec = int(match.group(1))
    usec_txt = match.group(2)[:6].ljust(6, "0")
    ts = sec + int(usec_txt) / 1_000_000
    iface = match.group(3)
    id_txt = match.group(4)
    data_txt = match.group(5)
    can_id = int(id_txt, 16)
    err = bool(can_id & CAN_ERR_FLAG)
    eff = (not err) and len(id_txt) > 3
    can_id = can_id & (CAN_EFF_MASK if (eff or err) else CAN_SFF_MASK)
    if len(data_txt) % 2:
        return None
    data = bytes.fromhex(data_txt) if data_txt else b""
    return CanFrame(ts=ts, can_id=can_id, data=data, eff=eff, err=err, iface=iface)


def parse_socket_frame(buf: bytes, ts: float, iface: str) -> CanFrame:
    """Unpack a Linux ``struct can_frame`` (16 bytes)."""
    if len(buf) < CAN_MTU:
        raise ValueError(f"short CAN frame ({len(buf)} bytes)")
    can_id, length = struct.unpack_from("<IB", buf)
    length &= 0xFF
    if length > 8:
        length = 8
    eff = bool(can_id & CAN_EFF_FLAG)
    rtr = bool(can_id & CAN_RTR_FLAG)
    err = bool(can_id & CAN_ERR_FLAG)
    ident = can_id & (CAN_EFF_MASK if (eff or err) else CAN_SFF_MASK)
    data = b"" if rtr else bytes(buf[8 : 8 + length])
    return CanFrame(
        ts=ts, can_id=ident, data=data, eff=eff, rtr=rtr, err=err, iface=iface
    )
