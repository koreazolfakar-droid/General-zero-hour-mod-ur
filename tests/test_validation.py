from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from validate_mod import definition, field


class DefinitionTests(unittest.TestCase):
    def test_references_accept_both_supported_assignment_styles(self):
        block = b"Command FIRE_WEAPON\nWeaponSlot = PRIMARY\n"
        self.assertEqual(field(block, "Command"), "FIRE_WEAPON")
        self.assertEqual(field(block, "WeaponSlot"), "PRIMARY")

    def test_missing_or_duplicate_definition_rejected(self):
        for data in (b"", b"SpecialPower Target\nEnd\nSpecialPower Target\nEnd\n"):
            with self.subTest(data=data), self.assertRaises(ValueError):
                definition({"specialpower.ini": data}, "SpecialPower", "Target")

    def test_indented_field_is_not_a_top_level_definition(self):
        with self.assertRaises(ValueError):
            definition({"commandbutton.ini": b"CommandButton Button\n  SpecialPower Target\nEnd\n"},
                       "SpecialPower", "Target")

    def test_nested_ocl_is_not_truncated_at_inner_end(self):
        data = b"ObjectCreationList Wreck\n CreateDebris\n ModelNames = CorrectMesh\n End\nEnd\n"
        result = definition({"ocl.ini": data}, "ObjectCreationList", "Wreck")
        self.assertEqual(field(result, "ModelNames"), "CorrectMesh")
        self.assertIn(b"End", result)

    def test_unterminated_definition_rejected(self):
        with self.assertRaises(ValueError):
            definition({"ocl.ini": b"ObjectCreationList Wreck\n CreateDebris\n End\n"},
                       "ObjectCreationList", "Wreck")

    def test_duplicate_field_rejected(self):
        with self.assertRaises(ValueError):
            field(b"RadiusCursorRadius = 30\nRadiusCursorRadius = 99\n", "RadiusCursorRadius")


if __name__ == "__main__":
    unittest.main()
