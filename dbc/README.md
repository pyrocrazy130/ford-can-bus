# DBC files for the CAN translator project

These files record what we have decoded so far. Each one describes one bus:

| File | Bus | Speed | Basis | Messages / signals |
|---|---|---|---|---|
| `ford_2011-2012_superduty_hscan.dbc` | HS-CAN, cluster side (what the 2012 Lariat cluster expects) | 500k | Drive log 2021-06-08, recorded on a **friend's 2011 F-350 6.7L** (VIN `1FT8W3BT4BE******`) | 78 / 117 |
| `ford_2012_superduty_mscan.dbc` | MS-CAN, body/HVAC/seats | 125k | **Truck bus:** MS candumps 2020-06-02 19:13/19:16/19:18 from the same friend's 2011 (same VIN in 0x40A). **Bench:** the 2020-06-04 wake-set replay and the 2020-06-12 HVAC+DCSM log, both with module(s) of unknown origin. Plus the 2020 forum thread. Captures are indexed in `../captures/README.md` | 46 / 101 |
| `ford_2005_superduty_pcm_hscan.dbc` | 2005 F-350 6.0L PCM HS-CAN (the translator's input side) | 500k | **Bo's 2005 (VIN `1FTWX************`):** 2026-10-24 KOEO, 2026-10-25 synchronized (parked) and 2026-10-25 drive HS-CAN + FORScan captures, plus the translator code. See `../captures/2026-2005/2026-10-25_sync_analysis.md` and `2026-10-25_drive_analysis.md` | 14 / 64 |

**About the vehicles.** Bo's cluster and electronics come from a mostly parted-out 2012 F-350 Lariat. Every capture we have so far comes from the friend's 2011. The 2011 and 2012 Super Duty are assumed to share a layout, but that hasn't been checked. A bench capture of the 2012 parts would settle it. The MS file is named "2012" because it targets Bo's 2012 parts; its data is from the 2011.

**How the bus speeds were established.**
- **MS-CAN = 125k (high confidence).** In the MS candumps, back-to-back 8-byte frames are about 1.0 ms apart, which is roughly 125 bits at 125 kbit/s.
- **HS-CAN = 500k.** That's what the BUSMASTER log header says, and it's what the translator uses.

## Conventions
- **Byte and bit order.** Byte numbers b0–b7 match the hex dump order. Ford multi-byte signals are big-endian (Motorola, `@0`). The DBC start bit is the bit number of the signal's most significant bit (b0 bit 7 = 7, b2 bit 7 = 23, and so on). The NM opcode flags are single bits, written little-endian (`@1`).
- **Confidence and source are recorded twice**, so they show up in any tool:
  - In every `CM_` comment, which starts with `[conf=high|medium|low] [src=...]`.
  - As attributes: `MsgConfidence`/`MsgSource` on messages and `SigConfidence`/`SigSource` on signals.

  The levels mean:
  - **high**: checked against physics or a second source. Example: speed vs gear ratio, or the VIN.
  - **medium**: consistent behaviour, or Bo confirmed it, but the scaling or meaning is only partly proven.
  - **low**: a hypothesis or a guess. Temperature offsets and anything marked "candidate" fall here.
- **Periods** are in `GenMsgCycleTime` (ms), taken as the median observed gap. Event-driven or bursty messages have no cycle time.
- **Undecoded messages** are a single `RAW_xxx_Data` signal covering the whole payload. Their comment records the period, which bytes vary, and a typical payload. To decode one, replace the raw signal with real signals.
- Units: rpm, km/h, degC, s, and `raw` where the scaling is unknown. Example: the 0x407 boost value is kept raw on purpose.

## Key decodes (HS)
- **0x201:** RPM = b0-1 / 4 and speed = b2-3 × 0.01 km/h (both high confidence). b4-5 is unknown and looks load-related; b6 = 0x18.
- **0x230:**
  - b0 high nibble = gear (0 = P/N, 1–3 seen, E = reverse); b0 low nibble = shift state.
  - b3 = trans temp. The identity is medium confidence; the −60 offset is low.
  - b5-6 × 0.001 = gear ratio (6R140).
- **0x156:** b0 = ECT. The identity is medium; the −60 offset is low. b1 may be oil temp.
- **0x407:** the boost gauge (Bo confirmed). b0-1 is raw: 300 at idle, 318 on the drive. 1/3 kPa absolute is only a hypothesis. b2 is unknown and moves opposite to load.
- **0x415:** b0-1 = speed × 0.01 km/h, the same as 0x201.
- **0x430:** b3-5 is an odometer candidate (217206 → 217207; unit unknown).
- **0x40A:** multiplexed on b0-1.
  - C100, C101 and C102 carry the VIN, in ASCII.
  - C000 b3-6 is a 0.1 s real-time clock, with its epoch around 2010-10-16.
- **Network-management keep-alives:** 0x581, 0x591, 0x5A0 and 0x5B3, every 1 s.

## Key decodes (MS)
- **0x3A0:** Bo sent `45 00 80 02 89 24 00 00` every 200 ms to enable the HVAC controls (forum). The truck itself sends it every 1 s; b0 is 0x11 with the key off.
- **NM ring:**
  - The ring runs 0x501 → 0x503 → 0x50B → 0x50C → 0x527 → 0x53B → 0x541. In each frame, b0 is the next node and b1 is an OSEK-style opcode (01 Alive, 02 Ring, 04 LimpHome, 10 SleepInd, 20 SleepAck).
  - On the bench, Bo's tool played node 01 and sent `501 03 02 00` every 200 ms. The modules answered as 0x503 and 0x527.
- **Wake set** (forum): 3E2, 40A, 423, 425, 426, 42C, 10D, 3A0, 3B2 and 3B3. 3B3 reads `00 43 05 12 00 00 00 38` with KOES.
  - These are exactly **frames 21–30 of the 19:18 KOES truck capture**, i.e. one 1-second burst of periodic frames. They were probably found by replaying the first 10/20/30/40/50 frames (inferred).
- **Wake vs. keep-alive vs. enable**, from the 2020-06-04 bench replay. The interpretation is inferred; the timings are measured.
  - **Wake:** the module (NM node 03) answered within 8–58 ms of the replayed burst. In run 2 it woke *before* 0x3A0 was sent. So plain bus traffic wakes it, and 0x3A0 isn't needed for the wake.
  - **Without an NM partner:** it alternates `503 03 01` (Alive) and `503 03 02` (Ring to itself). At +2.46 s it switches to `03 04` (LimpHome, 1 Hz). At +5.48 s it sends `03 14` (LimpHome + SleepInd) and goes quiet. Both runs behaved identically.
  - **So a one-shot wake lasts about 5.5 s.** Keeping it up needs either an NM ring partner (Bo's `501 03 02 00` every 200 ms, as on the 06-12 bench) or continuous traffic such as 0x3A0 every 200 ms (forum).
- **Keep-awake tests**, 2020-06-10/12 bench, HVAC alone or HVAC+DCSM. These are measured.
  - **These kept it awake:**
    - `501 03 02 00` every 200 ms. HVAC replies `503 01 12 00`, and it's stable.
    - `3A0 45 …` every 200 ms. HVAC stays in LimpHome at 1 Hz but never sleeps. With HVAC+DCSM, nodes 03 and 27 ring each other. They sleep about 5.4 s after 3A0 stops.
  - **These did not:**
    - `580/583 03 01` every 200 ms: it sleeps after about 5 s.
    - Non-NM traffic (`000#…`): it wakes and sleeps in a 7.4 s cycle (5.5 s on, ~1.9 s off).
    - One-shot wake sets without 3A0: 5.5 s awake.
  - So 0x3A0 b0 = 0x45 is most likely the run/power-mode signal the modules use to stay awake (medium).
- **0x124 = climate-seat (TED) request from the HVAC module** (medium). b0 and b1 are one-hot per seat:
  - 02 = off
  - 80/40/20 = mode A levels 3/2/1
  - 10/08/04 = mode B levels 3/2/1
  - Which mode is heat and which is cool is unknown, and which byte is driver vs passenger is unknown.
- **HVAC module outputs:** 0x124, 0x35E, 0x3E7 and 0x41A are **sent by the module**, not something Bo had to send. After the wake-set replay, the bench module started sending them on its own at 1 s.
- **0x583** `00` (DLC 1): seen once after wake on the bench. 0x581/0x583 in the truck logs are bit-flipped 0x501/0x503 copies, not this.
- **0x466:** event bursts on the truck (19:18 KOES log). Each burst is 10–20 identical copies about 1 ms apart. Kept raw.
- **HVAC periodic frames:** 0x124, 0x35E, 0x3E7 and 0x41A at about 1 s.
- **0x333:** multi-frame display text, e.g. "Bluetooth Connected".
- **The 2020 MS logs are noisy.** They contain many single-bit-corrupted frames, so one-off IDs were left out. Some of the "FD/RTR/extended" oddities are probably logging artifacts: Bo's copy of the 19:16 log (src5N23) has those lines as normal frames where the repo copy shows `##0`. The remaining decode failures in the check are corrupted 0x40A mux values plus one malformed 0x50C in the repo copy.

## Key decodes (2005 PCM HS)
Sync (parked) and drive captures from 2026-10-25; details are in `../captures/2026-2005/2026-10-2*_analysis.md`.
- **0x201:**
  - RPM = 12-bit (b0 low nibble + b1) × 1 rpm (high).
  - VSS = b4-5 × 0.01 km/h (high).
  - APP = b6 × 100/256 % (high, 0–31 % seen).
  - b2-3 − 0x4000 ≈ rpm/s (low).
  - b0.7 is a flag, set during the crank and during coast-downs (low).
- **0x106:** b7 = engine load × 100/255 % (high).
- **0x200:** b7 = boost, 1 kPa/count above ~93 kPa (high; R² 0.995 up to 96 kPa). b0 and b4 are decel/TCC/pedal states (low).
- **0x225:**
  - b4-5 = output shaft speed in rpm (high).
  - b7 = TFT °C + 40 (medium; only 3 values seen hot, and the cold free-rev spikes are unexplained).
  - b0 = 0x60 while tow/haul is on (medium).
  - b2-3 is a second RPM (medium).
- **0x230:** b0 low nibble = TCM gear code 1/2/3/5/6 (code 5 = 4th, 6 = 5th); 0x10 = R, 0xF0 = P/N (high). b1.0 + b2 = gear ratio × 0.01 (high).
- **0x420:**
  - b0 = ECT °C + 40 (high; 19–39 °C confirmed, 91–95 °C seen without a reference).
  - b1 = distance counter, 0.2 m/count (high).
  - b2 = fuel counter (medium).
  - b3 = PRNDL (medium).
  - b4 = 0x40.
- **0x215:** three (raw − 10106) × 0.01 km/h speed fields, possibly wheel speeds (medium).
- **0x430:** b0 is a fuel-level candidate (low). b1 is unknown and is **not** voltage.
- **0x4FF:** VIN in 3 ASCII chunks (high).
- **TCM DIDs** are on 7E1/7E9 (gear, OSS, TCC ratio, TFT, desired line pressure); see `../tools/signal-finder/sigfind/pid_table.py`.

## Tools
- `tools/gen_2005_pcm_dbc.py [out dir]` writes `ford_2005_superduty_pcm_hscan.dbc` and is the source of truth for it. It needs no logs; `gen_dbc.py` calls it.
- `tools/gen_dbc.py <ford-can-bus dir> <out dir> [captures/2020-mscan]` writes the original version of all three files from the logs plus the hand-written definitions in the script. `tools/dbclib.py` is the DBC writer it uses.
- `tools/check_dbc.py <dbc dir> <ford-can-bus dir> [captures/2020-mscan]` parses every DBC strictly with cantools and decodes all the logs. It prints the RPM, speed, gear/ratio, temperature, boost, odometer and VIN checks. The latest run is in `tools/check_output.txt`.
- `tools/candump_stats.py <candump files>` prints per-ID periods and payload statistics.
- `../tools/signal-finder/` proposes new signals automatically: it correlates every byte field with OBD PID replies or known signals and writes a report plus a draft DBC fragment (`[conf=low] [src=signal-finder]`). See its README for the capture recipe.
- Setup: `python3 -m venv .venv && .venv/bin/pip install cantools` (matplotlib is optional).

## Adding a finding
1. Change the definition in `tools/gen_dbc.py` and regenerate. That keeps comments and attributes consistent. Alternatively, edit the .dbc directly (SavvyCAN, Kvaser Database Editor, or a text editor). If you do, stop regenerating, or copy the edit back into the script.
2. Every new or changed signal needs a `CM_` comment starting with `[conf=...] [src=...]`, plus the matching `SigConfidence`/`SigSource` attributes. A source names the capture (file and date, truck, bus) or the person ("Bo 2026-MM-DD").
3. Raise confidence only with evidence. Examples: a scan-tool PID logged alongside the bus, a known physical value, or a second capture.
4. Run `tools/check_dbc.py` to confirm the files still parse and the spot-check values still look sane.
5. If a finding changes what the translator should send, note it in `../drive-log-check/README.md`.

## Biggest unknowns
- Whether the 2012 Lariat cluster matches the friend's 2011 HS layout. This needs a bench capture of the 2012 parts.
- **2005 PCM side:** still open are the TCC lock/slip broadcast, line pressure, EOT/ICP/IPR/VPWR/FICM (none found in broadcasts), 0x430 b1, the brake and fuel-level candidates, the boost zero (baro or fixed), the TFT spikes, and the hot ECT end.
- **Boost scaling in 0x407:** needs a known boost reading during a capture.
- **Temperature offsets** (0x156 b0/b1, 0x230 b3): −60 or −40.
- **0x430:** is it the odometer, and in km or miles?
