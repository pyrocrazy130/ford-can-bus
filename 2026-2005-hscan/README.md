# 2005 F-350 6.0L Super Duty — HS-CAN captures (2026-10)

**Vehicle:** Bo Gifford's 2005 Ford F-350 6.0L Power Stroke SuperCab 4x4. VIN on the bus is **masked** in these public copies (see [VIN masking](#vin-masking) below). Original unmasked logs stay in the private `can-translator` repo.

**Bus:** Ford HS-CAN, OBD-II pins 6/14, 500 kbit/s.  
**Interface:** InnoMaker USB2CAN-X2 (`gs_usb`), always `listen-only` (TX count 0). Cable: InnoMaker OBD-to-4xDB9 (DB9-2 = OBD 6/14). **Ground jumper (DB9 pin 3/5 → OBD pin 5) was not confirmed** for any of these sessions.  
**Cluster / PATS / APCM** on this truck live on SCP (J1850 PWM, OBD 2/10) and are **not** in these logs.  
**Related private work:** github.com/pyrocrazy130/can-translator (DBC + analysis). Public DBC copies (VIN scrubbed) are in `../dbc/`.

All times are America/Los_Angeles (PDT).

## Index

| File | Size | What | sha256 (this public file) |
|---|---|---|---|
| `2026-10-24_keyon_noengine_can0.log` | 1.9 MB | 60 s key-on, engine off (suspect splitter) | `6e9a9eab011fe1d2cb3be50280a6b1208687e93aeda54930614e6b3dc34fdc74` |
| `2026-10-24_forscan_KOEO.fsl` | 44 KB | Matching FORScan live-stream (binary) | `fa2db08ea03d33c1975fd7b3583a8633cd0dea1d8d5a994fa46aa1fd572bfdcd` |
| `2026-10-25_sync_can0.log` | 9.7 MB | Synced HS-CAN + FORScan (parked: KOEO/crank/idle/blips) | `b8a8e09e2d012fef91d0187a28df2e6edf86d561ee3fd05b71425539bc09101e` |
| `2026-10-25_sync_forscan.csv` | 838 KB | FORScan CSV for the sync capture | `fecabad17483062d15099e59244695f11b21a771d6543b242d4a78b7bfa56d8f` |
| `2026-10-25_sync_forscan.fsl` | 683 KB | FORScan binary for the sync capture | `e9dbde283ebc3f8ed40bab218a39f7de1c600e713c9ec8128ccd81dc639afed7` |
| `2026-10-25_sync_analysis.md` | — | Analysis (VIN scrubbed) | — |
| `2026-10-25_drive_can1.log` | 63 MB | Highway cruise drive (live channel was linux `can1`) | `248be4e63cdc4cb6796002b8ce81dbfaf2e07861d1a98ed86a29c0f273ab8295` |
| `2026-10-25_drive_can0.log` | 0 B | Empty — wrong channel; see note below | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `2026-10-25_drive_forscan_A.csv` | 2.0 MB | FORScan CSV for the drive | `d2f5080013d9953a4dd471aef5ab97cc58b7b5bb044009e64d7e306dd8572b29` |
| `2026-10-25_drive_forscan_A.fsl` | 1.5 MB | FORScan binary for the drive | `0b12663fdee46ab9ff0b5e978ed30afeb6179cd153a1ed0919eb7a4dfb1aa294` |
| `2026-10-25_drive_times.txt` | 2.3 KB | Wall-clock marks (Hermes) | `1c610fc6f474ab234cf94bc72d047fb6816d4536aee3ef11ea83b6d7dd49751e` |
| `2026-10-25_drive_analysis.md` | — | Analysis (VIN scrubbed) | — |

No file needed gzip (largest is 63 MB).

---

## VIN masking

Public copies of the CAN logs have the vehicle identification number replaced. **can-translator is untouched.**

| Where | How |
|---|---|
| Broadcast **0x4FF** (PCM VIN chunks) | Keep b0 = chunk index ASCII `'0'`/`'1'`/`'2'`. Replace every printable VIN character in b1… with ASCII `'X'` (`0x58`). Keep `00` padding. |
| ISO-TP **Mode 09 PID 02** VIN replies on 0x7E8 (drive log only) | First-frame and consecutive-frame VIN bytes → `'X'`. PCI / `49 02` / length untouched. |
| Docs / DBC comments | Written as `1FTWX31P25E******`. |

**Original (private) sha256 → public sha256:**

| File | Original | Public (masked) |
|---|---|---|
| `2026-10-24_keyon_noengine_can0.log` | `d0562cb291cd9c8833f414ef00c2facd997e0fa0299449a77ad9db08de60f53a` | `6e9a9eab011fe1d2cb3be50280a6b1208687e93aeda54930614e6b3dc34fdc74` |
| `2026-10-25_sync_can0.log` | `2caf63d007fd12b377c96798ea046941f3eadaf2c39429cb10306fc5a0a6f78c` | `b8a8e09e2d012fef91d0187a28df2e6edf86d561ee3fd05b71425539bc09101e` |
| `2026-10-25_drive_can1.log` | `a05aef7856b6493698128634cd8f41d72876a8ca630473ed89d86e958674ab13` | `248be4e63cdc4cb6796002b8ce81dbfaf2e07861d1a98ed86a29c0f273ab8295` |

FORScan `.csv` / `.fsl` / `times.txt` contained no VIN string; they are byte-identical to the private copies. The masker is `../tools/mask_vin.py`.

---

## 2026-10-24 — key-on, engine off (suspect splitter)

