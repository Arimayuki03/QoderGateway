"""测试公共设施：在导入 qoder2api 之前接好环境，隔离真实 ~/.qoder 数据库与网络。

约定：
- 每个测试文件开头先把 <repo>/src 与 tests 目录插入 sys.path，再 import support；
- support 在任何 qoder2api.* 导入之前设置环境变量（QODER_DB_PATH / QODER_PAT /
  QODER_ADMIN_PASSWORD），保证 database.DB_PATH 解析到临时目录、不触发自动导入与网络；
- DBBackedTestCase 为每个测试准备一块全新临时 SQLite 库（init_db 显式建库，
  对应"建库已从导入期下沉到 lifespan"的新行为），并清空进程内的防爆破/轮转状态。
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = str(REPO_ROOT / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

# ---- 环境守卫（必须在 qoder2api.* 首次导入前执行）----
# 1) DB 指到临时目录，绝不读写真实 ~/.qoder/qoder2api.db
os.environ.setdefault(
    "QODER_DB_PATH",
    str(Path(tempfile.mkdtemp(prefix="qoder2api_tests_")) / "default.db"),
)
# 2) QODER_PAT 强制置空：项目根 .env 的 QODER_PAT（若存在）不得触发自动导入/网络调用
#    （env.load_dotenv 只在变量缺失时写入，这里预先占位即可屏蔽）
os.environ["QODER_PAT"] = ""
# 3) 固定管理口令：避免 init_db 打印一次性口令横幅，测试也可用已知口令
os.environ.setdefault("QODER_ADMIN_PASSWORD", "test-admin-token")

TEST_GATEWAY_TOKEN = "test-admin-token"


def fake_request(host: str = "127.0.0.1"):
    """构造最小 starlette Request：check_gateway_token 只用到 request.client.host。"""
    from starlette.requests import Request as StarletteRequest

    return StarletteRequest({"type": "http", "client": (host, 12345), "headers": [], "query_string": b""})


class DBBackedTestCase(unittest.TestCase):
    """每个测试一块全新临时 SQLite 库 + 进程内状态清零（互不污染）。"""

    def setUp(self) -> None:
        import qoder2api.accounts as accounts
        import qoder2api.app as app_module
        import qoder2api.database as database

        self._tmp = tempfile.TemporaryDirectory(prefix="qoder2api_test_")
        self.addCleanup(self._tmp.cleanup)
        self._old_db_path = database.DB_PATH
        self.addCleanup(setattr, database, "DB_PATH", self._old_db_path)
        database.DB_PATH = Path(self._tmp.name) / "test.db"
        database.init_db()

        # 网关防爆破状态（app）与轮转冷却状态（accounts）逐测试清零
        app_module._reset_auth_state()
        self.addCleanup(app_module._reset_auth_state)
        accounts._recent_failures.clear()
        self.addCleanup(accounts._recent_failures.clear)

        # 进程级一次性自动导入标记：默认复位，需要的测试自行置 True 跳过导入分支
        app_module._pat_import_attempted = False
        app_module._local_import_attempted = False

    # ---- 小工具 ----
    def sql(self, query: str, params: tuple = ()):
        import qoder2api.database as database

        with database.get_db() as conn:
            return conn.execute(query, params).fetchall()

    def gateway_token(self) -> str:
        return self.sql("SELECT value FROM settings WHERE key = 'gateway_token'")[0][0]

    def set_account_state(self, uid: str, **fields) -> None:
        """把指定账号的列改成便于检测"是否被 UPSERT 保留"的值。"""
        assert fields
        cols = ", ".join(f"{k} = ?" for k in fields)
        self.sql(f"UPDATE accounts SET {cols} WHERE uid = ?", tuple(fields.values()) + (uid,))

    def get_account_row(self, uid: str):
        rows = self.sql("SELECT * FROM accounts WHERE uid = ?", (uid,))
        return dict(rows[0]) if rows else None
