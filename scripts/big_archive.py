"""Read BIGF/BIG4 indexes without extracting or executing archive contents."""
from dataclasses import dataclass
import struct


@dataclass(frozen=True)
class Entry:
    name: str
    row: int
    offset: int
    size: int

    @property
    def key(self):
        return self.name.replace("\\", "/").lower()


def read_index(data):
    if len(data) < 16 or data[:4] not in (b"BIGF", b"BIG4"):
        raise ValueError("invalid BIG magic/header (is Git LFS downloaded?)")
    length = struct.unpack_from("<I", data, 4)[0]
    count, header_size = struct.unpack_from(">II", data, 8)
    if length != len(data) or not 0 < count <= 50000:
        raise ValueError("invalid BIG length/count")
    if not 16 <= header_size <= len(data):
        raise ValueError("invalid BIG index size")
    pos, entries, keys = 16, [], set()
    for _ in range(count):
        if pos + 8 >= header_size:
            raise ValueError("truncated BIG index")
        row = pos
        offset, size = struct.unpack_from(">II", data, pos)
        pos += 8
        end = data.find(b"\0", pos, min(pos + 8192, header_size))
        if end <= pos:
            raise ValueError("invalid BIG filename")
        entry = Entry(data[pos:end].decode("latin-1"), row, offset, size)
        parts = entry.key.split("/")
        if any(p in ("", ".", "..") or ":" in p for p in parts):
            raise ValueError("unsafe BIG path")
        if entry.key in keys:
            raise ValueError("duplicate BIG path")
        if offset < header_size or offset + size > len(data):
            raise ValueError("invalid BIG payload extent")
        keys.add(entry.key)
        entries.append(entry)
        pos = end + 1
    cursor = header_size
    for entry in sorted(entries, key=lambda e: e.offset):
        if entry.offset < cursor:
            raise ValueError("overlapping BIG payloads")
        cursor = entry.offset + entry.size
    return entries


def payloads(data):
    return {e.key: bytes(data[e.offset:e.offset + e.size]) for e in read_index(data)}


def write_big(files):
    """Build a deterministic BIGF archive from named byte payloads."""
    items = sorted(files.items(), key=lambda item: item[0].replace('\\', '/').lower())
    names = [name.replace('\\', '/').encode('latin-1') for name, _ in items]
    if any(b'\0' in name for name in names):
        raise ValueError('NUL in BIG filename')
    header_size = 16 + sum(9 + len(name) for name in names)
    length = header_size + sum(len(data) for _, data in items)
    output = bytearray(b'BIGF' + struct.pack('<I', length) + struct.pack('>II', len(items), header_size))
    offset = header_size
    for name, (_, data) in zip(names, items):
        output.extend(struct.pack('>II', offset, len(data)) + name + b'\0')
        offset += len(data)
    output.extend(b''.join(data for _, data in items))
    read_index(output)
    return bytes(output)


def replace_payloads(data, replacements):
    """Keep index names/order/padding; update only offsets, sizes and file length."""
    entries = read_index(data)
    if set(replacements) - {e.key for e in entries}:
        raise ValueError("replacement path absent from archive")
    ordered = sorted(entries, key=lambda e: e.offset)
    cursor = ordered[0].offset
    output = bytearray(data[:cursor])
    for entry in ordered:
        if entry.offset != cursor:
            raise ValueError("repacking requires contiguous source payloads")
        cursor = entry.offset + entry.size
        contents = replacements.get(entry.key, data[entry.offset:cursor])
        struct.pack_into(">II", output, entry.row, len(output), len(contents))
        output.extend(contents)
    if cursor != len(data):
        raise ValueError("unexpected trailing archive data")
    struct.pack_into("<I", output, 4, len(output))
    read_index(output)
    return bytes(output)
