"""Exercise malformed archive rejection and preservation with independent fixtures."""
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from big_archive import payloads, read_index, replace_payloads


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
