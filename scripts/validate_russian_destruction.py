#!/usr/bin/env python3
"""Check finite effects, references, archive scope and unchanged gameplay bytes."""
import hashlib
import json
import math
import mmap
from pathlib import Path
import re

from big_archive import payloads, read_index, write_big
from build_russian_destruction import ARCHIVE, APPENDS, BUILDINGS, NEWLINE, SOURCE_SHA256, make_files, rewired

ROLES = {'Flash': 1, 'Fireball': 3, 'DustRing': 12, 'CollapseDust': 14,
         'BurstDust': 6, 'Smoke': 6, 'Sparks': 4, 'Debris': 6}
BUDGETS = {'Initial': 16, 'Delay': 10, 'Burst': 14, 'Final': 30, 'InstantDeath': 42}
SOUNDS = {'Initial': 'BuildingDamage', 'Delay': 'BuildingCollapse1',
          'Burst': 'BuildingCollapse2', 'Final': 'BuildingCollapse3', 'InstantDeath': 'BuildingDie'}
SIZES = ('Small', 'Medium', 'Large')
FIELDS = set('Priority IsOneShot Shader Type ParticleName AngleZ AngularRateZ AngularDamping VelocityDamping Gravity Lifetime SystemLifetime Size StartSizeRate SizeRate SizeRateDamping ColorScale BurstDelay BurstCount InitialDelay DriftVelocity VelocityType VelOutward VelOutwardOther VolumeType VolCylinderRadius VolCylinderLength IsHollow IsGroundAligned IsEmitAboveGroundOnly IsParticleUpTowardsEmitter WindMotion'.split())
FIELDS |= {'Alpha' + str(i) for i in range(1, 9)} | {'Color' + str(i) for i in range(1, 9)}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def lines(data):
    return [line for raw in data.decode('ascii').splitlines()
            if (line := raw.split(';', 1)[0].strip())]


def fields(rows):
    result = {}
    for line in rows:
        match = re.fullmatch(r'(\w+)\s*=\s*(.+)', line)
        require(match is not None, 'invalid field: ' + line)
        key, value = match.groups()
        require(key not in result, 'duplicate field: ' + key)
        result[key] = value
    return result


def parse(data, kind):
    """Parse the new restricted templates, including nested FX nuggets."""
    rows, result, i = lines(data), {}, 0
    while i < len(rows):
        match = re.fullmatch(kind + r'\s+(\w+)', rows[i])
        require(match is not None, 'unexpected definition: ' + rows[i])
        name = match[1]
        require(name not in result, 'duplicate definition: ' + name)
        i += 1
        body = []
        if kind == 'FXList':
            while i < len(rows) and rows[i] != 'End':
                nugget = rows[i]
                require(nugget in ('Sound', 'ParticleSystem', 'ViewShake'), 'unsupported FX nugget: ' + nugget)
                i += 1
                block = []
                while i < len(rows) and rows[i] != 'End':
                    block.append(rows[i]); i += 1
                require(i < len(rows), 'unterminated FX nugget')
                body.append((nugget, fields(block))); i += 1
        else:
            while i < len(rows) and rows[i] != 'End':
                body.append(rows[i]); i += 1
            body = fields(body)
        require(i < len(rows) and rows[i] == 'End', 'unterminated template: ' + name)
        result[name] = body; i += 1
    return result


def numbers(value, count):
    parts = value.split()
    require(len(parts) == count, 'unexpected number count: ' + value)
    try:
        result = [float(n) for n in parts]
    except ValueError as error:
        raise ValueError('invalid number: ' + value) from error
    require(all(math.isfinite(n) for n in result), 'non-finite number')
    return result


def pair(value, low, high):
    a, b = numbers(value, 2)
    require(low <= a <= b <= high, 'range outside permitted bounds: ' + value)
    return a, b


