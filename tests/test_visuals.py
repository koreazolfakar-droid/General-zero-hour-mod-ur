"""Independent DDS fixtures catch mip truncation and alpha loss without Pillow."""
import os
from pathlib import Path
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT / 'scripts'))
from validate_russian_visuals import dds_info, alpha_bytes, nearest_alpha, validate

def fixture(codec=b'DXT3'):
    header = bytearray(128)
    header[:4] = b'DDS '
    for offset,value in ((4,124),(8,0xA1007),(12,4),(16,4),(20,16 if codec==b'DXT3' else 8),
                         (28,3),(76,32),(80,4),(108,0x401008)):
        struct.pack_into('<I',header,offset,value)
    header[84:88] = codec
    # Explicit alpha nibbles 0..15 in row-major order plus an opaque DXT1 color block.
    colors = struct.pack('<HHI',0xffff,0,0)
    block = bytes.fromhex('1032547698badcfe')+colors if codec==b'DXT3' else colors
    return bytes(header)+block*3

class DDSTests(unittest.TestCase):
    def test_exact_dimensions_and_mip_extents(self):
        info=dds_info(fixture())
        self.assertEqual(info['levels'],[(4,4,128,16),(2,2,144,16),(1,1,160,16)])

    def test_dxt3_alpha_including_partial_edge_blocks(self):
        data=fixture();info=dds_info(data)
        self.assertEqual(alpha_bytes(data,info['levels'][0]),bytes(i*17 for i in range(16)))
        self.assertEqual(alpha_bytes(data,info['levels'][1]),bytes([0,17,68,85]))
        self.assertEqual(alpha_bytes(data,info['levels'][2]),bytes([0]))

    def test_dxt1_alpha_is_opaque_unless_transparent_index_used(self):
        data=bytearray(fixture(b'DXT1'));info=dds_info(data)
        self.assertEqual(alpha_bytes(data,info['levels'][0]),b'\xff'*16)
        struct.pack_into('<HHI',data,128,0,0xffff,3)
        self.assertEqual(alpha_bytes(data,info['levels'][0]),b'\x00'+b'\xff'*15)

    def test_rejects_incomplete_or_invalid_dds(self):
        for offset,value in ((4,125),(8,0x81007),(16,3),(20,0),(28,2),(76,4),(80,0),(108,0x1000),(112,512)):
            data=bytearray(fixture());struct.pack_into('<I',data,offset,value)
            with self.subTest(offset=offset),self.assertRaises(ValueError):dds_info(data)
        for data in (fixture()[:-1],fixture()+b'bad',b'version https://git-lfs.github.com/spec/v1\n',fixture(b'DXT5')):
            with self.subTest(data_length=len(data)),self.assertRaises(ValueError):dds_info(data)

    def test_nearest_alpha_keeps_original_transparent_holes(self):
        self.assertEqual(nearest_alpha(bytes([0,255,17,238]),2,2,4,4),
                         bytes([0,0,255,255,0,0,255,255,17,17,238,238,17,17,238,238]))
        self.assertEqual(nearest_alpha(bytes(range(16)),4,4,2,2),bytes([5,7,13,15]))

@unittest.skipUnless(os.environ.get('MOD_ARCHIVE_TESTS')=='1','requires downloaded BIG archives')
class ShippedVisualTests(unittest.TestCase):
    def test_overlay_reproduces_and_all_alpha_mips_match_originals(self):
        validate(ROOT)

if __name__=='__main__':unittest.main()
