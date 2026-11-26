"""Desktop window for passive CAN logging. Runs as the normal user."""

from __future__ import annotations

import os
import shutil
import subprocess
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from f350can import ALLOWED_BITRATES, TZ_NAME
from f350can.engine import SessionEngine
from f350can.forscan import find_overlapping_sessions, format_overlaps
from f350can.iface import IfaceError

HELPER_NAME = "can-listen-only-up"
DEFAULT_HELPER = Path("/usr/local/sbin") / HELPER_NAME
DEFAULT_FORSCAN = Path.home() / ".wine-forscan/drive_c/users/pyrocrazy130/Documents/FORScan"

INSTALL_HINT = (
    "The bring-up helper is not installed.\n\n"
    "Install it yourself (the logger stays unprivileged):\n"
    "  sudo install -o root -g root -m 0755 "
    "vehicles/2008-f350-6.4/bringup/can-listen-only-up /usr/local/sbin/can-listen-only-up\n"
    "Then either a polkit rule or a sudoers rule for that one path.\n"
    "See vehicles/2008-f350-6.4/README.md."
)


def default_session_name() -> str:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    now = datetime.now(ZoneInfo(TZ_NAME))
    return now.strftime("%m-%d-%Y") + " 2008 F350 "


POLICY_PATH = Path("/usr/share/polkit-1/actions/com.pyrocrazy130.can-listen-only-up.policy")


def prefer_pkexec() -> bool:
    """Use pkexec only when its policy is installed. Otherwise sudo -n.

    A desktop has pkexec on PATH even when this policy was never installed.
    Falling through to ``sudo -n`` lets a NOPASSWD sudoers rule work from the
    GUI without sitting on a password prompt that has no terminal.
    """
    return shutil.which("pkexec") is not None and POLICY_PATH.is_file()


def helper_command(channels: list[tuple[str, int]], helper: Path, *, use_pkexec: bool) -> list[str]:
    if helper.name != HELPER_NAME:
        raise ValueError(f"refusing to run {helper}; basename must be {HELPER_NAME}")
    specs = [f"{name}={bitrate}" for name, bitrate in channels]
    if use_pkexec:
        return ["pkexec", str(helper), *specs]
    return ["sudo", "-n", str(helper), *specs]


def human_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / 1024 / 1024:.2f} MB"


def format_elapsed(seconds: float) -> str:
    total = max(0, int(seconds))
    return f"{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}"


