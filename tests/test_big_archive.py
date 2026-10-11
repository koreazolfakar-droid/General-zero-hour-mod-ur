"""Exercise malformed archive rejection and preservation with independent fixtures."""
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from big_archive import payloads, read_index, replace_payloads, replace_file, check_replacement, write_big


def fixture(names=(b"Data/A.ini", b"Data/B.ini")):
    header_size = 16 + sum(9 + len(n) for n in names)
    contents = [b"alpha", b"beta"]
    data = bytearray(b"BIGF" + struct.pack("<I", header_size + sum(map(len, contents))) +
                     struct.pack(">II", 2, header_size))
    offset = header_size
    for name, content in zip(names, contents):
        data.extend(struct.pack(">II", offset, len(content)) + name + b"\0")
        offset += len(content)
    return data + b"".join(contents)


class ArchiveTests(unittest.TestCase):
    def test_streamed_original_archive_matches_independent_fixture(self):
        original = fixture()
        expected = fixture()
        # Independent expected BIG with replacement 'ALPHA' of equal length.
        first = read_index(expected)[0]
        expected[first.offset:first.offset+first.size] = b'ALPHA'
        with tempfile.TemporaryDirectory() as folder:
            source, target = Path(folder)/'before.big', Path(folder)/'after.big'
            source.write_bytes(original)
            replace_file(source, target, {'data/a.ini': b'ALPHA'})
            self.assertEqual(target.read_bytes(), expected)
            self.assertEqual(source.read_bytes(), original)
            with self.assertRaises(ValueError): replace_file(source, source, {})
            with self.assertRaises(ValueError): replace_file(source, target, {'missing': b'x'})

    def test_streamed_growth_preserves_padding_and_index_order(self):
        original = fixture()
        # Include header padding, an inter-entry gap, and trailing bytes.
        entries = read_index(original)
        header = bytearray(original[:entries[0].offset])
        header.extend(b'HEAD')
        struct.pack_into('>II', header, entries[0].row, len(header), 5)
        struct.pack_into('>II', header, entries[1].row, len(header)+8, 4)
        original = header + b'alphaGAPbetaTAIL'
        struct.pack_into('<I', original, 4, len(original))
        with tempfile.TemporaryDirectory() as folder:
            source, target = Path(folder)/'before.big', Path(folder)/'after.big'
            source.write_bytes(original)
            replace_file(source, target, {'data/a.ini': b'longer alpha'})
            actual = target.read_bytes()
            check_replacement(original, actual, {'data/a.ini': b'longer alpha'})
            self.assertIn(b'HEAD', actual)
            self.assertIn(b'GAP', actual)
            self.assertTrue(actual.endswith(b'TAIL'))
            self.assertEqual(payloads(actual)['data/b.ini'], b'beta')

    def test_integration_rejects_unrelated_payload_or_header_change(self):
        original = fixture()
        replacement = {'data/a.ini': b'new alpha'}
        updated = bytearray(replace_payloads(original, replacement))
        check_replacement(original, updated, replacement)
        mutated = bytearray(updated)
        entry = read_index(mutated)[1]
        mutated[entry.offset] ^= 1
        with self.assertRaisesRegex(ValueError, 'payload content'): check_replacement(original, mutated, replacement)
        mutated = bytearray(updated); mutated[:4] = b'BIG4'
        with self.assertRaisesRegex(ValueError, 'header bytes'): check_replacement(original, mutated, replacement)
        with self.assertRaises(ValueError): check_replacement(original, updated, {'missing': b'x'})

    def test_writer_matches_independent_big_fixture(self):
        self.assertEqual(write_big({'Data/B.ini':b'beta', 'Data/A.ini':b'alpha'}), fixture())

    def test_writer_rejects_duplicate_paths_and_nul(self):
        for files in ({'Art/A.dds':b'a','art/a.dds':b'b'}, {'Art/A\0.dds':b'a'}, {'../evil':b'a'}, {}):
            with self.subTest(files=files), self.assertRaises(ValueError):
                write_big(files)

    def test_replacement_preserves_other_payload_and_names(self):
        original = fixture()
        updated = replace_payloads(original, {"data/a.ini": b"longer new content"})
        self.assertEqual(payloads(updated), {"data/a.ini": b"longer new content", "data/b.ini": b"beta"})
        self.assertEqual([e.name for e in read_index(original)], [e.name for e in read_index(updated)])

    def test_lfs_pointer_is_not_an_archive(self):
        with self.assertRaises(ValueError):
            read_index(b"version https://git-lfs.github.com/spec/v1\n")

    def test_truncated_archive(self):
        with self.assertRaises(ValueError):
            read_index(fixture()[:-1])

    def test_duplicate_paths_case_and_separator_insensitive(self):
        with self.assertRaises(ValueError):
            read_index(fixture((b"Data/A.ini", b"data\\a.INI")))

    def test_unsafe_paths(self):
        for path in (b"../evil", b"/absolute", b"C:/drive", b"Data/../evil"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                read_index(fixture((path, b"Data/B.ini")))

    def test_bad_index_size_and_termination(self):
        for header_size in (15, 17, 999999):
            data = fixture()
            struct.pack_into(">I", data, 12, header_size)
            with self.subTest(header_size=header_size), self.assertRaises(ValueError):
                read_index(data)
        data = fixture()
        for pos in (34, 53):
            data[pos] = 65
        with self.assertRaises(ValueError):
            read_index(data)

    def test_payload_overlap_and_out_of_bounds(self):
        for offset in (0, 54, 99999):
            data = fixture()
            struct.pack_into(">I", data, 35, offset)
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                read_index(data)

    def test_unknown_replacement_rejected(self):
        with self.assertRaises(ValueError):
            replace_payloads(fixture(), {"missing.ini": b"bad"})


if __name__ == "__main__":
    unittest.main()
