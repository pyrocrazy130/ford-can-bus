# ford-can-bus — Ford Super Duty CAN recordings

Public archive of CAN / OBD captures used for a 2005 F-350 6.0L ↔ 2012 Lariat cluster/electronics swap (CAN translator project).

**VINs in these public files are masked.** Broadcast VIN frames (`0x4FF` on the 2005, `0x40A` C100–C102 on the 2011) and Mode 09 VIN replies have every VIN character replaced with ASCII `X` (`0x58`). Documentation writes Bo's VIN as `1FTWX31P25E******` and the friend's as `1FT8W3BT4BE******`. Unmasked originals remain in the private [can-translator](https://github.com/pyrocrazy130/can-translator) repo. See each folder's README for per-file sha256 (original vs public).

## Layout

| Path | Contents |
|---|---|
| `2026-2005-hscan/` | **Bo's 2005 F-350 6.0L** HS-CAN (500k, OBD 6/14) — 2026-10-24 KOEO, 2026-10-25 synced parked capture, 2026-10-25 highway drive + FORScan CSV/FSL + analysis |
| `2020-mscan-truck/` | **Friend's 2011 F-350 6.7L** MS-CAN (~125k) truck captures and wake-set excerpts (2020-06-02) |
| `2020-mscan-bench/` | Bench MS-CAN with 2012-era HVAC (± DCSM) modules (2020-06-04 / 06-10 / 06-12) |
| `dbc/` | Decoded DBC copies (VIN strings scrubbed): 2005 PCM HS, 2011–2012 HS, 2012 MS |
| `tools/mask_vin.py` | Script used to produce the masked public CAN logs |
| `Drive around the block.log` | Friend's 2011 HS-CAN BUSMASTER drive log (2021-06-08) — **VIN masked** |
| `candump-2020-06-02_191322.log` / `191626.log` | Historical MS truck candumps (kept at repo root; **VIN masked**) |
| `0x5xx message HVAC and DCSM` | Historical bench NM log (no VIN; also under `2020-mscan-bench/`) |

## Quick facts

| Capture | Vehicle | Bus | Interface | Listen-only? |
|---|---|---|---|---|
| 2026-10-24 / 10-25 sync | 2005 F-350 6.0L | HS 500k pins 6/14 | USB2CAN-X2 `can0` + InnoMaker OBD-4xDB9 | yes (TX 0) |
| 2026-10-25 drive | 2005 F-350 6.0L | HS 500k | USB2CAN-X2 **`can1`** (can0 empty) | yes (TX 0) |
| Drive around the block | Friend 2011 6.7L | HS 500k | BUSMASTER | capture of truck traffic |
| 2020-06-02 MS truck | Friend 2011 6.7L | MS ~125k | candump | truck traffic (+ excerpts) |
| 2020-06 bench | 2012 HVAC/DCSM on bench | MS ~125k | candump | **no** — tool TX for wake/keep-alive tests |

**Ground jumper** on the 2026 USB2CAN sessions was never confirmed.  
**2005 alignment offsets** for FORScan CSV ↔ candump: sync `1792947636.274`; drive **`1792955781.572`** (not the first-poll timestamp). Details in `2026-2005-hscan/README.md`.

## What is *not* here

- Private can-translator tooling, signal-finder outputs, plots, and git history.
- Unmasked VIN bytes.
- Anything from Bo's company accounts.

## License / use

Recordings are provided for reverse-engineering and interoperability work on these specific vehicles. No warranty. Do not use them to identify or track a person or vehicle.
