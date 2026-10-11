#!/usr/bin/env python3
"""Reproduce the two updated original archives from immutable Git LFS sources."""
import argparse
import hashlib
import json
import mmap
from pathlib import Path

from build_russian_destruction import build as build_ini
from build_russian_visuals import build as build_art
from patch_russian_references import SOURCE_SHA256, patch

ART_SHA256 = '038768a89b6d4081da68e6bbc8bdaa4fafb3616e563f478b1812fe766c2fde11'


def baseline_path(root, digest):
    git = root / '.git'
    if git.is_file():
        git = (root / git.read_text().strip().removeprefix('gitdir: ')).resolve()
        if (git / 'commondir').exists():
            git = (git / (git / 'commondir').read_text().strip()).resolve()
    path = git / 'lfs/objects' / digest[:2] / digest[2:4] / digest
    if not path.is_file():
        raise ValueError('immutable baseline not downloaded: ' + digest)
    return path


def digest_file(path):
    with path.open('rb') as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
        return hashlib.sha256(data).hexdigest()


def build(root, ini_source, art_source, output):
    output.mkdir(parents=True, exist_ok=True)
    if art_source.resolve() == (output / '!ProjectXRe_Art.big').resolve() or ini_source.resolve() == (output / '!!ProjectXRe_INI.big').resolve():
        raise ValueError('immutable sources and output must differ')
    ini = build_ini(root, patch(ini_source.read_bytes()))
    # Build Art first; neither source archive is modified.
    build_art(root, art_source, output / '!ProjectXRe_Art.big')
    (output / '!!ProjectXRe_INI.big').write_bytes(ini)
    rows = {name: {'size': (output / name).stat().st_size, 'sha256': digest_file(output / name)}
            for name in ('!ProjectXRe_Art.big', '!!ProjectXRe_INI.big')}
    print(json.dumps(rows, indent=2))
    return rows


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--ini-source', type=Path)
    parser.add_argument('--art-source', type=Path)
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args()
    build(args.root, args.ini_source or baseline_path(args.root, SOURCE_SHA256),
          args.art_source or baseline_path(args.root, ART_SHA256), args.output_dir or args.root)
