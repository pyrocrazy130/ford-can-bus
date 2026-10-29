# Friend's 2011 F-350 — MS-CAN truck captures (2020-06-02)

**Vehicle:** Friend's 2011 Ford F-350 6.7L KR 4x4. VIN on the bus (`0x40A` mux C100/C101/C102) is **masked** in these public copies (VIN character bytes → ASCII `X` / `0x58`; mux id bytes kept). The same VIN was already present in the older root files of this repo; those root copies are also masked now.

**Bus:** MS-CAN ~125 kbit/s (back-to-back 8-byte frames ≈ 1.0 ms).  
**Where:** Truck bus (full NM ring 01→03→0B→0C→27→3B→41).  
**Source:** Copies from private `can-translator/captures/2020-mscan/` (and near-duplicates of the historical root candumps). File names keep Bo's upload tags (`srcXXXX`).

Times are America/Los_Angeles (PDT). Epoch in each filename is the first-frame timestamp.

## VIN masking
- Frames: `0x40A` with mux `C100` / `C101` / `C102` only.
- Replacement: printable VIN ASCII → `0x58` (`X`). Mux bytes and non-printable bytes unchanged.
- Tool: `../tools/mask_vin.py`.
- Docs write the VIN as `1FT8W3BT4BE******`.

| File (short) | Original sha256 | Public (masked) sha256 |
|---|---|---|
| `…_191322_…_srcNNKD.log` (clean variant of root 191322) | `ea906e64f8de01c39db1ce932946b33ad5ac952c84879f10c8bbf81a7ff5d870` | `c86a55e2a29b23c45e8ca73496f0832f19bcea1a3302dc27644a66d15822704b` |
| `…_191644_…_src5N23.log` (clean variant of root 191626) | `418dd721b231650ae9812c478a902675cdb7ceac6c724c15ef0bce2e6bec88b8` | `f64d4d6fd0621c16b5fcc5abaa95b5c2fbb7235049e56c69a310ee5993f309be` |
| `…_191817_…_KOES_51s_src22GEX.log` | `aa95ee49454c3b0a225c5d9c2c5cc11daf5eb50a49ee582dcce056e673a4d0fb` | `fbfebfa01f9ad62b9d29695a5c492eb198226cad5d10ddaf434f6628d9833363` |
| `…_srcPASE.save` (nano emergency save of src22GEX) | `8e3cb588d3737b58e5221122a1b75bff4f30b1fa37eea274aef4b848c52f2269` | `332a6e898e161955715834c3676d41a9e0223351b7861d5bf8955af1e85888f4` |

Replay excerpts that contain no VIN frames are byte-identical to the private copies. `…_first50_src30XZ.log` did contain a VIN frame and is masked.

## What each capture is

| File | Frames | Notes |
|---|---|---|
| `…_191322_…_srcNNKD.log` | ~13k | Key-off → key in → KOES, HVAC/seats traffic. Cleaner than the root `candump-2020-06-02_191322.log` (no header; FD-style `##0` lines appear as normal frames). |
| `…_191644_…_src5N23.log` | ~5.5k | Seat-memory / key-off. Cleaner near-duplicate of root `candump-2020-06-02_191626.log`. |
| `…_191817_…_src22GEX.log` | 6427 | Full KOES, 51.3 s, starts ~40 s after the 19:16 log ends. |
| `…_srcPASE.save` | 6427 | nano `.save` of src22GEX mid-edit (3 lines differ; kept for line-57 reference). |
| `…_replay-excerpt_first{10,20,30,40,50}_*.log` | 10–50 | Prefixes of src22GEX used while searching for a wake set. |
| `…_wakeset10_frames21-30_src2Z6G.log` | 10 | Forum "wake set": 3E2, 40A, 423, 425, 426, 42C, 10D, 3A0, 3B2, 3B3. |
| `…_wakeset9_*_no3E2` / `*_no3B3` | 9 | Leave-one-out wake-set variants. |

Full narrative of these experiments (wake / keep-alive / seat climate 0x124) is in the private can-translator `captures/README.md` and `dbc/README.md`. Public DBC: `../dbc/ford_2012_superduty_mscan.dbc`.
