#!/usr/bin/env python3
"""Integrate Russian building destruction inside the original INI BIG."""
import argparse
import hashlib
from pathlib import Path
import re

from big_archive import payloads, replace_payloads

ARCHIVE = '!!ProjectXRe_INI.big'
SOURCE_SHA256 = '0b5797d866c3389f4528fdca99b06c22c29058670928c71441c4726179f0d060'
GROUPS = {
    'airfield': 'Large', 'barracks': 'Medium', 'coalpowerplant': 'Medium',
    'commandbunker': 'Large', 'helipad': 'Medium', 'industrialplant': 'Large',
    'missilesilo': 'Medium', 'outpostairraid': 'Small', 'outpostobservation': 'Small',
    'outpostradar': 'Small', 'supplywarhouse': 'Medium', 'tremor': 'Large',
    'warfactory': 'Large', 'weaponbunker': 'Medium',
}
BUILDINGS = {'data/ini/object/russia/buildings/' + name + '.ini': group
             for name, group in GROUPS.items()}
APPENDS = {'data/ini/fxlist.ini': 'FXList.ini',
           'data/ini/particlesystem.ini': 'ParticleSystem.ini'}
ORIGINAL = {phase: 'FX_StructureCollapse' + phase for phase in ('Initial', 'Delay', 'Burst', 'Final')}
ORIGINAL['InstantDeath'] = 'FX_LargeStructureDeath'
NEWLINE = b'\r\n\r\n; Russian building destruction v1 (integrated)\r\n'


def rewired(data, group, reverse=False):
    """Touch only an existing FX/FXList value, preserving every other byte."""
    for phase, old in ORIGINAL.items():
        new = 'FX_PXRBuilding' + phase + group
        source, target = (new, old) if reverse else (old, new)
        pattern = rb'(?mi)^([ \t]*FX(?:List)?[ \t]*=[ \t]*(?:(?:INITIAL|DELAY|BURST|FINAL)[ \t]+)?)' + source.encode() + rb'\b'
        data, count = re.subn(pattern, lambda m: m[1] + target.encode(), data)
        if not count:
            raise ValueError('missing destruction stage: ' + source)
    return data


def make_files(root, source):
    if hashlib.sha256(source).hexdigest() != SOURCE_SHA256:
        raise ValueError('destruction integration requires the pinned repaired INI archive')
    original = payloads(source)
    files = {path: rewired(original[path], group) for path, group in BUILDINGS.items()}
    for path, name in APPENDS.items():
        addition = (root / 'effects/v1' / name).read_bytes()
        files[path] = original[path] + NEWLINE + addition
    return files


def build(root, source):
    return replace_payloads(source, make_files(root, source))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output', type=Path)
    parser.add_argument('--source', type=Path, required=True)
    args = parser.parse_args()
    if args.source.resolve() == (args.output or args.root / ARCHIVE).resolve():
        parser.error('source and output must differ')
    data = build(args.root, args.source.read_bytes())
    target = args.output or args.root / ARCHIVE
    target.write_bytes(data)
    print('Built', target.name, len(data), 'bytes; SHA256', hashlib.sha256(data).hexdigest())
