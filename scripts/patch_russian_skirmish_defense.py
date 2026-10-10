#!/usr/bin/env python3
"""Targeted Russia skirmish AI base defense fix for Project X BIGF archives.

Only Data/INI/Default/AIData.ini is modified. All other 621 archived
payloads, entry names, ordering and unrelated metadata are preserved.
"""
import argparse
import hashlib
from pathlib import Path
import re
import struct

SOURCE_SHA256 = "214a17c3d501ec756d82f375353e329dfe0e7e074dc9f5f9e2d42d8fbe6f5fe4"
EXPECTED_OUTPUT_SHA256 = "83c6616cbf7a45f0979edebd34d22a157d76751d03359bf62e62ca184d92bb25"
TARGET = "data\\ini\\default\\aidata.ini"
OLD = b"Russia_RussiaKashtan"
NEW = b"RussiaKashtan"

def index_big(data):
    if len(data) < 20 or data[:4] != b"BIGF" or struct.unpack_from("<I", data, 4)[0] != len(data):
        raise ValueError("invalid BIGF header or file length")
    count = struct.unpack_from(">I", data, 8)[0]
    if not 1 <= count <= 4000:
        raise ValueError("invalid BIG entry count")
    pos = 16
    result = []
    for _ in range(count):
        if pos + 8 >= len(data):
            raise ValueError("truncated BIG index")
        row = pos
        offset, size = struct.unpack_from(">II", data, pos)
        pos += 8
        end = data.find(b"\0", pos, min(pos + 8192, len(data)))
        if end < 0 or end == pos:
            raise ValueError("invalid BIG entry name")
        filename = data[pos:end].decode("latin-1").replace("/", "\\")
        pos = end + 1
        if offset < pos or offset + size > len(data):
            raise ValueError("invalid BIG payload extent")
        result.append((filename, row, offset, size))
    ordered = sorted(result, key=lambda x: x[2])
    start = ordered[0][2]
    if start < pos or ordered[-1][2] + ordered[-1][3] != len(data):
        raise ValueError("invalid first or last BIG payload")
    cursor = start
    for _, _, offset, size in ordered:
        if offset != cursor:
            raise ValueError("overlapping or noncontiguous payloads")
        cursor += size
    if len({name.lower() for name, *_ in result}) != len(result):
        raise ValueError("duplicate BIG path")
    return result, start

def patch(data, enforce_source=True):
    if enforce_source and hashlib.sha256(data).hexdigest() != SOURCE_SHA256:
        raise ValueError("refusing to edit unexpected Project X LFS archive")
    entries, first_offset = index_big(data)
    matching = [row for row in entries if row[0].lower() == TARGET]
    if len(matching) != 1 or len(entries) != 622:
        raise ValueError("unexpected Project X index")
    if not any(re.search(rb"(?m)^\s*Object\s+RussiaKashtan\s*$", data[off:off+size])
               for path, _, off, size in entries if path.lower().endswith(".ini")):
        raise ValueError("RussiaKashtan object definition absent")
    name, _, offset, size = matching[0]
    contents = data[offset:offset+size]
    begin = contents.index(b"  SideInfo AmericaLaserGeneral ; Russia")
    finish = contents.index(b"  SideInfo AmericaSuperWeaponGeneral", begin)
    side = contents[begin:finish]
    expected = re.compile(rb"(?m)^([ \t]*BaseDefenseStructure1[ \t]+)Russia_RussiaKashtan([ \t]*\r?)$")
    if len(expected.findall(side)) != 1 or side.count(OLD) != 1:
        raise ValueError("unexpected Russian defense line")
    corrected = contents[:begin] + side.replace(OLD, NEW) + contents[finish:]
    if OLD in corrected[begin:begin+len(side)] or NEW not in corrected[begin:begin+len(side)]:
        raise ValueError("Russian defense reference not repaired")
    output = bytearray(data[:first_offset])
    cursor = first_offset
    for filename, row, off, length in sorted(entries, key=lambda item: item[2]):
        payload = corrected if filename.lower() == TARGET else data[off:off+length]
        struct.pack_into(">II", output, row, cursor, len(payload))
        output.extend(payload)
        cursor += len(payload)
    struct.pack_into("<I", output, 4, len(output))
    check, _ = index_big(output)
    old_payloads = {n:data[off:off+size] for n, _, off, size in entries}
    new_payloads = {n:output[off:off+size] for n, _, off, size in check}
    changed = [n for n in old_payloads if old_payloads[n] != new_payloads[n]]
    if changed != [name] or len(data)-len(output) != len(OLD)-len(NEW):
        raise ValueError("unexpected change outside the Russian defense setting")
    if enforce_source and hashlib.sha256(output).hexdigest() != EXPECTED_OUTPUT_SHA256:
        raise ValueError("output does not match validated deterministic hash")
    return bytes(output)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.input.resolve() == args.output.resolve():
        parser.error("input and output paths must differ")
    data = args.input.read_bytes()
    result = patch(data)
    args.output.write_bytes(result)
    print("PASS: fixed RussiaKashtan base-defense reference; 622 BIG entries, exactly one modified.")
    print("SHA256", hashlib.sha256(result).hexdigest())

if __name__ == "__main__":
    main()
