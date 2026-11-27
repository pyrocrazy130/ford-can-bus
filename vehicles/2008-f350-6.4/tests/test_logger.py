"""Logger engine, candump format, link checks, and the desktop window."""

import json
import queue
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from f350can.candump import format_candump_line, parse_candump_line, parse_socket_frame
from f350can.engine import (
    BitrateMismatch,
    InterfaceNotUp,
    ListenOnlyError,
    SessionEngine,
    SessionError,
)
from f350can.iface import IfaceStatus, parse_ip_link_json
from f350can.inhibit import INHIBIT_ARGV
from f350can.socketcan import LinkDown
import struct


def _status(name, *, kind, up=True, listen=False, bitrate=None, present=True, tx=0, state="ERROR-ACTIVE"):
    return IfaceStatus(
        name=name,
        present=present,
        kind=kind,
        is_up=up,
        listen_only=listen,
        bitrate=bitrate,
        state=state if up else "DOWN",
        rx_errors=0,
        tx_errors=0,
        tx_packets=tx,
        rx_packets=0,
    )


class QueueSource:
    def __init__(self):
        self.q = queue.Queue()
        self.closed = False

    def recv(self, timeout):
        if self.closed:
            raise LinkDown("closed")
        try:
            item = self.q.get(timeout=timeout)
        except queue.Empty:
            return None
        if item is None or self.closed:
            raise LinkDown("closed")
        return item

    def close(self):
        self.closed = True
        self.q.put(None)


class FakeInhibit:
    def __init__(self):
        self.started = 0
        self.stopped = 0

    def start(self):
        self.started += 1
        return None

    def stop(self):
        self.stopped += 1


def _frame(can_id, data, ts=1_700_000_000.5):
    from f350can.candump import CanFrame

    return CanFrame(ts=ts, can_id=can_id, data=data)


def _engine(tmp_path, inspect, sources):
    def factory(name):
        src = QueueSource()
        sources.setdefault(name, []).append(src)
        return src

    inhibit = FakeInhibit()
    engine = SessionEngine(
        inspect=inspect,
        source_factory=factory,
        inhibitor=inhibit,
        log_root=tmp_path,
        poll_s=0.05,
    )
    return engine, inhibit


def _wait(pred, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.02)
    return False


def test_candump_line_matches_repo_style():
    ts = 1792947706 + 972675 / 1_000_000
    line = format_candump_line(ts, "can0", 0x225, bytes.fromhex("00FF00000000003D"))
    assert line == "(1792947706.972675) can0 225#00FF00000000003D\n"
    parsed = parse_candump_line(line)
    assert parsed is not None
    assert parsed.can_id == 0x225
    assert parsed.data.hex().upper() == "00FF00000000003D"


def test_kernel_timestamp_option_does_not_need_socket_SO_TIMESTAMP():
    import socket
    import struct

    from f350can.socketcan import SO_TIMESTAMP_OLD, _timestamp_from_ancdata

    payload = struct.pack("qq", 1_700_000_000, 123456)
    ts = _timestamp_from_ancdata([(socket.SOL_SOCKET, SO_TIMESTAMP_OLD, payload)])
    assert ts == pytest.approx(1_700_000_000.123456)
    assert SO_TIMESTAMP_OLD == 29


def test_parse_socket_frame_layout():
    raw = struct.pack("<IB3x8s", 0x201, 4, bytes.fromhex("aabbccdd") + b"\x00" * 4)
    frame = parse_socket_frame(raw, 10.5, "can0")
    assert frame.can_id == 0x201
    assert frame.data == bytes.fromhex("aabbccdd")


def test_refuses_real_can_that_is_not_listen_only(tmp_path):
    def inspect(name):
        return _status(name, kind="can", listen=False, bitrate=500000)

    engine, inhibit = _engine(tmp_path, inspect, {})
    with pytest.raises(ListenOnlyError):
        engine.start("11-26-2026 2008 F350 grade", [("can0", 500000)])
    assert inhibit.started == 0
    assert list(tmp_path.rglob("*.log")) == []


