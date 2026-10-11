"""Regression checks against real shipped INI files, enabled after CI downloads LFS."""
import mmap
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from big_archive import payloads, read_index
from validate_mod import check_references


@unittest.skipUnless(os.environ.get("MOD_ARCHIVE_TESTS") == "1", "requires downloaded BIG archives")
class ShippedReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files = payloads((ROOT / "!!ProjectXRe_INI.big").read_bytes())
        with (ROOT / "!ProjectXRe_Art.big").open("rb") as stream:
            with mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
                cls.assets = {e.key for e in read_index(data)}

    def test_shipped_references_resolve(self):
        check_references(self.files, self.assets)

    def test_original_reference_failures_are_rejected(self):
        cases = (
            ("data/ini/commandset.ini", b"CommandSet RussianInfantrySVUSniperCommandSet", b"CommandSet BrokenSVUCommandSet"),
            ("data/ini/specialpower.ini", b"SpecialPower IskanderGroundAttack", b"SpecialPower BrokenIskanderGroundAttack"),
            ("data/ini/specialpower.ini", b"SpecialPower MigBomberGroundAttack", b"SpecialPower BrokenMigBomberGroundAttack"),
            ("data/ini/objectcreationlist.ini", b"ObjectCreationList OCL_OgreTankDeathEffect", b"ObjectCreationList OCL_BrokenOgreTankDeathEffect"),
            ("data/ini/object/russia/vehicles/mishka.ini", b"RVMishka_UD", b"RVMishka_U_D"),
            ("data/ini/default/aidata.ini", b"BaseDefenseStructure1       RussiaKashtan", b"BaseDefenseStructure1       Russia_RussiaKashtan"),
        )
        for path, valid, broken in cases:
            with self.subTest(reference=valid):
                self.assertIn(valid, self.files[path])
                mutant = dict(self.files)
                mutant[path] = mutant[path].replace(valid, broken)
                with self.assertRaises(ValueError):
                    check_references(mutant, self.assets)

    def test_missing_repaired_meshes_are_rejected(self):
        for asset in ("art/w3d/rvogre_d1.w3d", "art/w3d/rvmishka_ud.w3d"):
            with self.subTest(asset=asset):
                self.assertIn(asset, self.assets)
                with self.assertRaises(ValueError):
                    check_references(self.files, self.assets - {asset})


if __name__ == "__main__":
    unittest.main()
