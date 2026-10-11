"""Read BIGF/BIG4 indexes without extracting or executing archive contents."""
from dataclasses import dataclass
import mmap
from pathlib import Path
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


def replace_file(source, target, replacements):
    """Stream a large original archive, keeping index names, order and padding."""
    if Path(source).resolve() == Path(target).resolve():
        raise ValueError('source and target must differ')
    with open(source, 'rb') as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
        entries = read_index(data)
        if set(replacements) - {e.key for e in entries}:
            raise ValueError('replacement path absent from archive')
        ordered = sorted(entries, key=lambda e: e.offset)
        header = bytearray(data[:ordered[0].offset])
        cursor = ordered[0].offset
        output_offset = len(header)
        for entry in ordered:
            output_offset += entry.offset - cursor
            size = len(replacements[entry.key]) if entry.key in replacements else entry.size
            struct.pack_into('>II', header, entry.row, output_offset, size)
            output_offset += size
            cursor = entry.offset + entry.size
        output_offset += len(data) - cursor
        struct.pack_into('<I', header, 4, output_offset)
        with open(target, 'wb') as output:
            output.write(header)
            cursor = ordered[0].offset
            for entry in ordered:
                output.write(data[cursor:entry.offset])
                if entry.key in replacements:
                    output.write(replacements[entry.key])
                else:
                    for offset in range(entry.offset, entry.offset + entry.size, 1024 * 1024):
                        output.write(data[offset:min(offset + 1024 * 1024, entry.offset + entry.size)])
                cursor = entry.offset + entry.size
            output.write(data[cursor:])
    with open(target, 'rb') as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
        read_index(data)


def check_replacement(before, after, replacements):
    """Prove only declared payloads and necessary index length/offsets changed."""
    old, new = read_index(before), read_index(after)
    if [e.name for e in old] != [e.name for e in new]:
        raise ValueError('archive names/order changed')
    if set(replacements) - {e.key for e in old}:
        raise ValueError('replacement path absent from archive')
    targets = {e.key: e for e in new}
    first = min(e.offset for e in old)
    header = bytearray(before[:first])
    struct.pack_into('<I', header, 4, len(after))
    old_cursor = new_cursor = first
    delta = 0
    for entry in sorted(old, key=lambda e: e.offset):
        target = targets[entry.key]
        expected = replacements.get(entry.key)
        size = len(expected) if expected is not None else entry.size
        if target.offset != entry.offset + delta or target.size != size:
            raise ValueError('unexpected payload offset/size: ' + entry.key)
        if before[old_cursor:entry.offset] != after[new_cursor:target.offset]:
            raise ValueError('archive padding changed')
        original = before[entry.offset:entry.offset + entry.size]
        actual = after[target.offset:target.offset + target.size]
        if actual != (original if expected is None else expected):
            raise ValueError('unexpected payload content: ' + entry.key)
        struct.pack_into('>II', header, entry.row, target.offset, target.size)
        old_cursor, new_cursor = entry.offset + entry.size, target.offset + target.size
        delta += size - entry.size
    if len(after) != len(before) + delta or before[old_cursor:] != after[new_cursor:]:
        raise ValueError('archive trailing bytes changed')
    if after[:first] != header:
        raise ValueError('archive header bytes changed')
