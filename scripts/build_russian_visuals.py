#!/usr/bin/env python3
"""Replace seven canonical DDS payloads inside the original Art BIG."""
import argparse
import hashlib
import json
from pathlib import Path
from big_archive import replace_file

ARCHIVE = '!ProjectXRe_Art.big'
TEXTURES = {'RBCPwrPlnt1', 'RBBarr_1', 'RBBarr_2', 'RBCmdBnkr1', 'RBCmdBnkr2', 'RVKodiakC', 'RVKodiakT'}

def make_files(root):
    folder = root / 'visuals/v1'
    manifest = json.loads((folder / 'manifest.json').read_text())
    if manifest['archive'] != ARCHIVE:
        raise ValueError('unexpected overlay name')
    expected = {'Art/Textures/' + name + '.dds' for name in TEXTURES}
    if {t['path'] for t in manifest['textures']} != expected or len(manifest['textures']) != len(expected):
        raise ValueError('unexpected texture scope')
    files = {}
    for row in manifest['textures']:
        data = (folder / row['path']).read_bytes()
        if len(data) != row['size'] or hashlib.sha256(data).hexdigest() != row['sha256']:
            raise ValueError('canonical DDS hash mismatch: ' + row['path'])
        files[row['path']] = data
    return {name.lower(): data for name, data in files.items()}

def build(root, source, target):
    import mmap
    manifest = json.loads((root / 'visuals/v1/manifest.json').read_text())
    with source.open('rb') as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
        if hashlib.sha256(data).hexdigest() != manifest['source_art_sha256']:
            raise ValueError('visual integration requires the pinned original Art archive')
    replace_file(source, target, make_files(root))

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output', type=Path)
    parser.add_argument('--source', type=Path, required=True)
    args = parser.parse_args()
    target = args.output or args.root / ARCHIVE
    build(args.root, args.source, target)
    print('Built', target.name, target.stat().st_size, 'bytes')
