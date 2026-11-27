"""DBC checks, FORScan correlation, summarize, scrub, and the root helper."""

import json
import os
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DBC = ROOT / "ford_2008_f350_hscan.dbc"
HELPER = ROOT / "bringup" / "can-listen-only-up"


def test_dbc_parses_and_labels_confidence():
    cantools = pytest.importorskip("cantools")
    db = cantools.database.load_file(DBC)
    assert db.get_message_by_frame_id(0x201) is not None
    text = DBC.read_text(encoding="utf-8")
    assert "[confidence=confirmed]" not in text
    for line in text.splitlines():
        if line.startswith("CM_ SG_") or line.startswith("CM_ BO_"):
            assert "[confidence=hypothesis]" in line or "[confidence=public-source]" in line
    decoded = db.decode_message(0x201, bytes.fromhex("0320000027100000"), decode_choices=False)
    # 2005 layout: low nibble of byte0 plus byte1 = 0x320 = 800 rpm.
    # 2011 layout: bytes 0-1 = 0x0320 * 0.25 = 200 rpm. Both are hypotheses.
    assert decoded["Hyp2005_EngineSpeed"] == pytest.approx(800)
    assert decoded["Hyp2005_VehicleSpeed"] == pytest.approx(100.0)
    assert "Hyp2011_EngineSpeed" not in decoded


def test_correlate_finds_scale_and_offset(tmp_path):
    from f350can.candump import format_candump_line
    from f350can.correlate import correlate, write_hypothesis_dbc

    rpms = [700, 1500, 700, 2000, 900, 1800, 1100, 1600]
    ects = [20, 21, 22, 30, 40, 55, 60, 70]
    lines = []
    for i, (rpm, ect) in enumerate(zip(rpms, ects)):
        raw = int(rpm / 0.25)
        payload = bytes([(raw >> 8) & 0xFF, raw & 0xFF, i, 0, 0, 0, 0, 0])
        lines.append(format_candump_line(1000.0 + i * 0.1, "can0", 0x201, payload).rstrip("\n"))
        lines.append(
            format_candump_line(1000.0 + i * 0.1 + 0.01, "can0", 0x420, bytes([ect + 40]) + b"\x00" * 7).rstrip("\n")
        )
    log = tmp_path / "can.log"
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    csv = tmp_path / "forscan.csv"
    rows = ["time(ms);RPM(1/min);ECT(°C)"]
    for i, (rpm, ect) in enumerate(zip(rpms, ects)):
        rows.append(f"{i * 100};{rpm};{ect}")
    csv.write_text("\n".join(rows) + "\n", encoding="utf-8")
    found = correlate(log, csv, ref_offset=1000.0, min_interval=0, min_points=8)
    rpm_hits = [c for c in found if c.pid.startswith("RPM") and c.can_id == 0x201 and c.field == "be16@b0"]
    assert rpm_hits, found
    assert rpm_hits[0].r == pytest.approx(1.0, abs=1e-6)
    assert rpm_hits[0].scale == pytest.approx(0.25, rel=1e-3)
    assert rpm_hits[0].offset == pytest.approx(0.0, abs=1e-6)
    ect_hits = [c for c in found if c.pid.startswith("ECT") and c.field == "b0"]
    assert ect_hits
    assert ect_hits[0].r == pytest.approx(1.0, abs=1e-6)
    assert ect_hits[0].scale == pytest.approx(1.0, abs=1e-6)
    assert ect_hits[0].offset == pytest.approx(-40.0, abs=1e-6)
    frag = tmp_path / "hyp.dbc"
    assert write_hypothesis_dbc(frag, found, min_r=0.95) >= 2
    cantools = pytest.importorskip("cantools")
    cantools.database.load_file(frag)


def test_summarize_ids(tmp_path):
    from f350can.candump import format_candump_line
    from f350can.summarize import summarize

    lines = []
    for i in range(10):
        lines.append(format_candump_line(100 + i * 0.01, "can0", 0x201, bytes([i, 0, 0, 0, 0, 0, 0, 0])))
        lines.append(format_candump_line(100 + i * 0.05, "can0", 0x123, b"\x11" * 8))
    path = tmp_path / "s.log"
    path.write_text("".join(lines), encoding="utf-8")
    rows = {row.can_id: row for row in summarize(path)}
    assert rows[0x201].count == 10
    assert 0 in rows[0x201].changed
    assert rows[0x123].changed == set()
    assert rows[0x201].as_dict()["hz"] == pytest.approx(100, rel=0.05)


def test_match_forscan_by_mtime(tmp_path):
    from f350can.forscan import find_overlapping_sessions

    log_root = tmp_path / "truck-logs" / "2026-11-26"
    log_root.mkdir(parents=True)
    session = {
        "session": "11-26-2026 2008 F350 grade",
        "start": "2026-11-26T12:00:00-08:00",
        "stop": "2026-11-26T12:10:00-08:00",
    }
    (log_root / "session.json").write_text(json.dumps(session), encoding="utf-8")
    other = tmp_path / "truck-logs" / "2026-11-20"
    other.mkdir()
    (other / "old.json").write_text(
        json.dumps(
            {
                "session": "old",
                "start": "2026-11-20T12:00:00-08:00",
                "stop": "2026-11-20T12:05:00-08:00",
            }
        ),
        encoding="utf-8",
    )
    csv = tmp_path / "forscan.csv"
    # 30 s of samples. mtime will be the end.
    lines = ["time(ms);RPM(1/min)"] + [f"{i * 1000};{800+i}" for i in range(31)]
    csv.write_text("\n".join(lines) + "\n", encoding="utf-8")
    # Session is 12:00-12:10 PST = those epochs. Put CSV end at 12:05 so
    # start is 11:35? duration is 30 s, so set mtime to 12:02 and start is 12:01:30.
    import datetime as dt
    from zoneinfo import ZoneInfo

    end = dt.datetime(2026, 11, 26, 12, 2, tzinfo=ZoneInfo("America/Los_Angeles")).timestamp()
    os.utime(csv, (end, end))
    matches = find_overlapping_sessions(csv, tmp_path / "truck-logs")
    assert len(matches) == 1
    assert matches[0].session == "11-26-2026 2008 F350 grade"
    assert matches[0].overlap_s == pytest.approx(30, abs=1.5)
    assert matches[0].csv_start_source == "mtime minus duration"


