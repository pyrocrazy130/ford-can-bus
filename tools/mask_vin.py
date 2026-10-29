#!/usr/bin/env python3
"""Mask VIN character bytes in Ford Super Duty CAN logs for public release.

Broadcast:
  - 0x4FF (2005 PCM): keep b0 chunk index ('0'/'1'/'2'); printable b1.. -> 'X' (0x58)
  - 0x40A mux C100/C101/C102 (2011/2012): keep mux; printable b2.. -> 'X'
ISO-TP:
  - Mode 09 PID 02 VIN on 0x7E8/0x7E9 (first + consecutive frames)
  - Mode 22 DID F190 VIN on 0x7E8/0x7E9 (first + consecutive frames)

Timestamps, DLC, IDs, non-VIN bytes, and file size (candump) are preserved.
Usage:
  mask_vin.py candump  IN.log OUT.log
  mask_vin.py busmaster IN.log OUT.log
"""
import re, sys, hashlib, pathlib

X = 0x58

def sha256(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()

def mask_candump(src, dst):
    lines = open(src, 'rb').read().splitlines(True)
    out = []
    vin_cf_left = 0
    for raw in lines:
        line = raw.decode('latin-1')
        ends = line.endswith('\n')
        body = line.rstrip('\n')
        m = re.match(r'^(\([^)]+\)\s+\S+\s+)([0-9A-Fa-f]+)#([0-9A-Fa-f]*)(.*)$', body)
        if not m:
            out.append(raw); continue
        prefix, idhex, datahex, rest = m.groups()
        can_id = int(idhex, 16)
        if len(datahex) % 2:
            out.append(raw); continue
        data = bytearray.fromhex(datahex)
        changed = False

        if vin_cf_left > 0 and can_id in (0x7E8, 0x7E9) and data and (data[0] >> 4) == 2:
            for i in range(1, len(data)):
                if vin_cf_left <= 0: break
                if 0x20 <= data[i] <= 0x7E:
                    data[i] = X; changed = True
                vin_cf_left -= 1
        else:
            if can_id == 0x4FF and len(data) >= 2 and data[0] in (0x30, 0x31, 0x32):
                for i in range(1, len(data)):
                    if 0x20 <= data[i] <= 0x7E:
                        data[i] = X; changed = True
            if can_id == 0x40A and len(data) >= 3:
                mux = (data[0] << 8) | data[1]
                if mux in (0xC100, 0xC101, 0xC102):
                    for i in range(2, len(data)):
                        if 0x20 <= data[i] <= 0x7E:
                            data[i] = X; changed = True
            if can_id in (0x7E8, 0x7E9) and len(data) >= 4 and (data[0] >> 4) == 0 and data[1] == 0x49 and data[2] == 0x02:
                start = 4 if len(data) > 4 else 3
                for i in range(start, 1 + (data[0] & 0x0F)):
                    if i < len(data) and 0x20 <= data[i] <= 0x7E:
                        data[i] = X; changed = True
            if can_id in (0x7E8, 0x7E9) and len(data) >= 4 and (data[0] >> 4) == 1:
                if len(data) >= 4 and data[2] == 0x49 and data[3] == 0x02:
                    total = ((data[0] & 0x0F) << 8) | data[1]
                    for i in range(4, len(data)):
                        if 0x20 <= data[i] <= 0x7E:
                            data[i] = X; changed = True
                    vin_cf_left = max(0, total - (len(data) - 2))
                elif len(data) >= 5 and data[2] == 0x62 and data[3] == 0xF1 and data[4] == 0x90:
                    total = ((data[0] & 0x0F) << 8) | data[1]
                    for i in range(5, len(data)):
                        if 0x20 <= data[i] <= 0x7E:
                            data[i] = X; changed = True
                    vin_cf_left = max(0, total - (len(data) - 2))
            if can_id in (0x7E8, 0x7E9) and len(data) >= 5 and (data[0] >> 4) == 0 and data[1] == 0x62 and data[2] == 0xF1 and data[3] == 0x90:
                for i in range(4, 1 + (data[0] & 0x0F)):
                    if i < len(data) and 0x20 <= data[i] <= 0x7E:
                        data[i] = X; changed = True

        if changed:
            nl = f"{prefix}{idhex}#{data.hex().upper()}{rest}" + ('\n' if ends else '')
            out.append(nl.encode('latin-1'))
        else:
            out.append(raw)
    pathlib.Path(dst).write_bytes(b''.join(out))
    print(sha256(src), sha256(dst))

def mask_busmaster(src, dst):
    raw = open(src, 'rb').read()
    out = []
    for line in raw.splitlines(True):
        if line.endswith(b'\r\n'): ending, body = b'\r\n', line[:-2]
        elif line.endswith(b'\n'): ending, body = b'\n', line[:-1]
        else: ending, body = b'', line
        s = body.decode('latin-1')
        mm = re.search(r'0x([0-9A-Fa-f]+)\s+s\s+(\d+)\s+((?:[0-9A-Fa-f]{2}\s*)+)', s)
        if not mm:
            out.append(line); continue
        can_id = int(mm.group(1), 16)
        dlc = int(mm.group(2))
        parts = mm.group(3).split()
        if len(parts) < dlc:
            out.append(line); continue
        data = bytearray(int(x, 16) for x in parts[:dlc])
        if not (can_id == 0x40A and len(data) >= 3 and ((data[0] << 8) | data[1]) in (0xC100, 0xC101, 0xC102)):
            out.append(line); continue
        for i in range(2, len(data)):
            if 0x20 <= data[i] <= 0x7E:
                data[i] = X
        newhex = ' '.join(f'{b:02X}' for b in data)
        pos = mm.start(3)
        tmp = s[pos:]
        for tok in parts[:dlc]:
            idx = tmp.find(tok)
            tmp = tmp[idx + len(tok):]
        new_s = s[:pos] + newhex + tmp
        out.append(new_s.encode('latin-1') + ending)
    pathlib.Path(dst).write_bytes(b''.join(out))
    print(sha256(src), sha256(dst))

if __name__ == '__main__':
    if len(sys.argv) != 4 or sys.argv[1] not in ('candump', 'busmaster'):
        sys.exit('usage: mask_vin.py {candump|busmaster} IN OUT')
    (mask_candump if sys.argv[1] == 'candump' else mask_busmaster)(sys.argv[2], sys.argv[3])
