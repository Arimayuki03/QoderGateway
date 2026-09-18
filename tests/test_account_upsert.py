"""覆盖修复 3：UPSERT 保留账号状态（凭据更新，状态列不被 INSERT OR REPLACE 抹掉）。"""
import asyncio
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (str(REPO_ROOT / "src"), str(Path(__file__).resolve().parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import support  # noqa: E402  # 必须先于 qoder2api 导入（设置环境守卫）
from support import DBBackedTestCase  # noqa: E402

import qoder2api.app as app_module  # noqa: E402
import qoder2api.registrar as registrar  # noqa: E402
from qoder2api.accounts import (  # noqa: E402
    batch_import_accounts,
    save_device_credentials,
    upsert_account_credentials,
)
from qoder2api.auth import AuthIdentity, new_session  # noqa: E402

# 账号级状态列 → 用于检测"冲突时被保留"的特征值
STATE_FIELDS = dict(
    enabled=0,
    quota=7,
    is_quota_exceeded=1,
    plan="PLAN_TIER_MAX",
    user_tag="Max",
    next_reset_at=123456,
    last_status="failed",
    last_error="boom",
)


class UpsertHelperTest(DBBackedTestCase):
    def test_conflict_updates_credentials_and_preserves_state(self):
        import qoder2api.database as database
        with database.get_db() as conn:
            upsert_account_credentials(conn, "acc-1", "N1", "personal_standard",
                                       "tok-1", "rt-1", "mid-1", "exp-1")
        self.set_account_state("acc-1", **STATE_FIELDS)

        # 同 uid 再次写入：只更新凭据类列
        with database.get_db() as conn:
            upsert_account_credentials(conn, "acc-1", "N2", "personal_standard",
                                       "tok-2", "rt-2", "mid-2", "exp-2")

        row = self.get_account_row("acc-1")
        # 凭据类列已更新
        self.assertEqual(row["security_oauth_token"], "tok-2")
        self.assertEqual(row["refresh_token"], "rt-2")
        self.assertEqual(row["machine_id"], "mid-2")
        self.assertEqual(row["token_expires_at"], "exp-2")
        self.assertEqual(row["name"], "N2")
        # 状态列全部保留
        for key, expected in STATE_FIELDS.items():
            self.assertEqual(row[key], expected, f"列 {key} 未保留")

    def test_new_row_gets_defaults(self):
        import qoder2api.database as database
        with database.get_db() as conn:
            upsert_account_credentials(conn, "acc-new", "New", "personal_standard",
                                       "tok-n", "rt-n", "mid-n", "exp-n")
        row = self.get_account_row("acc-new")
        self.assertEqual(row["enabled"], 1)
        self.assertEqual(row["last_status"], "ok")
        self.assertIsNone(row["last_error"])
        self.assertEqual(row["quota"], 0)
        self.assertEqual(row["is_quota_exceeded"], 0)
        self.assertEqual(row["plan"], "PLAN_TIER_PRO_TRIAL")
        self.assertEqual(row["user_tag"], "Pro Trial")
        self.assertIsNone(row["next_reset_at"])
        self.assertEqual(row["token_expires_at"], "exp-n")


class SaveDeviceCredentialsTest(DBBackedTestCase):
    def test_reimport_preserves_state_and_updates_credentials(self):
        cred1 = {"user_id": "dev-1", "token": "dt-1", "refresh_token": "rt-1",
                 "expires_at": "exp-1", "refresh_token_expires_at": ""}
        save_device_credentials(cred1)
        self.set_account_state("dev-1", **STATE_FIELDS)

        cred2 = {"user_id": "dev-1", "token": "dt-2", "refresh_token": "rt-2",
                 "expires_at": "exp-2", "refresh_token_expires_at": ""}
        save_device_credentials(cred2)

        row = self.get_account_row("dev-1")
        self.assertEqual(row["security_oauth_token"], "dt-2")
        self.assertEqual(row["refresh_token"], "rt-2")
        for key, expected in STATE_FIELDS.items():
            self.assertEqual(row[key], expected, f"列 {key} 未保留")
        # 设备授权导入仍会激活该账号
        active = self.sql("SELECT value FROM settings WHERE key = 'active_uid'")[0][0]
        self.assertEqual(active, "dev-1")


class RegistrarSaveAccountTest(DBBackedTestCase):
    def test_reimport_preserves_state_and_updates_credentials(self):
        acct = {"email": "a@b.c", "password": "p", "name": "Registered A"}
        cred1 = {"user_id": "reg-1", "token": "dt-1", "refresh_token": "rt-1", "expires_at": "exp-1"}
        registrar._save_account("t1", acct, cred1)
        self.set_account_state("reg-1", **STATE_FIELDS)

        cred2 = {"user_id": "reg-1", "token": "dt-2", "refresh_token": "rt-2", "expires_at": "exp-2"}
        registrar._save_account("t1", acct, cred2)

        row = self.get_account_row("reg-1")
        self.assertEqual(row["security_oauth_token"], "dt-2")
        for key, expected in STATE_FIELDS.items():
            self.assertEqual(row[key], expected, f"列 {key} 未保留")


class BatchImportTest(DBBackedTestCase):
    def test_reimport_preserves_state_and_updates_credentials(self):
        batch_import_accounts([{"user_id": "b-1", "token": "tok-1", "refresh_token": "rt-1"}])
        self.set_account_state("b-1", **STATE_FIELDS)
        batch_import_accounts([{"user_id": "b-1", "token": "tok-2", "refresh_token": "rt-2"}])
        row = self.get_account_row("b-1")
        self.assertEqual(row["security_oauth_token"], "tok-2")
        for key, expected in STATE_FIELDS.items():
            self.assertEqual(row[key], expected, f"列 {key} 未保留")


class SetSessionUpsertTest(DBBackedTestCase):
    """/ui/session 写入路径：mock create_session（零网络），验证 UPSERT 语义。"""

    def _mock_create_session(self, uid: str, token: str):
        identity = AuthIdentity(
            name="Mocked", aid=uid, uid=uid, yx_uid="", organization_id="",
            organization_name="", user_type="personal_standard",
            security_oauth_token=token, refresh_token="rt-" + token,
        )
        sess = new_session(identity, "mid-" + uid, "mtok", "mtype")

        async def fake_create_session(pat: str):
            return sess

        original = app_module.create_session
        app_module.create_session = fake_create_session
        self.addCleanup(setattr, app_module, "create_session", original)

    def test_set_session_preserves_state_on_reimport(self):
        self._mock_create_session("sess-1", "tok-1")
        asyncio.run(app_module.set_session({"pat": "jrt-test"}, None))
        self.set_account_state("sess-1", **STATE_FIELDS)

        self._mock_create_session("sess-1", "tok-2")
        asyncio.run(app_module.set_session({"pat": "jrt-test"}, None))

        row = self.get_account_row("sess-1")
        self.assertEqual(row["security_oauth_token"], "tok-2")
        for key, expected in STATE_FIELDS.items():
            self.assertEqual(row[key], expected, f"列 {key} 未保留")


if __name__ == "__main__":
    unittest.main()
