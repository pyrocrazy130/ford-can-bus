# Bench MS-CAN captures — 2012-era HVAC / DCSM modules (2020-06)

**Modules:** Isolated HVAC (NM node 03) and, on 2020-06-12, HVAC + DCSM (node 27). Origin of the modules is unknown (no VIN on the bus). They are the parts Bo uses toward the 2012 Lariat cluster swap into the 2005.

**Bus:** MS-CAN ~125 kbit/s on Bo's bench. Interface `can1` (06-04) or `can0` (06-10/06-12).  
**These logs include transmitted frames** from Bo's tool (`0x000`, `0x501`, `0x580`, `0x583`, `0x3A0`, and wake-set replays) — they are **not** listen-only.

No VIN was present; files are byte-identical to the private can-translator copies (masker still run). The historical root file `0x5xx message HVAC and DCSM` is also copied here as `2020-06-12_1804_bench_HVAC+DCSM_0x5xx_message.log`.

## Highlights

| File | What |
|---|---|
| `…_06-04_…_wakeset-replay-2runs…_src22FF.log` | Two wake-set replays; module answers within 8–58 ms; one-shot wake lasts ~5.5 s. |
| `…_06-10_…_tx-501-030200_stays-awake…` | `501#030200` @ 200 ms keeps HVAC awake (stable). |
| `…_06-10_…_tx-3A0-200ms_stays-awake…` | `3A0` alone @ 200 ms also keeps it awake (LimpHome). Seat-climate presses visible in 0x124. |
| `…_06-10_…_tx-000-*` / `tx-580-*` / `tx-583-*` | Negative keep-awake tests. |
| `…_06-12_…_tx-501-…_ring-01-03-27…` | HVAC+DCSM with tool as node 01. |
| `…_06-12_…_tx-3A0-…_ring-03-27…` | No 0x501: 03 and 27 ring each other; seat climate on b0 and b1. |

`0x124` seat climate encoding (one-hot per seat): `80/40/20` = mode A levels 3/2/1, `10/08/04` = mode B levels 3/2/1, `02` = off. Which mode is heat vs cool, and which byte is driver, is unconfirmed.
