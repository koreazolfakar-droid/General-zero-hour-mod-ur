#!/usr/bin/env python3
"""Validate the texture-only overlay, DDS mip chains and original alpha masks."""
import argparse
import hashlib
import json
import mmap
from pathlib import Path
import struct
from big_archive import payloads, read_index
from build_russian_visuals import ARCHIVE, build

def require(condition, message):
    if not condition:
        raise ValueError(message)

def dds_info(data):
    require(len(data) >= 128 and data[:4] == b'DDS ', 'invalid DDS header')
    require(struct.unpack_from('<I', data, 4)[0] == 124, 'invalid DDS header size')
    flags, height, width, linear, depth, count = struct.unpack_from('<6I', data, 8)
    require(width > 0 and height > 0 and width <= 4096 and height <= 4096,
            'invalid DDS dimensions')
    require(width & (width - 1) == 0 and height & (height - 1) == 0, 'DDS must be power of two')
    require(depth == 0, 'volume DDS not supported')
    require(struct.unpack_from('<I', data, 76)[0] == 32, 'invalid DDS pixel format size')
    require(struct.unpack_from('<I', data, 80)[0] & 4, 'DDS FourCC flag absent')
    fourcc = data[84:88].decode('ascii', errors='replace')
    require(fourcc in ('DXT1', 'DXT3'), 'unsupported DDS codec')
    block_size = 8 if fourcc == 'DXT1' else 16
    require(count == max(width, height).bit_length(), 'incomplete DDS mip chain')
    require(flags & 0x20000 and flags & 0x80000, 'DDS mip/linear flags absent')
    caps, caps2 = struct.unpack_from('<II', data, 108)
    require(caps & 0x401008 == 0x401008 and caps2 == 0, 'invalid DDS mip/texture caps')
    levels, cursor, w, h = [], 128, width, height
    for _ in range(count):
        size = ((w + 3) // 4) * ((h + 3) // 4) * block_size
        levels.append((w, h, cursor, size)); cursor += size
        w, h = max(1, w // 2), max(1, h // 2)
    require(linear == levels[0][3], 'incorrect DDS linear size')
    require(cursor == len(data), 'truncated or trailing DDS mip data')
    return {'width':width, 'height':height, 'fourcc':fourcc, 'mipmaps':count, 'levels':levels}

def alpha_bytes(data, level):
    w, h, offset, _ = level
    codec = data[84:88]
    block_size = 8 if codec == b'DXT1' else 16
    alpha = bytearray(w * h)
    for by in range((h + 3) // 4):
        for bx in range((w + 3) // 4):
            start = offset + (by * ((w + 3) // 4) + bx) * block_size
            if codec == b'DXT3':
                bits = struct.unpack_from('<Q', data, start)[0]
                values = [(bits >> (4 * i) & 15) * 17 for i in range(16)]
            else:
                c0, c1, bits = struct.unpack_from('<HHI', data, start)
                values = [0 if c0 <= c1 and (bits >> (2 * i) & 3) == 3 else 255 for i in range(16)]
            for y in range(min(4, h - by * 4)):
                start_pixel = (by * 4 + y) * w + bx * 4
                alpha[start_pixel:start_pixel+min(4,w-bx*4)] = bytes(values[y*4:y*4+min(4,w-bx*4)])
    return bytes(alpha)

def nearest_alpha(original, ow, oh, width, height):
    # Same centered nearest-neighbor sampling used to preserve the original masks.
    xs = [min(ow-1, ((2*x+1)*ow)//(2*width)) for x in range(width)]
    return bytes(original[min(oh-1, ((2*y+1)*oh)//(2*height))*ow+x] for y in range(height) for x in xs)

def validate(root, report=None):
    folder = root / 'visuals/v1'
    manifest = json.loads((folder / 'manifest.json').read_text())
    data = (root / ARCHIVE).read_bytes()
    require(data == build(root), 'shipped visual BIG differs from canonical DDS sources')
    files = payloads(data)
    require(set(files) == {r['path'].lower() for r in manifest['textures']}, 'overlay scope changed')
    rows = []
    with (root / '!ProjectXRe_Art.big').open('rb') as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as art:
        require(hashlib.sha256(art).hexdigest() == manifest['source_art_sha256'], 'source art archive changed')
        index = {entry.key:entry for entry in read_index(art)}
        for row in manifest['textures']:
            texture = files[row['path'].lower()]
            entry = index[row['path'].lower()]
            original = art[entry.offset:entry.offset + entry.size]
            require(hashlib.sha256(original).hexdigest() == row['source_sha256'], 'original texture hash mismatch')
            info = dds_info(texture)
            for key in ('width', 'height', 'mipmaps', 'fourcc'):
                require(info[key] == row[key], 'DDS metadata mismatch: ' + key)
            require(info['width'] == info['height'] == 1024, 'unexpected target resolution')
            require(texture[84:88] == original[84:88], 'original texture codec changed')
            oh, ow = struct.unpack_from('<II', original, 12)
            require((ow,oh) == (row['source_width'],row['source_height']), 'source dimensions mismatch')
            original_alpha = alpha_bytes(original, (ow,oh,128,entry.size-128))
            for level_number, level in enumerate(info['levels']):
                alpha = alpha_bytes(texture, level)
                expected = nearest_alpha(original_alpha, ow, oh, level[0], level[1])
                require(alpha == expected, 'alpha mask changed: ' + row['path'] + ' mip ' + str(level_number))
                if level_number == 0:
                    require(hashlib.sha256(alpha).hexdigest() == row['alpha_sha256'], 'alpha hash mismatch')
            rows.append({k:row[k] for k in ('path','sha256','width','height','fourcc','mipmaps')})
    result = {'archive':ARCHIVE,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),
              'textures':rows,'alpha_masks':'Exact nearest sampling of original top-level alpha at all 11 mips.',
              'validation':'Static DDS/BIG/alpha verification; offline visual preview is separate. No game/device execution.'}
    if report:
        report.write_text(json.dumps(result, indent=2) + '\n')
    print('PASS: 7 texture-only DDS entries; 1024 square, 11 mips, original codecs/alpha; BIG reproduced byte-for-byte')
    return result

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    validate(args.root, args.report)