class LoggerApp:
    def __init__(self, root: tk.Tk, engine: SessionEngine | None = None, log_root: Path | None = None):
        self.root = root
        self.engine = engine or SessionEngine(log_root=log_root)
        self.alerts: list[tuple[str, str]] = []
        self.headless_alerts = False
        self._proc = subprocess.run
        root.title("2008 F-350 passive CAN logger")
        root.minsize(760, 520)
        if os.geteuid() == 0:
            self._banner_text = (
                "This window is running as root. Quit and start it as your normal user. "
                "Only the bring-up helper should run as root."
            )
        else:
            self._banner_text = (
                "Listen-only. This program never transmits and never opens the OBDLink EX. "
                "can0 defaults to HS-CAN 500 kbit/s. can1 defaults to 125 kbit/s "
                "(it was silent at 500k; that may be MS-CAN or the wrong plug)."
            )
        self.session_var = tk.StringVar(value=default_session_name())
        self.notes_var = tk.StringVar()
        self.mark_var = tk.StringVar(value="start of grade")
        self.elapsed_var = tk.StringVar(value="00:00:00")
        self.size_var = tk.StringVar(value="0 B")
        self.path_var = tk.StringVar(value=str(self.engine.log_root))
        self._build()
        self._tick()

    def _build(self) -> None:
        outer = ttk.Frame(self.root, padding=10)
        outer.pack(fill="both", expand=True)
        banner = ttk.Label(outer, text=self._banner_text, wraplength=720)
        banner.pack(fill="x", pady=(0, 8))

        form = ttk.Frame(outer)
        form.pack(fill="x")
        ttk.Label(form, text="Session").grid(row=0, column=0, sticky="w")
        ttk.Entry(form, textvariable=self.session_var, width=52).grid(
            row=0, column=1, sticky="ew", padx=6
        )
        ttk.Label(form, text="Notes").grid(row=1, column=0, sticky="w")
        ttk.Entry(form, textvariable=self.notes_var, width=52).grid(
            row=1, column=1, sticky="ew", padx=6, pady=4
        )
        form.columnconfigure(1, weight=1)
        ttk.Label(outer, textvariable=self.path_var).pack(anchor="w", pady=(4, 8))

        self.rows = []
        box = ttk.LabelFrame(outer, text="Channels", padding=8)
        box.pack(fill="x")
        defaults = (("can0", 500000, True), ("can1", 125000, True))
        for row_i, (name, bitrate, enabled) in enumerate(defaults):
            self.rows.append(self._channel_row(box, row_i, name, bitrate, enabled))

        buttons = ttk.Frame(outer)
        buttons.pack(fill="x", pady=8)
        ttk.Button(buttons, text="Bring up listen-only", command=self.on_bringup).pack(
            side="left"
        )
        self.start_btn = ttk.Button(buttons, text="Start", command=self.on_start)
        self.start_btn.pack(side="left", padx=8)
        ttk.Label(buttons, text="Mark").pack(side="left", padx=(12, 4))
        ttk.Entry(buttons, textvariable=self.mark_var, width=24).pack(side="left")
        ttk.Button(buttons, text="Mark event", command=self.on_mark).pack(side="left", padx=6)
        ttk.Button(buttons, text="Match FORScan log", command=self.on_match).pack(side="right")

        stats = ttk.Frame(outer)
        stats.pack(fill="x")
        ttk.Label(stats, text="Elapsed").pack(side="left")
        ttk.Label(stats, textvariable=self.elapsed_var, font=("TkDefaultFont", 12, "bold")).pack(
            side="left", padx=6
        )
        ttk.Label(stats, text="Written").pack(side="left", padx=(16, 0))
        ttk.Label(stats, textvariable=self.size_var).pack(side="left", padx=6)

        self.log = tk.Text(outer, height=10, wrap="word")
        self.log.pack(fill="both", expand=True, pady=(8, 0))
        self.log.configure(state="disabled")
        self._say(self._banner_text)

    def _channel_row(self, parent, row, name, bitrate, enabled):
        enabled_var = tk.BooleanVar(value=enabled)
        bitrate_var = tk.StringVar(value=str(bitrate))
        info = tk.StringVar(value="…")
        ttk.Checkbutton(parent, text=name, variable=enabled_var).grid(
            row=row, column=0, sticky="w"
        )
        ttk.Combobox(
            parent,
            textvariable=bitrate_var,
            values=[str(b) for b in ALLOWED_BITRATES],
            width=10,
            state="readonly",
        ).grid(row=row, column=1, padx=8)
        ttk.Label(parent, text="bit/s").grid(row=row, column=2, sticky="w")
        ttk.Label(parent, textvariable=info).grid(row=row, column=3, sticky="w", padx=8)
        return {"name": name, "enabled": enabled_var, "bitrate": bitrate_var, "info": info}

    def selected(self) -> list[tuple[str, int]]:
        chosen = []
        for row in self.rows:
            if row["enabled"].get():
                chosen.append((row["name"], int(row["bitrate"].get())))
        return chosen

    def alert(self, title: str, text: str) -> None:
        self.alerts.append((title, text))
        self._say(f"{title}: {text}")
        if not self.headless_alerts:
            messagebox.showerror(title, text)

    def _say(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text.rstrip() + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def on_bringup(self) -> None:
        channels = self.selected()
        if not channels:
            self.alert("Nothing selected", "Enable at least one channel.")
            return
        helper = Path(os.environ.get("CAN_LISTEN_ONLY_HELPER", str(DEFAULT_HELPER)))
        if not helper.is_file() or not os.access(helper, os.X_OK):
            self.alert("Helper not installed", INSTALL_HINT)
            return
        try:
            cmd = helper_command(channels, helper, use_pkexec=prefer_pkexec())
        except ValueError as exc:
            self.alert("Helper refused", str(exc))
            return
        self._say("Running " + " ".join(cmd))
        proc = self._proc(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
            self.alert("Bring-up failed", detail)
            return
        self._say("Interfaces brought up listen-only.")

    def on_start(self) -> None:
        if self.engine.running:
            self.on_stop()
            return
        try:
            path = self.engine.start(
                self.session_var.get(),
                self.selected(),
                notes=self.notes_var.get(),
            )
        except Exception as exc:
            self.alert("Not logging", str(exc))
            return
        self.start_btn.configure(text="Stop")
        self.path_var.set(str(path.parent))
        self._say(f"Logging to {path.parent}")

    def on_stop(self) -> None:
        self.engine.stop()
        self.start_btn.configure(text="Start")
        self._say("Stopped.")

    def on_mark(self) -> None:
        try:
            self.engine.mark(self.mark_var.get())
        except Exception as exc:
            self.alert("Mark failed", str(exc))
            return
        self._say(f"Marked: {self.mark_var.get()}")

    def on_match(self) -> None:
        folder = Path(os.environ.get("FORSCAN_DIR", str(DEFAULT_FORSCAN)))
        if not folder.is_dir():
            self.alert(
                "FORScan folder not found",
                f"{folder} is not on this machine. Set FORSCAN_DIR or copy a CSV.",
            )
            return
        csvs = sorted(folder.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not csvs:
            self.alert("No CSV", f"No CSV files in {folder}")
            return
        target = csvs[0]
        matches = find_overlapping_sessions(target, self.engine.log_root)
        text = format_overlaps(target, matches)
        self._say(text)
        if not self.headless_alerts:
            messagebox.showinfo("FORScan overlap", text)

    def _tick(self) -> None:
        try:
            self._refresh()
        except Exception as exc:
            self._say(f"status: {exc}")
        self.root.after(400, self._tick)

    def _refresh(self) -> None:
        if self.engine.running:
            snap = self.engine.status()
            self.elapsed_var.set(format_elapsed(snap["elapsed_s"]))
            total = sum(ch["bytes"] for ch in snap["channels"].values())
            self.size_var.set(human_bytes(total))
            by_name = snap["channels"]
            for warning in snap["warnings"][-3:]:
                if warning not in self.log.get("1.0", "end"):
                    self._say(warning)
        else:
            by_name = {}
        for row in self.rows:
            name = row["name"]
            if name in by_name:
                ch = by_name[name]
                lo = "listen-only" if ch["listen_only"] else "NOT listen-only"
                if ch["kind"] == "vcan":
                    lo = "vcan"
                row["info"].set(
                    f"{ch['link']}  {ch['frames_per_s']:.0f} fr/s  "
                    f"{ch['state']}  rxerr {ch['rx_errors']}  txΔ {ch['tx_delta']}  "
                    f"{lo}  {human_bytes(ch['bytes'])}"
                )
            else:
                try:
                    status = self.engine.inspect(name)
                except IfaceError as exc:
                    row["info"].set(str(exc))
                    continue
                if not status.present:
                    row["info"].set("missing")
                else:
                    lo = "listen-only" if status.listen_only else "not listen-only"
                    if status.kind == "vcan":
                        lo = "vcan (no listen-only bit)"
                    rate = status.bitrate if status.bitrate is not None else "?"
                    row["info"].set(
                        f"{'up' if status.is_up else 'down'}  {status.kind or '?'}  "
                        f"{rate}  {status.state}  {lo}"
                    )


def run(engine: SessionEngine | None = None, log_root: Path | None = None) -> int:
    root = tk.Tk()
    LoggerApp(root, engine=engine, log_root=log_root)
    root.mainloop()
    return 0
