# 2008 F-350 6.4L Power Stroke — passive HS-CAN logger

Tools for Bo's 2008 Ford F-350, 6.4L Power Stroke, 5R110W TorqShift. On this truck the transmission control function is integrated in the PCM. The logger is strictly passive: it reads SocketCAN and writes `candump -L` text. It never sends a frame, and it never opens the OBDLink EX that FORScan uses.

Nothing in `ford_2008_f350_hscan.dbc` is a confirmed decode of this truck. See [What the DBC actually claims](#what-the-dbc-actually-claims).

## What you need

On the laptop (normal user, Wayland or X11):

```bash
sudo apt install python3-tk iproute2 can-utils
```

`cantools` is only for the DBC and the correlation tool:

```bash
python3 -m pip install --user cantools
```

Hardware assumed here: InnoMaker USB3CAN-X2 (`gs_usb`). `can0` is the busy HS-CAN at 500 kbit/s. `can1` was silent at 500 kbit/s, so the window defaults it to 125 kbit/s (Ford MS-CAN on the 2011 truck in this repo; not yet confirmed on this port). Either channel can be turned off, and each bitrate is only 500000 or 125000.

## Root helper (install this yourself)

Bringing a CAN interface up needs root. The window stays your user. The only root command is `bringup/can-listen-only-up`, which will:

- accept only names like `can0` or `can1` (not `vcan`, not `ttyUSB`, not the OBDLink EX)
- accept only bitrates `500000` and `125000`
- run exactly `ip link set … down`, then `type can bitrate … listen-only on restart-ms 0`, then `up`, then `txqueuelen 1000`
- leave the interface down if listen-only did not stick

It does not send CAN frames.

```bash
sudo install -o root -g root -m 0755 \
  vehicles/2008-f350-6.4/bringup/can-listen-only-up \
  /usr/local/sbin/can-listen-only-up
```

Pick one of these so the window can call that path. Do not give the UI a blanket sudo.

**Polkit (GUI password prompt).** The policy file's `exec.path` must be the script you installed.

```bash
sudo install -o root -g root -m 0644 \
  vehicles/2008-f350-6.4/bringup/com.pyrocrazy130.can-listen-only-up.policy \
  /usr/share/polkit-1/actions/
```

If `pkexec` refuses `/usr/local/sbin`, install the script to `/usr/sbin/can-listen-only-up` instead and change the `exec.path` line in the policy to that same path.

**sudoers (no password prompt).** `sudo visudo -f /etc/sudoers.d/can-listen-only` and use `bringup/sudoers-can-listen-only`, with your username in place of `YOUR_USERNAME`. Mode `0440`, owner root. The rule is only that one program.

The window uses `pkexec` when that policy file is present. Otherwise it runs `sudo -n` so a missing password prompt cannot hang a GUI. "Bring up listen-only" will fail with the helper's own error until one of the two is installed.

Check the helper without touching the bus:

```bash
bringup/can-listen-only-up --dry-run can0=500000 can1=125000
```

## Run the window

From this directory (`vehicles/2008-f350-6.4`):

```bash
python3 -m f350can
```

From the repo root:

```bash
python3 vehicles/2008-f350-6.4/f350can/__main__.py
```

1. Leave `can0` at 500000 and `can1` at 125000, or change them. Uncheck a channel you do not want.
2. Click **Bring up listen-only**. That is the root step.
3. Session name starts as `11-26-2026 2008 F350 ` (today's date in America/Los_Angeles). Type the label, for example `grade`.
4. **Start**. The logger refuses to start unless each real `can` interface is up, in listen-only mode, and already at the bitrate you selected. It will not run `ip` itself.
5. **Mark event** appends a line to the sidecar immediately (default text `start of grade`).
6. **Stop**.

While logging, the window shows frames/s, controller state, receive errors, whether the interface's own transmit counter moved, elapsed time, and bytes written. Sleep and lid-close are inhibited with `systemd-inhibit` (`sleep`, `idle`, and `handle-lid-switch`) for the length of the session. If inhibit cannot be taken, logging still runs and the window says so.

If an interface goes down (the failure that killed candump when the laptop suspended), that segment is closed. When the same interface is back, listen-only, and at the selected bitrate, logging continues in a new file ending in `_seg2`, `_seg3`, and so on. If it returns writable, logging stays stopped on that channel.

Headless, same checks, no window:

```bash
python3 -m f350can --headless \
  --session "11-26-2026 2008 F350 grade" \
  --channel can0=500000 --channel can1=125000
```

Ctrl-C stops the session. `--duration 30` stops itself.

## Where the files go

```
~/truck-logs/2026-11-26/11-26-2026 2008 F350 grade_can0.log
~/truck-logs/2026-11-26/11-26-2026 2008 F350 grade_can1.log
~/truck-logs/2026-11-26/11-26-2026 2008 F350 grade.markers.txt
~/truck-logs/2026-11-26/11-26-2026 2008 F350 grade.json
```

The log line is the same shape as the 2026 captures already in this repo:

```
(1792947706.972675) can0 225#00FF00000000003D
```

The JSON records start and stop in America/Los_Angeles, the bitrate and listen-only flag seen at the start of each segment, notes, markers, and whether sleep was inhibited. A full 17-character Ford-style VIN typed into the session name, notes, or a marker is replaced with `X` before it is written. Do not rely on that as the only scrub.

These files are on purpose **not** in git. This repo has no Git LFS. Older masked logs were committed as ordinary files; new raw captures stay in `~/truck-logs`. `.gitignore` ignores `truck-logs/` and `vehicles/2008-f350-6.4/captures/` if a copy is made inside the tree.

## Match a FORScan CSV

**Match FORScan log** looks in `~/.wine-forscan/drive_c/users/pyrocrazy130/Documents/FORScan/` (override with `FORSCAN_DIR`) at the newest CSV and compares it with `~/truck-logs`.

FORScan `time(ms)` is relative to when that CSV started, not a wall clock. The matcher uses a clock in the filename when one is present, otherwise file mtime minus the CSV duration. That is the same class of guess that was wrong by about 90 seconds on the 2005 drive until RPM was used to check it. The printed `--ref-offset` is a starting point for the correlator, not a proof.

```bash
python3 tools/match_forscan.py /path/to/forscan.csv --log-root ~/truck-logs
```

## Reverse-engineering tools

Summarize ids, rates, and which bytes change:

```bash
python3 tools/summarize_ids.py ~/truck-logs/2026-11-26/*_can0.log
```

Correlate byte and big-endian 16-bit fields with FORScan columns (ECT, EOT, TFT, RPM, VSS, TCC, slip, fan duty, whatever is in the header). Output is scale, offset, and Pearson r. It does not edit the vehicle DBC.

```bash
python3 tools/correlate_forscan.py capture.log forscan.csv --ref-offset 1732660000.0
python3 tools/correlate_forscan.py capture.log forscan.csv --ref-offset 1732660000.0 \
  --dbc-fragment /tmp/hypotheses.dbc
```

Anything that fragment contains is a hypothesis.

## VIN scrub before anything is published

The 2008 broadcast VIN id is not known. `tools/scrub_vin.py` runs the repo `tools/mask_vin.py` rules (2005 `0x4FF` chunks, 2011 `0x40A` mux `C100`–`C102`, Mode 09 and DID `F190` on `0x7E8`/`0x7E9`) and then masks a Ford WMI (`1FT`, `1FD`, `1FM`, `2FT`, …) plus the rest of a VIN-charset run in that frame when the run is at least 5 characters. That is how the 2005 VIN was split across frames. It can false-positive; it is for publishing, not for the live log.

```bash
python3 tools/scrub_vin.py candump raw.log public.log
python3 tools/scrub_vin.py text notes.json notes.public.json
python3 tools/scrub_vin.py check public.log
```

`check` exits 1 if a full 17-character Ford-style VIN is still in the file. It does not print the VIN.

## What the DBC actually claims

`ford_2008_f350_hscan.dbc` loads in cantools (`cantools.database.load_file`). Comments use `[confidence=hypothesis]` or `[confidence=public-source]`. There is no `[confidence=confirmed]` signal. Attribute `SigConfidence` / `MsgConfidence` use the same scale as the other files in `dbc/`: hypothesis is `low`, public-source is `medium`.

**Published network facts, not signal layouts.** The 2008 F-450 6.4L diesel workshop information-bus pages (same 6.4L Super Duty powertrain family; an F-350-specific page was not the one quoted) say HS-CAN runs at a maximum of 500 Kbps and list ABS, the instrument cluster, PCM, RCM, supplemental heater, trailer brake control, TCM, and the VGT actuator. The instrument cluster is the gateway between HS-CAN and MS-CAN.

- [HS-CAN 500 Kbps and module list](https://workshop-manuals.com/ford/f_450_4wd_super_duty/v8-6.4l_dsl_turbo/powertrain_management/computers_and_control_systems/information_bus/component_information/testing_and_inspection/initial_inspection_and_diagnostic_overview/page_4566/)
- [Module list and gateway](https://workshop-manuals.com/ford/f_450_4wd_super_duty/v8-6.4l_dsl_turbo/powertrain_management/computers_and_control_systems/information_bus/component_information/diagrams/page_4562/)

The workshop lists TCM as its own HS-CAN node. On this truck that function is inside the PCM. Those two statements can both be true. This file does not add a separate TCM box.

**Public-source diagnostic ids (ISO 15765-4), not seen yet on a 2008 log in this repo.** `0x7DF` functional request, `0x7E0` ECM request, `0x7E8` ECM response. The logger must not transmit them.

**Hypotheses copied from other trucks in this repo, and labeled that way.**

| Signal | Id | Why it is only a hypothesis |
|---|---|---|
| `Hyp2005_EngineSpeed`, `Hyp2005_VehicleSpeed`, `Hyp2005_AccelPedal` | `0x201` | Confirmed on the 2005 6.0 in `dbc/ford_2005_superduty_pcm_hscan.dbc` (12-bit RPM in byte 0 low nibble + byte 1, speed in bytes 4–5 at 0.01 km/h, pedal in byte 6). Different PCM year. |
| `Hyp2011_VehicleSpeed` | `0x201` bytes 2–3 | Confirmed on the 2011 6.7 in `dbc/ford_2011-2012_superduty_hscan.dbc`. Different engine and a 6R140, not a 5R110W. |
| 2011 RPM on `0x201` (bytes 0–1 × 0.25) | comment only | Same 2011 file. Those bits overlap the 2005 RPM field, so cantools will not hold both as signals. The comment tells you to score both with the correlator. |
| openDBC CGEA `EngVehicleSpThrottle_CG1` | not copied | A third layout (13-bit RPM × 2) from a different platform. [opendbc file](https://github.com/commaai/opendbc/blob/master/opendbc/dbc/ford_cgea1_2_ptcan_2011.dbc). |
| `Hyp2005_OutputShaftSpeed`, `Hyp2005_TransFluidTemp` | `0x225` | 2005 6.0, same 5R110W family. TFT offset was only medium confidence even there. |
| `Hyp2005_GearByte`, `Hyp2005_GearRatio` | `0x230` | 2005 5R110W gear byte and ratio. The 2011 6R140 uses this id with a different nibble layout; that layout was not copied. |
| `Hyp2005_EngineLoad` | `0x106` byte 7 | 2005, matched there to OBD load. |
| `Hyp2005_EngineCoolantTemp` | `0x420` byte 0, °C+40 | Confirmed on the 2005 while cold. |
| `Hyp2011_EngineCoolantTemp` | `0x156` byte 0, offset −60 | 2011 6.7. The offset was a guess even on that truck. |
| `Hyp2005_BrakeSwitchCandidate` | `0x440` byte 0 | Low-confidence candidate on the 2005. Brake was not logged. This is not a sourced brake pedal. |
| `Hyp2005_Payload` / `Hyp2011_Payload` | `0x4FF`, `0x40A` | VIN carriers on the 2005 and 2011. The 2008 id is unknown. Scrub both before publishing. |
| `DiagPayload` on `0x7E1` / `0x7E9` | | The 2005 truck answers the 5R110W there. Not seen on a 2008 log. |

Unsliced "community" F-150 tables that disagree with the Super Duty captures in this repo were not used.

## Tests

```bash
python3 -m pytest vehicles/2008-f350-6.4/tests -q
```

From this directory, `python3 -m pytest tests -q`. The suite uses fake interfaces for the listen-only gate, segment resume, FORScan overlap, correlation, scrub, and the window (needs `DISPLAY` or `xvfb-run`). A kernel `vcan` round-trip runs when `vcan` exists. GitHub Actions loads the `vcan` module and sets `REQUIRE_VCAN=1`. This development VM's kernel was built with `CONFIG_CAN` off, so that one test is skipped here.

`vcan` is the only interface kind allowed to log without listen-only. It has no wire and the kernel will not set the bit. A real `can` interface is refused even if someone names it `vcan0`.