def check_sources(particle_data, fx_data, assets=None, audio=None):
    particles, fx = parse(particle_data, 'ParticleSystem'), parse(fx_data, 'FXList')
    expected = {'PXRBuilding' + role + group for role in ROLES for group in SIZES}
    require(set(particles) == expected, 'unexpected particle scope')
    expected = {'FX_PXRBuilding' + phase + group for phase in BUDGETS for group in SIZES}
    require(set(fx) == expected, 'unexpected FX scope')
    for name, block in particles.items():
        require(set(block) <= FIELDS, 'unsupported particle field: ' + name)
        mandatory = FIELDS - {key for key in FIELDS if key.startswith(('Alpha', 'Color'))}
        mandatory.add('ColorScale')
        require(mandatory <= set(block), 'missing particle field: ' + name)
        require(block['SystemLifetime'] == '1' and block['IsOneShot'] == 'Yes', 'emitter must emit once')
        require(block['Priority'] == 'DEATH_EXPLOSION' and block['Type'] == 'PARTICLE', 'invalid particle type/priority')
        require(block['Shader'] in ('ADDITIVE', 'ALPHA', 'ALPHA_TEST'), 'unsupported shader')
        require(block['VelocityType'] == 'OUTWARD' and block['VolumeType'] == 'CYLINDER', 'invalid emitter shape')
        require(block['IsHollow'] == block['IsGroundAligned'] == block['IsParticleUpTowardsEmitter'] == 'No', 'unexpected particle alignment')
        require(block['IsEmitAboveGroundOnly'] == 'Yes' and block['WindMotion'] == 'Unused', 'unexpected emission flags')
        pair(block['BurstDelay'], 99999, 99999); pair(block['InitialDelay'], 0, 0)
        group = next(g for g in SIZES if name.endswith(g))
        role = name[len('PXRBuilding'):-len(group)]
        pair(block['BurstCount'], ROLES[role], ROLES[role])
        life = pair(block['Lifetime'], 1, 210)
        for key, low, high in (('Size', .1, 40), ('StartSizeRate', 0, 0), ('SizeRate', 0, 2),
                              ('SizeRateDamping', 0, 1), ('AngularDamping', 0, 1),
                              ('VelocityDamping', 0, 1), ('VelOutward', 0, 4),
                              ('VelOutwardOther', 0, 4), ('AngularRateZ', -.2, .2),
                              ('AngleZ', 0, 6.284), ('ColorScale', 0, 0)):
            pair(block[key], low, high)
        require(-.2 <= numbers(block['Gravity'], 1)[0] <= 0, 'gravity out of bounds')
        require(0 <= numbers(block['VolCylinderRadius'], 1)[0] <= 30, 'emission radius out of bounds')
        require(numbers(block['VolCylinderLength'], 1)[0] == 0, 'unexpected vertical volume')
        drift = re.fullmatch(r'X:([^ ]+) Y:([^ ]+) Z:([^ ]+)', block['DriftVelocity'])
        require(drift is not None and all(0 <= n <= 1 for n in numbers(' '.join(drift.groups()), 3)), 'invalid drift')
        alphas = [block['Alpha' + str(i)] for i in range(1, 9) if 'Alpha' + str(i) in block]
        require(len(alphas) >= 3 and {'Alpha' + str(i) for i in range(1, len(alphas)+1)} <= set(block), 'missing alpha keyframes')
        ticks = []
        for value in alphas:
            a, b, tick = numbers(value, 3)
            require(0 <= a <= b <= 1 and tick == int(tick), 'invalid alpha keyframe')
            ticks.append(tick)
        require(ticks[0] == 0 and all(a < b for a, b in zip(ticks, ticks[1:])) and ticks[-1] == life[1], 'invalid alpha timing')
        require(numbers(alphas[-1], 3)[:2] == [0, 0], 'particles must fade to zero')
        colors = [block['Color' + str(i)] for i in range(1, 9) if 'Color' + str(i) in block]
        require(len(colors) >= 2 and {'Color' + str(i) for i in range(1,len(colors)+1)} <= set(block), 'missing color keyframes')
        color_ticks = []
        for value in colors:
            match = re.fullmatch(r'R:(\d+) G:(\d+) B:(\d+) (\d+)', value)
            require(match is not None and all(0 <= int(v) <= 255 for v in match.groups()[:3]), 'invalid color keyframe')
            color_ticks.append(int(match[4]))
        require(color_ticks[0] == 0 and all(a < b for a,b in zip(color_ticks,color_ticks[1:])) and color_ticks[-1] <= life[1], 'invalid color timing')
        if block['Shader'] == 'ADDITIVE':
            require(colors[-1].startswith('R:0 G:0 B:0 '), 'additive particles must fade to black')
        sprite = block['ParticleName'].lower()
        require(re.fullmatch(r'ex\w+\.tga', sprite) is not None, 'invalid sprite path')
        if assets is not None:
            require('art/textures/' + sprite in assets or 'art/textures/' + sprite[:-4] + '.dds' in assets, 'missing sprite: ' + sprite)
    for group in SIZES:
        for phase, budget in BUDGETS.items():
            name = 'FX_PXRBuilding' + phase + group
            nuggets = fx[name]
            sounds = [block for kind, block in nuggets if kind == 'Sound']
            require(sounds == [{'Name': SOUNDS[phase]}], 'original sound changed')
            if audio is not None:
                require(re.search(rb'(?m)^AudioEvent\s+' + SOUNDS[phase].encode() + rb'\s*\r?$', audio), 'missing audio event')
            shakes = [block for kind, block in nuggets if kind == 'ViewShake']
            require(shakes == ([{'Type': 'STRONG'}] if phase == 'InstantDeath' else []), 'unexpected camera shake')
            emitted, seen = 0, set()
            for kind, block in nuggets:
                if kind != 'ParticleSystem':
                    continue
                require(set(block) == {'Name', 'Count', 'InitialDelay', 'Offset'}, 'unsupported FX particle field')
                target = block['Name']
                require(target in particles and target.endswith(group) and target not in seen, 'invalid particle reference: ' + target)
                seen.add(target)
                require(block['Count'] == '1', 'unexpected emitter count')
                delay = re.fullmatch(r'(\d+) (\d+) CONSTANT', block['InitialDelay'])
                require(delay is not None and 0 <= int(delay[1]) == int(delay[2]) <= 250, 'invalid FX delay')
                require(re.fullmatch(r'X:0 Y:0 Z:(?:0|1|4|6|8|10|12)', block['Offset']) is not None, 'unexpected FX offset')
                emitted += int(numbers(particles[target]['BurstCount'], 2)[1])
            require(emitted == budget, 'particle budget changed: ' + name)
    return {'particle_templates': len(particles), 'fx_lists': len(fx),
            'particles_per_invocation': BUDGETS, 'max_lifetime_ticks': 210}


