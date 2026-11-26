"""Session logger. Reads CAN, writes candump -L files, never transmits.

Real ``can`` interfaces must already be up, listen-only, and at the bitrate
selected in the UI. vcan is the only kind that may skip those checks, because
it has no wire and the kernel will not set listen-only on it.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from f350can import ALLOWED_BITRATES, TRANSMISSION, TZ_NAME, VEHICLE
from f350can.candump import format_candump_line
from f350can.iface import IfaceError, IfaceStatus, inspect_interface, validate_iface_name
from f350can.inhibit import SystemdInhibitor
from f350can.redact import redact_text
from f350can.socketcan import LinkDown, SocketCanSource

TZ = ZoneInfo(TZ_NAME)


class ListenOnlyError(RuntimeError):
    pass


class BitrateMismatch(RuntimeError):
    pass


class InterfaceNotUp(RuntimeError):
    pass


class SessionError(RuntimeError):
    pass


@dataclass
class _Segment:
    path: Path
    index: int
    start: str
    stop: str | None = None
    frames: int = 0
    listen_only: bool | None = None
    bitrate: int | None = None
    kind: str = ""
    state: str = ""


@dataclass
class _Chan:
    name: str
    bitrate: int
    stop_event: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None
    source: object | None = None
    file: object | None = None
    segment_index: int = 0
    frames: int = 0
    segment_frames: int = 0
    nbytes: int = 0
    ever_started: bool = False
    resume_pending: bool = False
    blocked: bool = False
    last_status: IfaceStatus | None = None
    tx_base: int = 0
    tx_warned: bool = False
    warnings: list = field(default_factory=list)
    segments: list = field(default_factory=list)
    rate_frames: int = 0
    rate_mono: float = 0.0
    fps: float = 0.0
    link_note: str = "idle"


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    return dt.astimezone(TZ).isoformat(timespec="milliseconds")


def safe_session_name(name: str) -> tuple[str, int]:
    cleaned, n = redact_text(name.strip())
    cleaned = cleaned.replace("\\", "-").replace("/", "-").replace("\x00", "")
    cleaned = " ".join(cleaned.split())
    if cleaned in {"", ".", ".."}:
        raise SessionError("session name is empty")
    if len(cleaned) > 120:
        cleaned = cleaned[:120].rstrip()
    return cleaned, n


def segment_path(directory: Path, session: str, iface: str, index: int) -> Path:
    if index <= 1:
        return directory / f"{session}_{iface}.log"
    return directory / f"{session}_{iface}_seg{index}.log"


class SessionEngine:
    def __init__(
        self,
        *,
        inspect=None,
        source_factory=None,
        inhibitor=None,
        log_root: Path | None = None,
        poll_s: float = 0.25,
    ):
        self.inspect = inspect or inspect_interface
        self.source_factory = source_factory or SocketCanSource
        self.inhibitor = inhibitor if inhibitor is not None else SystemdInhibitor()
        self.log_root = Path(log_root) if log_root is not None else Path.home() / "truck-logs"
        self.poll_s = poll_s
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._supervisor: threading.Thread | None = None
        self._channels: dict[str, _Chan] = {}
        self._session = ""
        self._notes = ""
        self._directory: Path | None = None
        self._json_path: Path | None = None
        self._markers_path: Path | None = None
        self._started: datetime | None = None
        self._stopped: datetime | None = None
        self._mono0 = 0.0
        self._markers: list[dict] = []
        self._warnings: list[str] = []
        self._vin_redactions = 0
        self._inhibit_warning: str | None = None
        self.running = False

    def start(self, session_name: str, channels: list[tuple[str, int]], notes: str = "") -> Path:
        if self.running:
            raise SessionError("already logging")
        if not channels:
            raise SessionError("enable at least one channel")
        session, redacted = safe_session_name(session_name)
        notes_r, notes_n = redact_text(notes)
        self._vin_redactions = redacted + notes_n
        seen = set()
        chans: dict[str, _Chan] = {}
        statuses: dict[str, IfaceStatus] = {}
        for name, bitrate in channels:
            try:
                validate_iface_name(name, allow_vcan=True)
            except IfaceError as exc:
                raise SessionError(str(exc)) from exc
            if name in seen:
                raise SessionError(f"duplicate channel {name}")
            seen.add(name)
            if bitrate not in ALLOWED_BITRATES:
                raise SessionError(
                    f"{name} bitrate {bitrate} is not allowed; use 125000 or 500000"
                )
            try:
                status = self.inspect(name)
            except IfaceError as exc:
                raise SessionError(str(exc)) from exc
            self._require_ready(name, bitrate, status)
            chans[name] = _Chan(name=name, bitrate=bitrate, last_status=status)
            statuses[name] = status

        now = datetime.now(TZ)
        directory = self.log_root / now.strftime("%Y-%m-%d")
        directory.mkdir(parents=True, exist_ok=True)
        session = self._unique_session(directory, session)
        self._session = session
        self._notes = notes_r
        self._directory = directory
        self._json_path = directory / f"{session}.json"
        self._markers_path = directory / f"{session}.markers.txt"
        self._markers_path.write_text("", encoding="utf-8")
        self._started = now
        self._stopped = None
        self._mono0 = time.monotonic()
        self._markers = []
        self._warnings = []
        if self._vin_redactions:
            self._warnings.append(
                "A VIN-like string was replaced with X in the session name or notes."
            )
        self._channels = chans
        self._stop.clear()
        inhibit_warning = self.inhibitor.start()
        self._inhibit_warning = inhibit_warning
        if inhibit_warning:
            self._warnings.append(inhibit_warning)
        try:
            for name, ch in chans.items():
                self._open_reader(ch, statuses[name], resume=False)
            self._write_metadata()
            self._supervisor = threading.Thread(
                target=self._loop, name="can-session", daemon=True
            )
            self.running = True
            self._supervisor.start()
        except Exception:
            self.running = False
            self._stop.set()
            self._stop_readers()
            self.inhibitor.stop()
            raise
        return self._json_path

    def mark(self, text: str) -> None:
        if not self.running:
            raise SessionError("not logging")
        cleaned, n = redact_text(text.strip())
        if not cleaned:
            raise SessionError("marker text is empty")
        now = datetime.now(TZ)
        row = {"wall": _iso(now), "epoch": time.time(), "text": cleaned}
        with self._lock:
            self._markers.append(row)
            if n:
                self._warnings.append(
                    "A VIN-like string was replaced with X in a marker."
                )
            path = self._markers_path
        assert path is not None
        with path.open("a", encoding="utf-8") as fh:
            fh.write(f"{row['wall']}\t{row['epoch']:.6f}\t{row['text']}\n")
            fh.flush()
            os.fsync(fh.fileno())
        self._write_metadata()

    def stop(self) -> None:
        if not self.running and self._supervisor is None and not self._channels:
            return
        self._stop.set()
        self.running = False
        thread = self._supervisor
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=3)
        self._stop_readers()
        self._stopped = datetime.now(TZ)
        try:
            self._write_metadata()
        finally:
            self.inhibitor.stop()
            self._supervisor = None

    def status(self) -> dict:
        with self._lock:
            now_m = time.monotonic()
            channels = {}
            for name, ch in self._channels.items():
                dt = now_m - ch.rate_mono
                if ch.rate_mono and dt >= 0.2:
                    ch.fps = (ch.frames - ch.rate_frames) / dt
                    ch.rate_frames = ch.frames
                    ch.rate_mono = now_m
                elif not ch.rate_mono:
                    ch.rate_mono = now_m
                    ch.rate_frames = ch.frames
                st = ch.last_status
                tx_delta = 0
                if st is not None:
                    tx_delta = max(0, st.tx_packets - ch.tx_base)
                channels[name] = {
                    "frames": ch.frames,
                    "frames_per_s": round(ch.fps, 1),
                    "bytes": ch.nbytes,
                    "segment": str(ch.segments[-1].path) if ch.segments else "",
                    "segment_index": ch.segment_index,
                    "state": st.state if st else "UNKNOWN",
                    "rx_errors": st.rx_errors if st else 0,
                    "tx_errors": st.tx_errors if st else 0,
                    "tx_delta": tx_delta,
                    "listen_only": None if st is None else st.listen_only,
                    "bitrate": None if st is None else st.bitrate,
                    "kind": "" if st is None else st.kind,
                    "link": ch.link_note,
                    "up": bool(st and st.is_up),
                }
            elapsed = (now_m - self._mono0) if self._mono0 else 0.0
            return {
                "running": self.running,
                "session": self._session,
                "directory": str(self._directory) if self._directory else "",
                "json": str(self._json_path) if self._json_path else "",
                "markers_file": str(self._markers_path) if self._markers_path else "",
                "elapsed_s": elapsed,
                "marker_count": len(self._markers),
                "warnings": list(self._warnings),
                "channels": channels,
                "inhibit_warning": self._inhibit_warning,
            }

    def _require_ready(self, name: str, bitrate: int, status: IfaceStatus) -> None:
        if not status.present or not status.is_up:
            raise InterfaceNotUp(
                f"{name} is down or missing. Use Bring up listen-only, then start. "
                "The logger will not configure the interface itself."
            )
        if status.kind == "vcan":
            return
        if status.kind != "can":
            raise SessionError(
                f"{name} is {status.kind or 'unknown'} rather than a CAN interface. "
                "Refusing to open it."
            )
        if not status.listen_only:
            raise ListenOnlyError(
                f"{name} is not in listen-only mode. Refusing to log. "
                "Run the bring-up helper so it sets listen-only on. "
                "This program will not transmit."
            )
        if status.bitrate != bitrate:
            raise BitrateMismatch(
                f"{name} is at {status.bitrate} bit/s, not the selected {bitrate}. "
                "Refusing to log. Use Bring up listen-only to set the bitrate."
            )

    def _acceptable(self, ch: _Chan, status: IfaceStatus) -> bool:
        try:
            self._require_ready(ch.name, ch.bitrate, status)
        except (InterfaceNotUp, ListenOnlyError, BitrateMismatch, SessionError):
            return False
        return True

    def _unique_session(self, directory: Path, session: str) -> str:
        candidate = session
        n = 2
        while (directory / f"{candidate}.json").exists():
            candidate = f"{session}-{n}"
            n += 1
        return candidate

    def _open_reader(self, ch: _Chan, status: IfaceStatus, *, resume: bool) -> None:
        assert self._directory is not None
        if resume:
            ch.segment_index += 1
        else:
            ch.segment_index = 1
        path = segment_path(self._directory, self._session, ch.name, ch.segment_index)
        fh = path.open("a", encoding="utf-8", newline="\n")
        seg = _Segment(
            path=path,
            index=ch.segment_index,
            start=_iso(datetime.now(TZ)),
            listen_only=status.listen_only,
            bitrate=status.bitrate,
            kind=status.kind,
            state=status.state,
        )
        ch.segments.append(seg)
        ch.file = fh
        ch.segment_frames = 0
        ch.stop_event = threading.Event()
        ch.source = self.source_factory(ch.name)
        ch.tx_base = status.tx_packets
        ch.ever_started = True
        ch.resume_pending = False
        ch.blocked = False
        ch.link_note = "logging"
        ch.last_status = status
        ch.thread = threading.Thread(
            target=self._reader, args=(ch,), name=f"can-{ch.name}", daemon=True
        )
        ch.thread.start()

    def _reader(self, ch: _Chan) -> None:
        assert ch.file is not None
        try:
            while not ch.stop_event.is_set() and not self._stop.is_set():
                assert ch.source is not None
                frame = ch.source.recv(0.4)
                if frame is None:
                    continue
                line = format_candump_line(
                    frame.ts,
                    ch.name,
                    frame.can_id,
                    frame.data,
                    eff=frame.eff,
                    rtr=frame.rtr,
                    err=frame.err,
                )
                ch.file.write(line)
                with self._lock:
                    ch.frames += 1
                    ch.segment_frames += 1
                    ch.nbytes += len(line.encode("utf-8"))
                    count = ch.segment_frames
                if count % 25 == 0:
                    ch.file.flush()
        except LinkDown:
            with self._lock:
                ch.link_note = "down"
                if "interface went down" not in ch.warnings:
                    ch.warnings.append("interface went down")
        except Exception as exc:
            with self._lock:
                ch.warnings.append(f"reader stopped: {exc}")
        finally:
            try:
                ch.file.flush()
                ch.file.close()
            except Exception:
                pass
            ch.file = None

    def _loop(self) -> None:
        while not self._stop.wait(self.poll_s):
            self._reconcile()

    def _reconcile(self) -> None:
        names = list(self._channels)
        for name in names:
            if self._stop.is_set():
                return
            try:
                status = self.inspect(name)
            except Exception as exc:
                with self._lock:
                    ch = self._channels.get(name)
                    if ch is not None:
                        ch.link_note = "inspect failed"
                        msg = f"{name}: {exc}"
                        if msg not in self._warnings:
                            self._warnings.append(msg)
                continue
            with self._lock:
                ch = self._channels.get(name)
                if ch is None:
                    continue
                ch.last_status = status
                self._note_tx(ch, status)
                alive = ch.thread is not None and ch.thread.is_alive()
                ok = bool(status.present and status.is_up and self._acceptable(ch, status))
                if alive and not ok:
                    reason = (
                        "link down"
                        if not (status.present and status.is_up)
                        else "interface left listen-only or changed bitrate"
                    )
                    self._retire_reader(ch, reason, want_resume=True)
                elif not alive and ch.ever_started and not ch.blocked:
                    if ch.segments and ch.segments[-1].stop is None:
                        ch.segments[-1].stop = _iso(datetime.now(TZ))
                        ch.segments[-1].frames = ch.segment_frames
                        ch.link_note = "down"
                        ch.resume_pending = not self._stop.is_set()
                        msg = f"{ch.name}: interface went down"
                        if msg not in self._warnings:
                            self._warnings.append(msg)
                        self._write_metadata_locked()
                    if ok and ch.resume_pending and not self._stop.is_set():
                        self._open_reader(ch, status, resume=True)
                        self._warnings.append(
                            f"{ch.name} came back; logging resumed in segment {ch.segment_index}"
                        )
                        self._write_metadata_locked()

    def _note_tx(self, ch: _Chan, status: IfaceStatus) -> None:
        delta = status.tx_packets - ch.tx_base
        if delta > 0 and not ch.tx_warned:
            ch.tx_warned = True
            self._warnings.append(
                f"{ch.name} transmit counter increased by {delta}. "
                "This logger does not send; another program may be transmitting."
            )

    def _retire_reader(self, ch: _Chan, reason: str, *, want_resume: bool) -> None:
        """Caller holds ``self._lock``. Joins the reader without deadlocking."""
        ch.stop_event.set()
        ch.link_note = "down" if "down" in reason else "stopped"
        src = ch.source
        thread = ch.thread
        self._lock.release()
        try:
            if src is not None:
                try:
                    src.close()
                except Exception:
                    pass
            if thread is not None:
                thread.join(timeout=2)
        finally:
            self._lock.acquire()
        ch.thread = None
        ch.source = None
        if ch.segments:
            ch.segments[-1].stop = _iso(datetime.now(TZ))
            ch.segments[-1].frames = ch.segment_frames
        msg = f"{ch.name}: {reason}"
        if msg not in ch.warnings:
            ch.warnings.append(msg)
        if msg not in self._warnings:
            self._warnings.append(msg)
        if "listen-only" in reason or "bitrate" in reason:
            ch.blocked = True
            ch.resume_pending = False
            self._warnings.append(
                f"{ch.name}: not resuming until it is listen-only at {ch.bitrate} bit/s again"
            )
        else:
            ch.resume_pending = want_resume and not self._stop.is_set()
        self._write_metadata_locked()

    def _stop_readers(self) -> None:
        with self._lock:
            chans = list(self._channels.values())
        for ch in chans:
            with self._lock:
                alive = ch.thread is not None and ch.thread.is_alive()
                if alive or ch.file is not None:
                    self._retire_reader(ch, "stopped", want_resume=False)
                elif ch.segments and ch.segments[-1].stop is None:
                    ch.segments[-1].stop = _iso(datetime.now(TZ))
                    ch.segments[-1].frames = ch.segment_frames

    def _write_metadata(self) -> None:
        with self._lock:
            self._write_metadata_locked()

    def _write_metadata_locked(self) -> None:
        if self._json_path is None or self._started is None or self._directory is None:
            return
        channels = {}
        for name, ch in self._channels.items():
            channels[name] = {
                "requested_bitrate": ch.bitrate,
                "segments": [
                    {
                        "path": str(seg.path),
                        "index": seg.index,
                        "start": seg.start,
                        "stop": seg.stop,
                        "frames": seg.frames if seg.stop else ch.segment_frames,
                        "listen_only": seg.listen_only,
                        "bitrate": seg.bitrate,
                        "kind": seg.kind,
                        "state": seg.state,
                    }
                    for seg in ch.segments
                ],
            }
        doc = {
            "format": 1,
            "tool": "f350can",
            "passive": True,
            "transmits": False,
            "vehicle": VEHICLE,
            "transmission": TRANSMISSION,
            "session": self._session,
            "timezone": TZ_NAME,
            "start": _iso(self._started),
            "stop": _iso(self._stopped) if self._stopped else None,
            "notes": self._notes,
            "log_dir": str(self._directory),
            "markers_file": str(self._markers_path) if self._markers_path else "",
            "sleep_inhibit": self._inhibit_warning is None,
            "sleep_inhibit_warning": self._inhibit_warning,
            "channels": channels,
            "markers": list(self._markers),
            "warnings": list(self._warnings),
        }
        tmp = self._json_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self._json_path)
