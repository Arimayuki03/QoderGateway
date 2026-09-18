import logging
import os
import secrets
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .env import load_dotenv

load_dotenv()

logger = logging.getLogger("qoder2api.database")


def _resolve_db_path() -> Path:
    """数据库路径：默认 ~/.qoder/qoder2api.db。

    QODER_DB_PATH 环境变量可覆盖（增量、向后兼容）：主要供测试把库指到
    临时目录，避免读写真实的 ~/.qoder 数据库；须在导入本模块前设置。
    """
    override = os.getenv("QODER_DB_PATH", "").strip()
    if override:
        return Path(override)
    return Path.home() / ".qoder" / "qoder2api.db"


DB_PATH = _resolve_db_path()


@contextmanager
def get_db() -> Iterator[sqlite3.Connection]:
    """连接上下文管理器：成功提交、异常回滚、退出必关连接。

    旧实现返回裸连接，调用方的 `with conn:`（sqlite3 连接上下文）只负责
    提交/回滚、从不关闭，长期运行会累积泄漏句柄；改为 contextmanager 后
    统一 `with get_db() as conn:`，提交/回滚语义不变且必关连接。
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # 多线程（refresh 线程 / to_thread / 注册机）并发写时等待锁而不是立刻抛 locked
    conn.execute("PRAGMA busy_timeout = 5000")
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_db() as conn:
        # WAL：读写不互斥，缓解 refresh 线程与请求处理并发写时的 database is locked
        conn.execute("PRAGMA journal_mode=WAL")
        # Accounts Table
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS accounts (
                uid TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                user_type TEXT,
                security_oauth_token TEXT NOT NULL,
                refresh_token TEXT NOT NULL,
                machine_id TEXT NOT NULL,
                enabled INTEGER DEFAULT 1,
                last_status TEXT DEFAULT 'ok',
                last_error TEXT,
                quota INTEGER DEFAULT 0,
                is_quota_exceeded INTEGER DEFAULT 0,
                plan TEXT,
                user_tag TEXT,
                next_reset_at INTEGER
            )
            """
        )
        
        # Allowed API Keys Table (for proxy routing auth)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS allowed_keys (
                api_key TEXT PRIMARY KEY
            )
            """
        )
        
        # Global Settings Table
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
            """
        )
        
        # Set default gateway token if not present
        res = conn.execute("SELECT value FROM settings WHERE key = 'gateway_token'").fetchone()
        if not res:
            # 仅首次建库时读取 env；之后以 SQLite 为准（控制台可改）
            env_token = os.getenv("QODER_ADMIN_PASSWORD", "").strip()
            if env_token:
                default_token = env_token
            else:
                # 留空时生成随机口令，不再使用可被猜到的默认口令 "admin"
                default_token = secrets.token_urlsafe(12)
                print(
                    "\n"
                    "======================================================================\n"
                    "[安全提示] 未设置 QODER_ADMIN_PASSWORD，已自动生成管理口令：\n"
                    "\n"
                    f"    {default_token}\n"
                    "\n"
                    "该口令仅显示这一次，请妥善保存；也可设置 QODER_ADMIN_PASSWORD 后删除数据库重建。\n"
                    f"数据库位置: {DB_PATH}\n"
                    "======================================================================\n",
                    flush=True,
                )
            conn.execute("INSERT INTO settings (key, value) VALUES ('gateway_token', ?)", (default_token,))

        res_auth = conn.execute("SELECT value FROM settings WHERE key = 'auth_required'").fetchone()
        if not res_auth:
            # 安全默认：未显式配置时要求 API Key 鉴权
            conn.execute("INSERT INTO settings (key, value) VALUES ('auth_required', '1')")

        # 历史库仍使用默认口令 "admin" 时不强制迁移，仅输出显著安全警告（不阻断服务）
        row_token = conn.execute("SELECT value FROM settings WHERE key = 'gateway_token'").fetchone()
        if row_token and row_token[0] == "admin":
            logger.warning(
                "安全警告：管理口令仍为默认值 'admin'，存在被猜解风险。"
                "请尽快在 WebUI 控制台修改，或设置 QODER_ADMIN_PASSWORD 后删除数据库重建。"
            )

        # token_expires_at 列（幂等：已存在则忽略）
        try:
            conn.execute("ALTER TABLE accounts ADD COLUMN token_expires_at TEXT")
        except Exception:
            pass


# 建库时机：从导入期（原模块级 init_db()）下沉到 FastAPI lifespan（app.py），
# 消除 import 副作用；lifespan 中保证 init_db() 先于 start_refresh_loop() 与
# 任何请求处理执行。绕过 lifespan 直接使用本模块（如测试）需自行调用 init_db()。
