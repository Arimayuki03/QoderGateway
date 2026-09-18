"""覆盖修复 5：uid 兜底改 SHA-256 哈希（确定性、不泄漏 token 前缀）。"""
import hashlib
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (str(REPO_ROOT / "src"), str(Path(__file__).resolve().parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import support  # noqa: E402  # 必须先于 qoder2api 导入（设置环境守卫）
from support import DBBackedTestCase  # noqa: E402

from qoder2api.accounts import batch_import_accounts  # noqa: E402

TOKEN = "dt-Ab12Cd34Ef56Gh78Ij90KlMnOpQrStUv"  # 长 token：旧实现会把前 24 位暴露进 uid


class UidFallbackTest(DBBackedTestCase):
    def test_uid_is_sha256_derived_and_contains_no_token_substring(self):
        result = batch_import_accounts([{"token": TOKEN}])
        self.assertEqual(result["imported"], 1)
        uid = self.sql("SELECT uid FROM accounts")[0][0]
        expected = "tok_" + hashlib.sha256(TOKEN.encode("utf-8")).hexdigest()[:24]
        self.assertEqual(uid, expected)
        # 旧格式是 "tok_" + token[:24]；新 uid 必须不含 token 的任何前缀片段
        self.assertNotIn(TOKEN[:24], uid)
        self.assertNotIn(TOKEN[:16], uid)
        self.assertNotIn(TOKEN[:8], uid)

    def test_same_token_maps_to_same_uid_and_single_row(self):
        batch_import_accounts([{"token": TOKEN, "name": "first"}])
        # 同一 token 再次导入（无 user_id）：命中同一行而不是新增
        batch_import_accounts([{"token": TOKEN, "name": "second", "expires_at": "exp-2"}])
        rows = self.sql("SELECT uid, name FROM accounts")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "second")  # 凭据/名称被更新

    def test_user_id_still_wins_over_fallback(self):
        batch_import_accounts([{"user_id": "real-uid", "token": TOKEN}])
        uid = self.sql("SELECT uid FROM accounts")[0][0]
        self.assertEqual(uid, "real-uid")


if __name__ == "__main__":
    unittest.main()
