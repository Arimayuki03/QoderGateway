"""覆盖修复 4：rotate_next_account 真轮转语义（环绕前进、失败账号进冷却、单账号不豁免）。"""
import sys
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (str(REPO_ROOT / "src"), str(Path(__file__).resolve().parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import support  # noqa: E402  # 必须先于 qoder2api 导入（设置环境守卫）
from support import DBBackedTestCase  # noqa: E402

import qoder2api.accounts as accounts  # noqa: E402
import qoder2api.database as database  # noqa: E402
from qoder2api.accounts import rotate_next_account, upsert_account_credentials  # noqa: E402


def make_accounts(uids: list[str]) -> None:
    with database.get_db() as conn:
        for uid in uids:
            upsert_account_credentials(conn, uid, "N-" + uid, "personal_standard",
                                       "tok-" + uid, "rt-" + uid, "mid-" + uid)


class RotateTest(DBBackedTestCase):
    def test_multi_account_true_rotation_in_order_and_wrap(self):
        make_accounts(["uid_a", "uid_b", "uid_c"])  # 按 uid 排序：a < b < c
        self.assertEqual(rotate_next_account("uid_a", "err").identity.uid, "uid_b")
        self.assertEqual(rotate_next_account("uid_b", "err").identity.uid, "uid_c")
        # 环绕：c 的下一个回到 a（a 的冷却 5 分钟内，但"环绕前进"仍应选它？
        # 否——a 在冷却期会被跳过，无其他候选时回退为 c 自身）
        accounts._recent_failures.clear()  # 清掉 a/b 的失败记录，验证纯环绕
        self.assertEqual(rotate_next_account("uid_c", "err").identity.uid, "uid_a")

    def test_single_account_returns_itself_without_cooldown_exempt(self):
        make_accounts(["uid_only"])
        sess = rotate_next_account("uid_only", "err")
        self.assertEqual(sess.identity.uid, "uid_only")
        # 不豁免冷却：失败记录保留，后续轮转仍视其为冷却中的失败账号
        self.assertIn("uid_only", accounts._recent_failures)
        active = self.sql("SELECT value FROM settings WHERE key = 'active_uid'")[0][0]
        self.assertEqual(active, "uid_only")

    def test_all_others_in_cooldown_falls_back_to_failed_account(self):
        make_accounts(["uid_a", "uid_b", "uid_c"])
        now = time.time()
        accounts._recent_failures["uid_b"] = now
        accounts._recent_failures["uid_c"] = now
        sess = rotate_next_account("uid_a", "err")
        # b/c 均在冷却 → 无其他候选，返回失败账号本身，且 a 的失败记录保留
        self.assertEqual(sess.identity.uid, "uid_a")
        self.assertIn("uid_a", accounts._recent_failures)

    def test_failed_account_excluded_and_cooldown_skipped(self):
        make_accounts(["uid_a", "uid_b", "uid_c"])
        now = time.time()
        accounts._recent_failures["uid_c"] = now  # c 在冷却
        # b 的下一个是 c（冷却中，跳过），再下一个是 a（不在冷却）→ 选 a
        self.assertEqual(rotate_next_account("uid_b", "err").identity.uid, "uid_a")

    def test_failed_uid_not_in_enabled_list_falls_back_to_first_enabled(self):
        make_accounts(["uid_a", "uid_b", "uid_c"])
        self.sql("UPDATE accounts SET enabled = 0 WHERE uid = 'uid_a'")
        sess = rotate_next_account("uid_a", "err")  # 失败账号已被禁用
        self.assertEqual(sess.identity.uid, "uid_b")

    def test_marks_failed_status_in_db(self):
        make_accounts(["uid_a", "uid_b"])
        rotate_next_account("uid_a", "boom")
        row = self.get_account_row("uid_a")
        self.assertEqual(row["last_status"], "failed")
        self.assertEqual(row["last_error"], "boom")


if __name__ == "__main__":
    unittest.main()
