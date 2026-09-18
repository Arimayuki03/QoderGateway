"""覆盖修复 16(g)：encoding.py 自定义 base64 编解码往返回归。"""
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (str(REPO_ROOT / "src"), str(Path(__file__).resolve().parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import support  # noqa: E402  # 必须先于 qoder2api 导入（设置环境守卫）

from qoder2api import encoding  # noqa: E402

CUSTOM_ALPHABET = set(encoding.CUSTOM_ALPHABET)
CUSTOM_PAD = encoding.CUSTOM_PAD


class EncodingRoundTripTest(unittest.TestCase):
    def test_roundtrip_various_inputs(self):
        samples = [
            b"",
            b"a",
            b"hello world",
            "中文测试 UTF-8 内容".encode("utf-8"),
            bytes(range(256)),
            b"x" * 1000,
            b"\x00\x01\x02\xff\xfe",
        ]
        for raw in samples:
            with self.subTest(raw=raw[:16]):
                encoded = encoding.encode(raw)
                self.assertIsInstance(encoded, str)
                self.assertEqual(encoding.decode(encoded), raw)

    def test_encode_output_uses_custom_alphabet(self):
        encoded = encoding.encode(b"standard base64 payload!!")
        for ch in encoded:
            self.assertIn(ch, CUSTOM_ALPHABET | {CUSTOM_PAD})

    def test_encode_is_deterministic(self):
        self.assertEqual(encoding.encode(b"same bytes"), encoding.encode(b"same bytes"))

    def test_encode_differs_from_standard_base64(self):
        raw = b"obviously different from std b64"
        self.assertNotEqual(encoding.encode(raw), __import__("base64").b64encode(raw).decode("ascii"))


if __name__ == "__main__":
    unittest.main()
