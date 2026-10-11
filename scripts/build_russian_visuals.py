#!/usr/bin/env python3
"""Pack canonical DDS sources into a reproducible optional visual overlay."""
import argparse
import hashlib
import json
from pathlib import Path
from big_archive import write_big

ARCHIVE = '!!!ProjectXRe_RussianVisualsV1.big'
TEXTURES = {'RBCPwrPlnt1', 'RBBarr_1', 'RBBarr_2', 'RBCmdBnkr1', 'RBCmdBnkr2', 'RVKodiakC', 'RVKodiakT'}

def build(root):
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
    return write_big(files)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    data = build(args.root)
    target = args.output or args.root / ARCHIVE
    target.write_bytes(data)
    print('Built', target.name, len(data), 'bytes; SHA256', hashlib.sha256(data).hexdigest())