def test_refuses_bitrate_mismatch_and_down_and_odd_names(tmp_path):
    def inspect(name):
        return _status(name, kind="can", listen=True, bitrate=500000)

    engine, _ = _engine(tmp_path, inspect, {})
    with pytest.raises(BitrateMismatch):
        engine.start("s", [("can0", 125000)])

    def down(_name):
        return _status("can0", kind="can", up=False, listen=True, bitrate=500000)

    engine, _ = _engine(tmp_path, down, {})
    with pytest.raises(InterfaceNotUp):
        engine.start("s", [("can0", 500000)])

    engine, _ = _engine(tmp_path, inspect, {})
    with pytest.raises(SessionError):
        engine.start("s", [("ttyUSB0", 500000)])
    with pytest.raises(SessionError):
        engine.start("s", [("obdlink0", 500000)])


def test_vcan_does_not_need_listen_only_and_records_session(tmp_path):
    def inspect(name):
        return _status(name, kind="vcan", listen=False, bitrate=None)

    sources = {}
    engine, inhibit = _engine(tmp_path, inspect, sources)
    fake_vin = "1FT" + "SW00X00X000000"
    path = engine.start(
        "11-26-2026 2008 F350 grade",
        [("vcan0", 500000)],
        notes="tow " + fake_vin,
    )
    sources["vcan0"][0].q.put(_frame(0x201, bytes.fromhex("0102030405060708")))
    assert _wait(lambda: engine.status()["channels"]["vcan0"]["frames"] >= 1)
    engine.mark("start of grade")
    engine.stop()
    assert inhibit.started == 1 and inhibit.stopped == 1
    text = path.read_text(encoding="utf-8")
    doc = json.loads(text)
    assert doc["timezone"] == "America/Los_Angeles"
    assert doc["passive"] is True and doc["transmits"] is False
    start = datetime.fromisoformat(doc["start"])
    assert start.tzinfo is not None
    assert start.utcoffset() == datetime.now(ZoneInfo("America/Los_Angeles")).utcoffset()
    assert doc["stop"]
    assert fake_vin not in text
    assert "XXXX" in doc["notes"]
    log = next(path.parent.glob("*_vcan0.log"))
    body = log.read_text(encoding="utf-8")
    assert "vcan0 201#0102030405060708" in body
    markers = (path.parent / f"{doc['session']}.markers.txt").read_text(encoding="utf-8")
    assert "start of grade" in markers
    assert doc["channels"]["vcan0"]["segments"][0]["listen_only"] is False
    assert doc["channels"]["vcan0"]["segments"][0]["kind"] == "vcan"


def test_resumes_into_a_new_segment_when_the_link_returns(tmp_path):
    state = {"up": True}

    def inspect(name):
        return _status(name, kind="vcan", up=state["up"])

    sources = {}
    engine, _ = _engine(tmp_path, inspect, sources)
    engine.start("11-26-2026 2008 F350 grade", [("vcan0", 500000)])
    sources["vcan0"][0].q.put(_frame(0x201, b"\x01" * 8, ts=10.0))
    assert _wait(lambda: engine.status()["channels"]["vcan0"]["frames"] >= 1)
    state["up"] = False
    sources["vcan0"][0].close()
    assert _wait(lambda: "came back" not in " ".join(engine.status()["warnings"]) and any(
        "down" in w for w in engine.status()["warnings"]
    ))
    state["up"] = True
    assert _wait(lambda: len(sources["vcan0"]) >= 2)
    sources["vcan0"][-1].q.put(_frame(0x420, b"\x02" * 8, ts=20.0))
    assert _wait(lambda: engine.status()["channels"]["vcan0"]["segment_index"] >= 2)
    assert _wait(lambda: engine.status()["channels"]["vcan0"]["frames"] >= 2)
    engine.stop()
    logs = sorted(p.name for p in tmp_path.rglob("*.log"))
    assert any(name.endswith("_vcan0.log") for name in logs)
    assert any("_vcan0_seg2.log" in name for name in logs)
    seg2 = next(tmp_path.rglob("*_vcan0_seg2.log"))
    assert "420#0202020202020202" in seg2.read_text(encoding="utf-8")