def check_overlay(original, overlay):
    require(set(overlay) == set(BUILDINGS) | set(APPENDS), 'unexpected destruction archive scope')
    for path, group in BUILDINGS.items():
        require(rewired(overlay[path], group, reverse=True) == original[path], 'gameplay bytes changed: ' + path)
    for path in APPENDS:
        require(overlay[path].startswith(original[path] + NEWLINE), 'original global definitions changed: ' + path)


def validate(root):
    source = (root / '!!ProjectXRe_INI.big').read_bytes()
    require(hashlib.sha256(source).hexdigest() == SOURCE_SHA256, 'source INI hash mismatch')
    original = payloads(source)
    shipped = (root / ARCHIVE).read_bytes()
    overlay = payloads(shipped)
    check_overlay(original, overlay)
    folder = root / 'effects/v1'
    p, f = (folder / 'ParticleSystem.ini').read_bytes(), (folder / 'FXList.ini').read_bytes()
    for kind, addition, path in (('ParticleSystem', p, 'data/ini/particlesystem.ini'), ('FXList', f, 'data/ini/fxlist.ini')):
        for name in parse(addition, kind):
            require(not re.search(rb'(?m)^' + kind.encode() + rb'\s+' + name.encode() + rb'\b', original[path]), 'new template collides with original: ' + name)
    with (root / '!ProjectXRe_Art.big').open('rb') as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
        assets = {e.key for e in read_index(data)}
    report = check_sources(p, f, assets, original['data/ini/soundeffects.ini'])
    require(write_big(make_files(root, source)) == shipped, 'destruction BIG is not reproducible')
    manifest = json.loads((folder / 'manifest.json').read_text())
    require(manifest['archive'] == ARCHIVE and manifest['source_ini_sha256'] == SOURCE_SHA256, 'manifest source mismatch')
    digest = hashlib.sha256(shipped).hexdigest()
    require(manifest['sha256'] == digest and manifest['size'] == len(shipped), 'destruction overlay digest mismatch')
    require(manifest['building_groups'] == BUILDINGS, 'manifest building scope mismatch')
    require(manifest['particles_per_invocation'] == BUDGETS, 'manifest particle budget mismatch')
    report.update(archive=ARCHIVE, entries=len(overlay), size=len(shipped), sha256=digest,
                  buildings=len(BUILDINGS), gameplay_preservation='all bytes except existing destruction FX references',
                  validation='static only; game and physical phone QA pending')
    print('PASS: Russian destruction overlay; 14 building files, 24 finite particles, 15 FX lists; original gameplay bytes preserved')
    return report


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    validate(parser.parse_args().root)
