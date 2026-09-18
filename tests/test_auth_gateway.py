"""覆盖修复 1/2：常量时间比较（非 ASCII 不再 TypeError）与防爆破下沉到 check_gateway_token。"""
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (str(REPO_ROOT / "src"), str(Path(__file__).resolve().parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import support  # noqa: E402  # 必须先于 qoder2api 导入（设置环境守卫）
from support import DBBackedTestCase, TEST_GATEWAY_TOKEN, fake_request  # noqa: E402

import qoder2api.app as app_module  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

SECRET = "中文口令🔒abc"  # 含非 ASCII 的口令（旧实现直接 compare_digest 会抛 TypeError）


class ConstantTimeEqTest(DBBackedTestCase):
    def test_non_ascii_equal_and_unequal(self):
        self.assertTrue(app_module._constant_time_eq(SECRET, SECRET))
        self.assertFalse(app_module._constant_time_eq(SECRET, SECRET + "x"))
        self.assertFalse(app_module._constant_time_eq("口令A", "口令B"))

    def test_ascii_still_works(self):
        self.assertTrue(app_module._constant_time_eq("abc123", "abc123"))
        self.assertFalse(app_module._constant_time_eq("abc123", "abc124"))

    def test_non_string_inputs_fail_closed(self):
        self.assertFalse(app_module._constant_time_eq(None, SECRET))
        self.assertFalse(app_module._constant_time_eq(SECRET, None))
        self.assertFalse(app_module._constant_time_eq(123, SECRET))
        self.assertFalse(app_module._constant_time_eq(None, None))

    def test_bytes_accepted(self):
        self.assertTrue(app_module._constant_time_eq(b"abc", "abc"))

    def test_api_key_allowed_no_length_leak_precheck(self):
        self.assertTrue(app_module._api_key_allowed("中文key", ["k1", "中文key"]))
        self.assertFalse(app_module._api_key_allowed("中文keY", ["k1", "中文key"]))
        self.assertFalse(app_module._api_key_allowed("k1", []))


class CheckGatewayTokenTest(DBBackedTestCase):
    def _set_secret(self, value: str) -> None:
        self.sql("UPDATE settings SET value = ? WHERE key = 'gateway_token'", (value,))

    def test_correct_non_ascii_token_passes_without_typeerror(self):
        self._set_secret(SECRET)
        # 旧实现此处抛 TypeError；新实现应安静通过（不抛任何异常）
        app_module.check_gateway_token(fake_request(), SECRET)

    def test_wrong_token_raises_401(self):
        self._set_secret(SECRET)
        with self.assertRaises(HTTPException) as ctx:
            app_module.check_gateway_token(fake_request(), "wrong-口令")
        self.assertEqual(ctx.exception.status_code, 401)

    def test_missing_header_fails_closed(self):
        self._set_secret(SECRET)
        with self.assertRaises(HTTPException) as ctx:
            app_module.check_gateway_token(fake_request(), None)
        self.assertEqual(ctx.exception.status_code, 401)

    def test_empty_configured_token_fails_closed(self):
        self._set_secret("")
        with self.assertRaises(HTTPException) as ctx:
            app_module.check_gateway_token(fake_request(), SECRET)
        self.assertEqual(ctx.exception.status_code, 401)


class BruteForceProtectionTest(DBBackedTestCase):
    """锁定状态由 check_gateway_token 与 /ui/verify 共享（模块级状态）。"""

    def test_lockout_after_five_failures_even_with_correct_token(self):
        client = TestClient(app_module.app)
        correct = self.gateway_token()
        for _ in range(5):
            app_module._auth_attempts.pop("testclient", None)  # 跳过 5s 冷却（测试加速）
            r = client.get("/ui/accounts", headers={"X-Gateway-Token": "wrong"})
            self.assertEqual(r.status_code, 401)
        # 第 6 次：即使口令正确也被锁拒绝（429）
        r = client.get("/ui/accounts", headers={"X-Gateway-Token": correct})
        self.assertEqual(r.status_code, 429)
        self.assertIn("锁定", r.json()["detail"])

    def test_cooldown_after_failure_without_new_failure_recorded(self):
        client = TestClient(app_module.app)
        r1 = client.post("/ui/verify", json={"token": "wrong"})
        self.assertEqual(r1.status_code, 401)
        # 立即重试：命中 5s 冷却 → 429，且不新增失败计数
        r2 = client.post("/ui/verify", json={"token": "wrong"})
        self.assertEqual(r2.status_code, 429)
        self.assertIn("频繁", r2.json()["detail"])
        self.assertEqual(len(app_module._auth_failures["testclient"]), 1)

    def test_success_clears_failure_count(self):
        client = TestClient(app_module.app)
        correct = self.gateway_token()
        for _ in range(3):
            app_module._auth_attempts.pop("testclient", None)
            client.get("/ui/accounts", headers={"X-Gateway-Token": "wrong"})
        app_module._auth_attempts.pop("testclient", None)
        # 失败 3 次后验证成功 → 计数清零；再失败一次也不会立刻被锁
        r = client.post("/ui/verify", json={"token": correct})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(app_module._auth_failures.get("testclient"), None)
        app_module._auth_attempts.pop("testclient", None)
        r = client.post("/ui/verify", json={"token": "wrong"})
        self.assertEqual(r.status_code, 401)

    def test_reset_auth_state_for_test_isolation(self):
        client = TestClient(app_module.app)
        correct = self.gateway_token()
        for _ in range(5):
            app_module._auth_attempts.pop("testclient", None)
            client.get("/ui/accounts", headers={"X-Gateway-Token": "wrong"})
        app_module._reset_auth_state()
        r = client.get("/ui/accounts", headers={"X-Gateway-Token": correct})
        self.assertEqual(r.status_code, 200)

    def test_verify_failure_protects_other_endpoints(self):
        """防爆破状态共享：/ui/verify 失败后，其他 /ui/* 端点同样被冷却拦截。"""
        client = TestClient(app_module.app)
        correct = self.gateway_token()
        r = client.post("/ui/verify", json={"token": "wrong"})
        self.assertEqual(r.status_code, 401)
        # 正确口令但处于失败后的 5s 冷却期内 → 429（老实现里该端点只依赖自己的比较，无任何限速）
        r = client.get("/ui/accounts", headers={"X-Gateway-Token": correct})
        self.assertEqual(r.status_code, 429)

    def test_check_gateway_token_records_failure_directly(self):
        req = fake_request("1.2.3.4")
        with self.assertRaises(HTTPException):
            app_module.check_gateway_token(req, "wrong")
        self.assertEqual(len(app_module._auth_failures["1.2.3.4"]), 1)
        self.assertLessEqual(time.time() - app_module._auth_attempts["1.2.3.4"], 1.0)


if __name__ == "__main__":
    unittest.main()
