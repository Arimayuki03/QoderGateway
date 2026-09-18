"""覆盖修复 9/12/13/14/15：get_db 关连接、CSP、build_qoder_body 不转发采样参数、main 控制台编码。"""
import sys
import sqlite3
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (str(REPO_ROOT / "src"), str(Path(__file__).resolve().parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import support  # noqa: E402  # 必须先于 qoder2api 导入（设置环境守卫）
from support import DBBackedTestCase  # noqa: E402

import qoder2api.app as app_module  # noqa: E402
import qoder2api.database as database  # noqa: E402
import qoder2api.bridge as bridge  # noqa: E402
from qoder2api.auth import AuthIdentity, new_session  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


class GetDbContextManagerTest(DBBackedTestCase):
    def test_connection_closed_after_context(self):
        holder = {}
        with database.get_db() as conn:
            holder["conn"] = conn
            conn.execute("SELECT 1").fetchone()
        # 旧实现泄漏连接；新实现退出 with 后必须已关闭
        with self.assertRaises(sqlite3.ProgrammingError):
            holder["conn"].execute("SELECT 1")

    def test_rollback_on_exception(self):
        with self.assertRaises(RuntimeError):
            with database.get_db() as conn:
                conn.execute(
                    "INSERT INTO settings (key, value) VALUES ('rollback_marker', '1')"
                )
                raise RuntimeError("boom")
        rows = self.sql("SELECT value FROM settings WHERE key = 'rollback_marker'")
        self.assertEqual(rows, [])


class SecurityHeadersTest(DBBackedTestCase):
    def test_csp_header_present(self):
        client = TestClient(app_module.app)
        r = client.get("/")
        self.assertEqual(r.status_code, 200)
        csp = r.headers.get("content-security-policy", "")
        self.assertTrue(csp.startswith("default-src 'self'"))
        self.assertIn("script-src 'self'", csp)
        self.assertIn("object-src 'none'", csp)
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertIn("https://fonts.googleapis.com", csp)
        self.assertIn("https://fonts.gstatic.com", csp)
        self.assertEqual(r.headers.get("x-frame-options"), "DENY")


class BuildQoderBodyTest(DBBackedTestCase):
    @staticmethod
    def _sess():
        identity = AuthIdentity(
            name="n", aid="u", uid="u", yx_uid="", organization_id="",
            organization_name="", user_type="personal_standard",
            security_oauth_token="tok", refresh_token="rt",
        )
        return new_session(identity, "mid", "mtok", "mtype")

    def test_sampling_params_not_forwarded_and_debug_logged(self):
        req = {
            "model": "lite",
            "messages": [{"role": "user", "content": "hi"}],
            "temperature": 0.7,
            "max_tokens": 100,
            "top_p": 0.9,
            "stop": ["END"],
        }
        with self.assertLogs("qoder2api.bridge", level="DEBUG") as cm:
            body, _model, _tools = bridge.build_qoder_body(req, self._sess())
        for key in ("temperature", "max_tokens", "top_p", "stop"):
            self.assertNotIn(key, body)
            self.assertTrue(any(key in line for line in cm.output), f"缺少 {key} 的 debug 提示")

    def test_no_debug_log_without_sampling_params(self):
        req = {"model": "lite", "messages": [{"role": "user", "content": "hi"}]}
        with self.assertNoLogs("qoder2api.bridge", level="DEBUG"):
            bridge.build_qoder_body(req, self._sess())


class MainEntryEncodingTest(unittest.TestCase):
    def test_main_reconfigures_console_to_utf8(self):
        """main() 入口应把 stdout/stderr 重配为 UTF-8（非 UTF-8 控制台防 UnicodeEncodeError）。

        不真正启动 uvicorn：把 uvicorn.run 换成桩后调用 main()，观察流编码。
        """
        import qoder2api.app as app_module

        class FakeStream:
            """鸭子类型流：只需暴露 reconfigure（main() 只调用该方法）。"""

            def __init__(self):
                self.encoding = "cp1252"
                self.reconfigured = False

            def reconfigure(self, **kwargs):
                self.reconfigured = True
                self.encoding = kwargs.get("encoding", self.encoding)

            def write(self, *_):
                return 0

        fake_out, fake_err = FakeStream(), FakeStream()
        original_out, original_err = sys.stdout, sys.stderr
        original_argv = sys.argv
        sys.argv = ["qoder2api", "--host", "127.0.0.1", "--port", "5050"]

        calls = {}

        def fake_run(app_name, **kwargs):
            calls["app"] = app_name

        sys.stdout, sys.stderr = fake_out, fake_err
        try:
            import uvicorn
            original_run = uvicorn.run
            uvicorn.run = fake_run
            try:
                app_module.main()
            finally:
                uvicorn.run = original_run
        finally:
            sys.stdout, sys.stderr = original_out, original_err
            sys.argv = original_argv

        self.assertTrue(fake_out.reconfigured)
        self.assertTrue(fake_err.reconfigured)
        self.assertEqual(fake_out.encoding, "utf-8")
        self.assertEqual(calls.get("app"), "qoder2api.app:app")


if __name__ == "__main__":
    unittest.main()
