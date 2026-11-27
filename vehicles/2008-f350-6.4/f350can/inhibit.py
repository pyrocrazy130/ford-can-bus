"""Ask systemd not to suspend the laptop while a capture is running.

A suspend during candump is what dropped the earlier session. Inhibition is
best-effort: if systemd-inhibit is missing the logger still runs and reports
the warning in the session metadata.
"""

from __future__ import annotations

import shutil
import subprocess
import time

INHIBIT_ARGV = [
    "systemd-inhibit",
    "--what=sleep:idle:handle-lid-switch",
    "--who=ford-can-logger",
    "--why=Passive CAN logging in progress",
    "--mode=block",
    "--",
    "sleep",
    "infinity",
]


class SystemdInhibitor:
    def __init__(self, popen=None, sleeper=time.sleep):
        self._popen = popen or subprocess.Popen
        self._sleep = sleeper
        self.proc = None
        self.warning: str | None = None

    def start(self) -> str | None:
        self.warning = None
        if self._popen is subprocess.Popen and shutil.which("systemd-inhibit") is None:
            self.warning = "systemd-inhibit not found; laptop sleep is not inhibited"
            return self.warning
        try:
            self.proc = self._popen(
                INHIBIT_ARGV,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
        except FileNotFoundError:
            self.warning = "systemd-inhibit not found; laptop sleep is not inhibited"
            return self.warning
        self._sleep(0.05)
        if self.proc.poll() is not None:
            err = ""
            if self.proc.stderr is not None:
                try:
                    err = self.proc.stderr.read().decode(errors="replace")[:300]
                except Exception:
                    err = ""
            self.warning = (
                "systemd-inhibit exited immediately; laptop sleep is not inhibited"
                + (f" ({err.strip()})" if err.strip() else "")
            )
            self.proc = None
            return self.warning
        return None

    def stop(self) -> None:
        proc = self.proc
        self.proc = None
        if proc is None or proc.poll() is not None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
