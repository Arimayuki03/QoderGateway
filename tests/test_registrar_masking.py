"""覆盖修复 7：注册 result 脱敏——最新完成记录保留明文，更早历史打码。"""
import copy
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (str(REPO_ROOT / "src"), str(Path(__file__).resolve().parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import support  # noqa: E402  # 必须先于 qoder2api 导入（设置环境守卫）

import qoder2api.registrar as registrar  # noqa: E402


def make_result(tag: str) -> dict:
    return {
        "email": f"{tag}@example.com",
        "password": f"Passw0rd!{tag}",
        "name": f"User {tag}",
        "device": {
            "token": f"dt-0123456789abcdef-{tag}",
            "refresh_token": f"rt-0123456789abcdef-{tag}",
            "user_id": f"uid-{tag}",
            "expires_at": "2026-01-01",
        },
    }


class RegistrarMaskingTest(unittest.TestCase):
    def setUp(self) -> None:
        # _REGISTRAR 是模块级单例：备份并在测后恢复，避免污染其他测试
        self._saved = copy.deepcopy(registrar._REGISTRAR)
        registrar._REGISTRAR["recent"] = {}
        registrar._REGISTRAR["active"] = {}
        registrar._REGISTRAR["stats"] = {"success": 0, "failed": 0, "total": 0}

    def tearDown(self) -> None:
        with registrar._LOCK:
            registrar._REGISTRAR.clear()
            registrar._REGISTRAR.update(self._saved)

    def test_latest_result_plaintext_older_masked(self):
        registrar._finish_task("t1", "success", result=make_result("t1"))
        registrar._finish_task("t2", "success", result=make_result("t2"))
        registrar._finish_task("t3", "success", result=make_result("t3"))

        recent = registrar._REGISTRAR["recent"]
        # 最新一条保留明文（注册完可立即复制）
        latest = recent["t3"]["result"]
        self.assertEqual(latest["password"], "Passw0rd!t3")
        self.assertEqual(latest["device"]["token"], "dt-0123456789abcdef-t3")

        # 更早的历史条目全部打码
        for tid in ("t1", "t2"):
            masked = recent[tid]["result"]
            self.assertNotEqual(masked["password"], f"Passw0rd!{tid}")
            self.assertNotIn(f"Passw0rd!{tid}", str(masked))
            self.assertNotEqual(masked["device"]["token"], f"dt-0123456789abcdef-{tid}")
            self.assertNotIn(f"dt-0123456789abcdef-{tid}", str(masked))
            self.assertNotIn(f"rt-0123456789abcdef-{tid}", str(masked))
            self.assertEqual(masked["email"], f"{tid}@example.com")  # 非敏感字段不动

    def test_masked_token_keeps_recognizable_head_and_tail(self):
        masked = registrar._mask_result(make_result("x"))
        token_masked = masked["device"]["token"]
        self.assertTrue(token_masked.startswith("dt-"), token_masked)
        self.assertTrue(token_masked.endswith("-x") or token_masked[-4:] in token_masked)
        self.assertIn("****", token_masked)

    def test_mask_value_styles(self):
        self.assertEqual(registrar._mask_value("short"), "****")
        self.assertEqual(registrar._mask_value("ab12cd34ef56"), "ab****56")
        self.assertEqual(registrar._mask_value("dt-0123456789abcdef"), "dt-****cdef")

    def test_status_dump_only_exposes_masked_history(self):
        registrar._finish_task("t1", "success", result=make_result("t1"))
        registrar._finish_task("t2", "success", result=make_result("t2"))
        status = registrar.get_registrar_status()
        dumped_history = str(status["recent"]["t1"]["result"])
        self.assertNotIn("Passw0rd!t1", dumped_history)
        self.assertNotIn("dt-0123456789abcdef-t1", dumped_history)


if __name__ == "__main__":
    unittest.main()