def test_scrub_vin_frames_and_text(tmp_path):
    from f350can.scrub import check_tree, scrub_candump, scrub_text

    vin = "1FT" + "SW00X00X000000"
    src = tmp_path / "in.log"
    # 0x4FF chunk: '0' + '1FTWX' + padding. Plus a short WMI run on 0x123.
    src.write_text(
        "(1.000000) can0 4FF#3031465457580000\n"
        "(1.100000) can0 123#3146545357303058\n"
        "(1.200000) can0 201#000003E800000000\n",
        encoding="utf-8",
    )
    dst = tmp_path / "out.log"
    stats = scrub_candump(src, dst)
    body = dst.read_text(encoding="utf-8")
    assert "31465457" not in body
    assert "1FT" not in body
    assert "201#000003E800000000" in body
    assert "4FF#3058585858580000" in body
    assert stats["wmi_frames"] >= 1
    notes = tmp_path / "notes.json"
    notes.write_text('{"notes": "%s"}' % vin, encoding="utf-8")
    out_notes = tmp_path / "notes.out.json"
    scrub_text(notes, out_notes)
    assert vin not in out_notes.read_text(encoding="utf-8")
    assert check_tree(out_notes) == []
    assert check_tree(notes) == [str(notes)]


def test_helper_dry_run_is_narrow():
    good = subprocess.run(
        ["bash", str(HELPER), "--dry-run", "can0=500000", "can1=125000"],
        check=True,
        capture_output=True,
        text=True,
    )
    out = good.stdout
    assert "ip link set can0 type can bitrate 500000 listen-only on restart-ms 0" in out
    assert "ip link set can1 type can bitrate 125000 listen-only on restart-ms 0" in out
    assert "cansend" not in HELPER.read_text(encoding="utf-8")
    assert "ttyUSB" not in out
    for bad in ("can0=250000", "vcan0=500000", "ttyUSB0=500000", "can0=500000;reboot"):
        proc = subprocess.run(
            ["bash", str(HELPER), "--dry-run", bad],
            capture_output=True,
            text=True,
        )
        assert proc.returncode != 0, bad
    live = subprocess.run(["bash", str(HELPER), "can0=500000"], capture_output=True, text=True)
    assert live.returncode != 0
    assert "root" in live.stderr.lower()


def test_vcan_round_trip_if_kernel_allows(tmp_path):
    if os.environ.get("REQUIRE_VCAN") != "1":
        probe = subprocess.run(
            ["ip", "link", "add", "dev", "vcan_probe", "type", "vcan"],
            capture_output=True,
            text=True,
        )
        if probe.returncode != 0:
            pytest.skip("kernel has no vcan: " + (probe.stderr or probe.stdout).strip())
        subprocess.run(["ip", "link", "del", "dev", "vcan_probe"], check=False)
    name = f"vcan{os.getpid() % 10000}"
    subprocess.run(["ip", "link", "del", "dev", name], check=False, capture_output=True)
    added = subprocess.run(
        ["ip", "link", "add", "dev", name, "type", "vcan"],
        capture_output=True,
        text=True,
    )
    if added.returncode != 0:
        # CI may need sudo.
        added = subprocess.run(
            ["sudo", "ip", "link", "add", "dev", name, "type", "vcan"],
            capture_output=True,
            text=True,
        )
    if added.returncode != 0:
        if os.environ.get("REQUIRE_VCAN") == "1":
            pytest.fail(added.stderr)
        pytest.skip(added.stderr)
    try:
        subprocess.run(["sudo", "ip", "link", "set", name, "up"], check=True)
        from f350can.engine import SessionEngine
        import socket
        import struct

        sniff = socket.socket(socket.PF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
        sniff.bind((name,))
        sniff.settimeout(0.3)
        engine = SessionEngine(log_root=tmp_path, poll_s=0.1, inhibitor=type("I", (), {
            "start": lambda self: None,
            "stop": lambda self: None,
        })())
        # start() binds the read socket before returning.
        engine.start("11-26-2026 2008 F350 vcan", [(name, 500000)])
        sock = socket.socket(socket.PF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
        sock.bind((name,))
        frame = struct.pack("<IB3x8s", 0x201, 3, bytes.fromhex("010203") + b"\x00" * 5)
        for _ in range(5):
            sock.send(frame)
        assert _wait_frames(engine, name, 5)
        seen = 0
        while True:
            try:
                sniff.recv(16)
            except socket.timeout:
                break
            seen += 1
            if seen > 5:
                break
        assert seen == 5, f"logger transmitted extra frames ({seen} seen, 5 sent)"
        engine.stop()
        log = next(tmp_path.rglob(f"*_{name}.log"))
        body = log.read_text(encoding="utf-8")
        assert body.count("201#010203") >= 5
        sock.close()
        sniff.close()
    finally:
        subprocess.run(["sudo", "ip", "link", "del", "dev", name], check=False)


def _wait_frames(engine, name, n):
    end = time.time() + 3
    while time.time() < end:
        if engine.status()["channels"][name]["frames"] >= n:
            return True
        time.sleep(0.02)
    return False
