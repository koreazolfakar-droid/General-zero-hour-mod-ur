"""Reject unsafe emitters, dangling effects and changes outside destruction FX."""
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from build_russian_destruction import APPENDS, BUILDINGS, NEWLINE, ORIGINAL, rewired
from validate_russian_destruction import BUDGETS, check_sources, check_overlay, parse, validate


class DestructionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = (ROOT / 'effects/v1/ParticleSystem.ini').read_bytes()
        cls.f = (ROOT / 'effects/v1/FXList.ini').read_bytes()

    def check(self, p=None, f=None, assets=None):
        return check_sources(self.p if p is None else p, self.f if f is None else f, assets)

    def test_all_three_sizes_are_finite_and_within_phase_budgets(self):
        report = self.check()
        self.assertEqual(report['particle_templates'], 24)
        self.assertEqual(report['fx_lists'], 15)
        self.assertEqual(report['particles_per_invocation'], BUDGETS)

    def test_rejects_perpetual_emitter_and_slave_system(self):
        for p in (self.p.replace(b'SystemLifetime = 1', b'SystemLifetime = 0', 1),
                  self.p.replace(b'IsOneShot = Yes', b'IsOneShot = No', 1),
                  self.p.replace(b'BurstDelay = 99999 99999', b'BurstDelay = 1 1', 1),
                  self.p.replace(b'  Shader', b'  SlaveSystem = SomeOtherEmitter\n  Shader', 1)):
            with self.subTest(p=p[:60]), self.assertRaises(ValueError): self.check(p=p)

    def test_rejects_higher_particle_count_or_unbounded_lifetime(self):
        for p in (self.p.replace(b'BurstCount = 14 14', b'BurstCount = 140 140', 1),
                  self.p.replace(b'Lifetime = 210.0000 210.0000', b'Lifetime = 150.0000 2100.0000', 1)):
            with self.assertRaises(ValueError): self.check(p=p)

    def test_rejects_duplicate_templates_and_missing_particle_reference(self):
        with self.assertRaises(ValueError): self.check(p=self.p+self.p)
        with self.assertRaises(ValueError): self.check(f=self.f.replace(b'Name = PXRBuildingFlashSmall', b'Name = MissingEmitter', 1))

    def test_rejects_unsupported_fx_damage_nugget_and_scale_field(self):
        for f in (self.f.replace(b'  Sound\n', b'  Damage\n', 1),
                  self.f.replace(b'    Count = 1', b'    Count = 1\n    Scale = 2', 1),
                  self.f.replace(b'    Count = 1', b'    Count = 2', 1)):
            with self.assertRaises(ValueError): self.check(f=f)

    def test_alpha_must_fade_with_increasing_keyframes(self):
        for p in (self.p.replace(b'Alpha3 = 0.0000 0.0000 9', b'Alpha3 = 0.5000 0.5000 9', 1),
                  self.p.replace(b'Alpha2 = 0.8500 0.8500 1', b'Alpha2 = 0.8500 0.8500 0', 1),
                  self.p.replace(b'Alpha2 = 0.8500 0.8500 1', b'Alpha2 = 1.8500 1.8500 1', 1)):
            with self.assertRaises(ValueError): self.check(p=p)

    def test_missing_sprite_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'missing sprite'): self.check(assets=set())
        sprites = {'art/textures/' + b['ParticleName'].lower().replace('.tga', '.dds')
                   for b in parse(self.p, 'ParticleSystem').values()}
        self.check(assets=sprites)

    def fixture(self):
        original = {}
        for path in BUILDINGS:
            data = b'  BuildCost = 1000\r\n'
            for phase, name in ORIGINAL.items():
                prefix = '  FX = ' if phase == 'InstantDeath' else '  FXList = ' + phase.upper() + ' '
                data += (prefix + name + '\r\n').encode()
            original[path] = data + b'  OCL = FINAL ExistingDebris\r\n  MinCollapseDelay = 600\r\n'
        original.update({path: b'Existing\r\n' for path in APPENDS})
        overlay = {path: rewired(original[path], group) for path, group in BUILDINGS.items()}
        overlay.update({path: original[path]+NEWLINE+b'new' for path in APPENDS})
        return original, overlay

    def test_only_fx_values_may_change_in_buildings(self):
        original, overlay = self.fixture()
        check_overlay(original, overlay)
        path = next(iter(BUILDINGS))
        overlay[path] = overlay[path].replace(b'BuildCost = 1000', b'BuildCost = 2000')
        with self.assertRaisesRegex(ValueError, 'gameplay bytes'): check_overlay(original, overlay)

    def test_no_extra_archive_entry_or_replacement_of_original_definitions(self):
        original, overlay = self.fixture()
        with self.assertRaises(ValueError): check_overlay(original, dict(overlay, **{'data/ini/weapon.ini': b'bad'}))
        overlay['data/ini/fxlist.ini'] = b'Edited' + overlay['data/ini/fxlist.ini']
        with self.assertRaises(ValueError): check_overlay(original, overlay)


@unittest.skipUnless(os.environ.get('MOD_ARCHIVE_TESTS') == '1', 'requires downloaded BIG archives')
class ShippedDestructionTests(unittest.TestCase):
    def test_overlay_reproduces_and_all_original_gameplay_bytes_are_preserved(self):
        validate(ROOT)


if __name__ == '__main__': unittest.main()
