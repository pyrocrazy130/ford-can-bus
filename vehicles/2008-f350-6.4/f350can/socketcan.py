"""Read-only SocketCAN reader.

The socket is shut down for writing when the kernel allows it, loopback is
turned off, and this class has no send method. Listen-only mode on a real
controller is what actually guarantees the laptop cannot transmit; that is
checked before this socket is opened.
"""

from __future__ import annotations

import socket
import struct
import time

from f350can.candump import CAN_MTU, CanFrame, parse_socket_frame

# linux/can.h and linux/can/raw.h
SOL_CAN_RAW = 101
CAN_RAW_LOOPBACK = 3
CAN_RAW_RECV_OWN_MSGS = 4
# linux/asm-generic/socket.h. Python 3.14 dropped socket.SO_TIMESTAMP.
SO_TIMESTAMP_OLD = 29
SO_TIMESTAMP_NEW = 63
_TIMESTAMP_CTYPES = {SO_TIMESTAMP_OLD, SO_TIMESTAMP_NEW}
if hasattr(socket, "SO_TIMESTAMP"):
    _TIMESTAMP_CTYPES.add(socket.SO_TIMESTAMP)


class LinkDown(RuntimeError):
    """The interface went away while receiving."""


class SocketCanSource:
    def __init__(self, iface: str):
        self.iface = iface
        self.write_shutdown = False
        self._sock = socket.socket(socket.PF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
        try:
            self._sock.bind((iface,))
            try:
                self._sock.setsockopt(SOL_CAN_RAW, CAN_RAW_LOOPBACK, 0)
                self._sock.setsockopt(SOL_CAN_RAW, CAN_RAW_RECV_OWN_MSGS, 0)
            except OSError:
                pass
            for option in (SO_TIMESTAMP_OLD, SO_TIMESTAMP_NEW):
                try:
                    self._sock.setsockopt(socket.SOL_SOCKET, option, 1)
                    break
                except OSError:
                    continue
            try:
                self._sock.shutdown(socket.SHUT_WR)
                self.write_shutdown = True
            except OSError:
                # CAN raw sockets often reject SHUT_WR. The class still never
                # calls send(). Listen-only on the netdev is the real gate.
                self.write_shutdown = False
        except Exception:
            self._sock.close()
            raise

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass

    def recv(self, timeout: float) -> CanFrame | None:
        self._sock.settimeout(timeout)
        try:
            data, ancdata, _flags, _addr = self._sock.recvmsg(CAN_MTU, 256)
        except socket.timeout:
            return None
        except OSError as exc:
            # ENETDOWN, ENODEV, ENXIO, EBADF after close.
            if exc.errno in (9, 19, 100, 6) or self._sock.fileno() < 0:
                raise LinkDown(str(exc)) from exc
            raise
        if not data:
            raise LinkDown("empty read")
        ts = _timestamp_from_ancdata(ancdata) or time.time()
        return parse_socket_frame(data, ts, self.iface)


def _timestamp_from_ancdata(ancdata) -> float | None:
    for level, ctype, payload in ancdata:
        if level != socket.SOL_SOCKET or ctype not in _TIMESTAMP_CTYPES:
            continue
        if len(payload) >= 16:
            sec, usec = struct.unpack_from("qq", payload)
        elif len(payload) >= 8:
            sec, usec = struct.unpack_from("ii", payload)
        else:
            continue
        return float(sec) + float(usec) / 1_000_000.0
    return None