def test_ip_json_listen_only_and_vcan():
    can = """
    [{
      "ifname": "can0",
      "flags": ["NOARP", "UP", "LOWER_UP"],
      "operstate": "UP",
      "linkinfo": {
        "info_kind": "can",
        "info_data": {
          "state": "ERROR-ACTIVE",
          "bittiming": {"bitrate": 500000},
          "ctrlmode": ["LISTEN-ONLY"],
          "berr_counter": {"tx": 0, "rx": 2}
        }
      },
      "stats64": {"rx": {"packets": 10, "errors": 1}, "tx": {"packets": 0, "errors": 0}}
    }]
    """
    status = parse_ip_link_json(can, "can0")
    assert status.kind == "can"
    assert status.is_up and status.listen_only
    assert status.bitrate == 500000
    assert status.state == "ERROR-ACTIVE"
    assert status.rx_errors == 2
    assert status.tx_packets == 0

    plain = parse_ip_link_json(
        '[{"ifname":"can1","flags":["NOARP","UP"],"operstate":"UP",'
        '"linkinfo":{"info_kind":"can","info_data":{"bittiming":{"bitrate":125000},"ctrlmode":""}}}]',
        "can1",
    )
    assert plain.listen_only is False
    assert plain.bitrate == 125000

    vcan = parse_ip_link_json(
        '[{"ifname":"vcan0","flags":["UP"],"operstate":"UNKNOWN","linkinfo":{"info_kind":"vcan"}}]',
        "vcan0",
    )
    assert vcan.kind == "vcan" and vcan.is_up and not vcan.listen_only


def test_bringup_uses_sudo_n_until_polkit_policy_exists():
    from f350can.ui import helper_command, prefer_pkexec
    from pathlib import Path

    assert prefer_pkexec() is False
    cmd = helper_command([("can0", 500000), ("can1", 125000)], Path("/usr/local/sbin/can-listen-only-up"), use_pkexec=False)
    assert cmd[:3] == ["sudo", "-n", "/usr/local/sbin/can-listen-only-up"]
    assert cmd[3:] == ["can0=500000", "can1=125000"]
    pk = helper_command([("can0", 500000)], Path("/usr/local/sbin/can-listen-only-up"), use_pkexec=True)
    assert pk[0] == "pkexec"


def test_inhibit_command_covers_sleep_and_lid():
    text = " ".join(INHIBIT_ARGV)
    assert "sleep" in text
    assert "handle-lid-switch" in text
    assert "idle" in text


def test_package_never_sends():
    root = Path(__file__).resolve().parents[1] / "f350can"
    blob = "\n".join(path.read_text(encoding="utf-8") for path in root.glob("*.py"))
    assert ".send(" not in blob
    assert "cansend" not in blob
    assert "cangen" not in blob


def test_ui_start_mark_stop(tmp_path):
    pytest.importorskip("tkinter")
    import os
    import tkinter as tk

    if not os.environ.get("DISPLAY"):
        pytest.skip("no DISPLAY")
    from f350can.ui import LoggerApp

    def inspect(name):
        return _status(name, kind="vcan")

    sources = {}
    engine, _inhibit = _engine(tmp_path, inspect, sources)
    root = tk.Tk()
    root.withdraw()
    app = LoggerApp(root, engine=engine)
    app.headless_alerts = True
    app.session_var.set("11-26-2026 2008 F350 ui")
    for row in app.rows:
        if row["name"] != "can0":
            row["enabled"].set(False)
    app.on_start()
    assert engine.running
    app.mark_var.set("start of grade")
    app.on_mark()
    app.on_stop()
    assert not engine.running
    assert app.alerts == []
    text = Path(engine.status()["markers_file"]).read_text(encoding="utf-8")
    assert "start of grade" in text
    root.destroy()
