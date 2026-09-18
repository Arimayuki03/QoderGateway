"""覆盖修复 8：get_session 的 400 不再被聊天循环吞成 502（HTTPException 穿透）。"""
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
from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


class ChatErrorPropagationTest(DBBackedTestCase):
    def setUp(self) -> None:
        super().setUp()
        # 空库（无账号）：关闭 API Key 校验，并跳过自动导入分支（零网络、不读本地 auth 文件）
        self.sql("UPDATE settings SET value = '0' WHERE key = 'auth_required'")
        app_module._pat_import_attempted = True
        app_module._local_import_attempted = True

    def test_get_session_raises_http_400_when_no_account(self):
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(app_module.get_session())
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("No active session", ctx.exception.detail)

    def test_chat_completions_returns_400_not_502(self):
        client = TestClient(app_module.app)
        r = client.post(
            "/v1/chat/completions",
            json={"model": "lite", "messages": [{"role": "user", "content": "hi"}]},
        )
        self.assertEqual(r.status_code, 400)
        self.assertIn("No active session", r.json()["detail"])


if __name__ == "__main__":
    unittest.main()