- **When:** 2026-10-24 ~18:27 PDT, ~60 s.
- **Channel:** linux `can0`, listen-only 500k.
- **Conditions:** Key on, engine off.
- **IDs (14):** 105 106 200 201 212 215 217 225 230 420 430 440 4D0 4FF. Periods roughly 8–1057 ms (see DBC `GenMsgCycleTime`).
- **Issue:** Taken through an OBD splitter that later prevented FORScan from reading the truck correctly. Adapter reported 0 errors and timing is steady, but treat as possibly degraded. Replaced by the 2026-10-25 sync capture for analysis.
- **FORScan:** `2026-10-24_forscan_KOEO.fsl` taken around the same time (binary; export CSV to use).

## 2026-10-25 — synchronized parked capture (sync)

- **CAN:** `2026-10-25_sync_can0.log`, candump `-L`, `can0` listen-only 500k, DB9-2 of InnoMaker cable, **new** OBD splitter (all pins). TX 0.
- **CAN time range:** 10:01:46.973–10:06:18.731 PDT (271.8 s, 210 170 frames).
- **FORScan:** 2.3.71, play click **10:00:36 PDT**, CSV 390.8 s / 12 188 samples, semicolon-separated, `time(ms)` relative to play click. PIDs (engineering units): ECT, EOT, VPWR, RPM, VSS, ICP, IPR, FICM_LPWR, FICM_MPWR, FICM_VPWR, MAP, IAT, GPL.
- **Alignment:** `--ref-offset 1792947636.274` (CSV t=0 = play click = 10:00:36.274 PDT). The CAN file starts ~70.7 s later, so the 60 s key-on/engine-off stretch is **only** in the CSV. Overlap covers crank, idle, and both free-rev blips (CSV peaks 259.1 / 277.8 s, max 2111 rpm).
- **IDs:** same 14 broadcast IDs + diagnostic 7E0/7E8 (Mode 22 polling).
- **Known issues:** First candump attempt started 10:00:24 but its stdout was truncated; this file is the second start. Ground jumper not confirmed.
- **Confirmed broadcast signals (detail in analysis doc / DBC):** 0x201 RPM (12-bit, high), 0x420 b0 ECT °C+40 (high, 19–39 °C), 0x4FF VIN (masked here), 0x200 b7 boost medium. 0x430 b1 is **not** battery voltage.

## 2026-10-25 — highway cruise drive

- **CAN:** `2026-10-25_drive_can1.log`, candump `-L`, **linux `can1`** listen-only 500k (USB2CAN-X2 CAN1 LEDs lit; `can0` log is empty — channel swap). 12:10:34.42–12:41:23.2 PDT, 1 361 327 frames, 63 MB.
- **FORScan A:** CSV 1358.9 s, 24 338 samples, uneven ~32 ms median (p90 160 ms). PIDs: RPM, VSS, MAP, ICP, IPR, EOT, APP, LOAD.OBDII, TFT, GEAR, GEAR_INPT, TCC_RAT, LINEDSD, OSS.
- **Alignment (important):** Hermes's suggested `--ref-offset 1792955689.792` (first 7E1 poll at 12:14:49.79) is **91.8 s early**. FORScan's CSV starts when recording started, not at the first poll. Correct value: **`--ref-offset 1792955781.572`** (CSV t=0 = 12:16:21.57 PDT). Verified by RPM cross-correlation (R² 0.999996) and by tow/haul / parked wall-clock marks.
- **Timeline (CSV-relative seconds after the corrected t=0):**
  - −347…0 (CAN-only head, 12:10–12:16): highway cruise already under way — **not** the grade. 120–140 km/h, gear 6, boost up to 70 kPa.
  - Overlap: highway cruise, tow/haul ~338–588 s (passenger call 12:22:02–12:26:15), side streets from ~736 s (12:28:37), parked ~1222 s (12:36:43), hot idle to end (EOT 89 °C, TFT 71 °C).
  - **Grade climb was missed** — FORScan was not polling yet when it happened.
  - CAN log ends 12:41:23 with engine still idling; Hermes's key-off mark is 12:41:47 (no key-off in the file).
- **Diagnostics:** PCM on 7E0→7E8; **TCM (5R110W) on 7E1→7E9**. Confirmed DID formulas (also in can-translator `tools/signal-finder/sigfind/pid_table.py`):

  | ECU | DID | PID | Formula |
  |---|---|---|---|
  | 7E8 | 0x1165 | RPM | raw/4 |
  | 7E8 | 0x11C1 | VSS | raw/512 mph |
  | 7E8 | 0x09D4 | APP | A×100/256 % |
  | 7E8 | 0x0004 | LOAD.OBDII | A×100/255 % |
  | 7E8 | 0x1440 / 0x1446 / 0x1434 / 0x1310 | MAP / ICP / IPR / EOT | raw/4 kPa; raw×1000/256 kPa; A×100/256 %; raw/100−40 °C |
  | 7E9 | 0x11B3 / 0x11B5 / 0x11BA / 0x1674 / 0x09D8 | GEAR / OSS / TCC_RAT / TFT / LINEDSD | A/2; raw/4 rpm; raw/16384; 1/8 °F; 0.5 psi/count |

- **Confirmed broadcast signals (high unless noted):** 0x201 VSS ×0.01 km/h; 0x201 b6 APP; 0x106 b7 load; 0x225 b4-5 OSS; 0x230 gear code + ratio; 0x200 b7 boost 1 kPa/count (R² 0.995 up to 96 kPa); 0x420 b1 distance 0.2 m/count; 0x420 b0 ECT (hot 91–95 °C seen, no ECT PID on this drive). Medium: TFT 0x225 b7, tow/haul 0x225 b0, PRNDL 0x420 b3, 0x215 wheel-speed-like fields. **Not found in broadcasts:** TCC ratio/lock, line pressure, EOT, ICP, IPR. 0x151 not present on this truck.

See `2026-10-25_drive_analysis.md` for the full findings table and next-capture list.
