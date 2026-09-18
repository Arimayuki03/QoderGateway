import argparse
import asyncio
import collections
import hashlib
import hmac
import os
import sys
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Header, Depends, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .auth import SessionContext, create_session
from .bridge import complete_openai_response, stream_openai_response
from .config import load_config, save_config
from .database import get_db, init_db
from .env import env_bool
from .accounts import (
    db_load_accounts,
    db_get_settings,
    db_set_settings,
    import_current_auth,
    get_active_session,
    rotate_next_account,
    batch_import_accounts,
    save_device_credentials,
    upsert_account_credentials,
)
from .registrar import (
    get_registrar_status,
    start_registration,
    stop_registration,
    device_flow_params,
    device_poll_once,
)
from .tokens import (
    refresh_all_account_tokens,
    refresh_one_account,
    get_account_quota,
    get_all_accounts_quota,
    start_refresh_loop,
)

BASE_DIR = os.path.dirname(__file__)
INDEX_HTML = Path(BASE_DIR) / "static" / "index.html"
CONSOLE_HTML = Path(BASE_DIR) / "static" / "console.html"
DOCS_HTML = Path(BASE_DIR) / "static" / "docs.html"

@asynccontextmanager
async def lifespan(_: FastAPI):
    # 建库/迁移从导入期（原 database.py 模块级 init_db()）下沉到启动期，消除 import 副作用；
    # 必须先于 start_refresh_loop：刷新线程首轮就会查询 accounts 表
    init_db()
    # 应用启动时开启 token 定时刷新线程：uvicorn 直接加载 app 与 main() 入口都会经过
    # lifespan；start_refresh_loop 内部幂等，重复调用也只会启动一次
    start_refresh_loop()
    yield


app = FastAPI(
    title="qoder2api-python",
    lifespan=lifespan,
    # 关闭 FastAPI 自带的交互文档与 OpenAPI schema（项目自己的文档站是 /documents），
    # 避免把接口结构暴露给未鉴权访问者
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.mount("/assets", StaticFiles(directory=os.path.join(BASE_DIR, "static", "assets")), name="assets")

# 基础安全响应头（S6）：纯 ASGI 中间件实现，不包装响应流（不影响 SSE），也不校验 Host
# （会破坏局域网直接以 IP/主机名访问的场景）
# CSP：前端产物无内联 script（外链 module），样式需 'unsafe-inline' 与 Google Fonts /
# cdnfonts 外链（构建产物引用），字体走 fonts.gstatic.com / fonts.cdnfonts.com 与 data:
_SECURITY_HEADERS = (
    (b"x-frame-options", b"DENY"),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"same-origin"),
    (
        b"content-security-policy",
        b"default-src 'self'; script-src 'self'; "
        b"style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://fonts.cdnfonts.com; "
        b"font-src 'self' data: https://fonts.gstatic.com https://fonts.cdnfonts.com; "
        b"img-src 'self' data:; connect-src 'self'; object-src 'none'; "
        b"frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
    ),
)


class SecurityHeadersMiddleware:
    """为所有 HTTP 响应补充基础安全响应头；响应已携带同名头时不覆盖。"""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers") or [])
                present = {name for name, _ in headers}
                for name, value in _SECURITY_HEADERS:
                    if name not in present:
                        headers.append((name, value))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)


app.add_middleware(SecurityHeadersMiddleware)

_local_auth_error: str | None = None
# 无账号时的自动导入每个进程只尝试一次，避免 /ui/status 轮询反复触发导入与刷日志
_pat_import_attempted = False
_local_import_attempted = False

logs_queue = collections.deque(maxlen=150)

# 设备授权导入的进行中会话：nonce → {"poll_url", "expires_at"}
_device_auth_sessions: dict[str, dict[str, Any]] = {}
_DEVICE_AUTH_TTL = 330.0  # 授权 URL 有效期 5 分钟 + 余量


def add_log(msg: str, level: str = "INFO") -> None:
    timestamp = datetime.now().strftime("%H:%M:%S")
    formatted = f"[{timestamp}] [{level}] {msg}"
    logs_queue.append(formatted)
    print(formatted)


# Add initial logs
add_log("Qoder2API Python Bridge initialized.")



def _constant_time_eq(a: Any, b: Any) -> bool:
    """常量时间比较口令/密钥：两边先各自 SHA-256 成定长摘要再 hmac.compare_digest。

    同时消除两类问题：
    1. compare_digest 直接比较 str 时任一侧含非 ASCII 字符会抛 TypeError（→ 500）；
    2. 长度预检/短路比较造成的长度侧信道（摘要定长，耗时与输入长度无关）。
    非 str/bytes（如缺失的请求头）一律视为不相等，绝不抛错。
    """
    if not isinstance(a, (str, bytes)) or not isinstance(b, (str, bytes)):
        return False
    if isinstance(a, str):
        a = a.encode("utf-8")
    if isinstance(b, str):
        b = b.encode("utf-8")
    return hmac.compare_digest(hashlib.sha256(a).digest(), hashlib.sha256(b).digest())


# 网关口令防爆破（纯内存实现，本地单用户场景）：
# 失败后 5s 冷却；15 分钟窗口内失败满 5 次锁定 15 分钟。
# 原来只覆盖 /ui/verify，现下沉到 check_gateway_token，所有 /ui/* 端点自动获得保护；
# /ui/verify 复用同一套状态。check_gateway_token 是同步依赖（线程池执行），
# /ui/verify 是 async（事件循环执行），故用锁保护共享状态。
_auth_attempts: dict[str, float] = {}        # 来源 -> 最近一次失败时间（冷却锚点）
_auth_failures: dict[str, list[float]] = {}  # 来源 -> 失败时间戳列表
_AUTH_COOLDOWN = 5.0
_AUTH_MAX_FAILURES = 5
_AUTH_FAIL_WINDOW = 900.0
_AUTH_LOCKOUT = 900.0
_AUTH_GC_INTERVAL = 300.0
_auth_last_gc = 0.0
_auth_state_lock = threading.Lock()


def _reset_auth_state() -> None:
    """清空防爆破状态（测试隔离用；生产运行期无需调用）。"""
    global _auth_last_gc
    with _auth_state_lock:
        _auth_attempts.clear()
        _auth_failures.clear()
        _auth_last_gc = 0.0


def _auth_rate_limit_check(client_ip: str) -> None:
    """锁定/冷却检查：命中则抛 429，否则放行。调用顺序：先查锁 → 再比较 → 失败计数。"""
    global _auth_last_gc
    now = time.time()
    with _auth_state_lock:
        if now - _auth_last_gc > _AUTH_GC_INTERVAL:
            # 定期清理过期记录，避免字典无限增长
            for ip, ts in list(_auth_attempts.items()):
                if now - ts > 3600:
                    _auth_attempts.pop(ip, None)
            for ip, fails in list(_auth_failures.items()):
                if not fails or now - fails[-1] > 3600:
                    _auth_failures.pop(ip, None)
            _auth_last_gc = now
        recent_fails = [ts for ts in _auth_failures.get(client_ip, []) if now - ts < _AUTH_FAIL_WINDOW]
        _auth_failures[client_ip] = recent_fails
        if len(recent_fails) >= _AUTH_MAX_FAILURES and now < recent_fails[-1] + _AUTH_LOCKOUT:
            raise HTTPException(status_code=429, detail="失败次数过多，已临时锁定，请 15 分钟后再试")
        if now - _auth_attempts.get(client_ip, 0.0) < _AUTH_COOLDOWN:
            raise HTTPException(status_code=429, detail="尝试过于频繁，请稍后再试")


def _auth_record_failure(client_ip: str) -> None:
    now = time.time()
    with _auth_state_lock:
        _auth_attempts[client_ip] = now
        _auth_failures.setdefault(client_ip, []).append(now)


def _auth_reset_client(client_ip: str) -> None:
    """认证成功：清空该来源的冷却与失败记录（成功清零计数）。"""
    with _auth_state_lock:
        _auth_attempts.pop(client_ip, None)
        _auth_failures.pop(client_ip, None)


def check_gateway_token(request: Request, x_gateway_token: str | None = Header(default=None)) -> None:
    client_ip = request.client.host if request.client else "unknown"
    _auth_rate_limit_check(client_ip)
    config = load_config()
    # 库中缺行时为空串，直接 fail closed（不再兜底默认口令）
    gateway_token = str(config.get("gateway_token") or "")
    if not gateway_token or not _constant_time_eq(x_gateway_token, gateway_token):
        _auth_record_failure(client_ip)
        raise HTTPException(status_code=401, detail="Unauthorized gateway access")
    _auth_reset_client(client_ip)


@app.post("/ui/verify")
async def verify_gateway(payload: dict[str, Any], request: Request) -> dict[str, Any]:
    """登录验证：与 check_gateway_token 共用同一套防爆破状态（冷却/锁定/成功清零）。"""
    client_ip = request.client.host if request.client else "unknown"
    _auth_rate_limit_check(client_ip)
    token = payload.get("token")
    token = token.strip() if isinstance(token, str) else ""
    config = load_config()
    gateway_token = str(config.get("gateway_token") or "")
    if token and gateway_token and _constant_time_eq(token, gateway_token):
        _auth_reset_client(client_ip)
        return {"status": "ok"}
    _auth_record_failure(client_ip)
    raise HTTPException(status_code=401, detail="Invalid Gateway Token")


async def get_session() -> SessionContext:
    global _local_auth_error, _pat_import_attempted, _local_import_attempted
    # 同步 SQLite 放线程池执行，避免阻塞事件循环（聊天热路径与 /ui/status 共用本函数）
    data = await asyncio.to_thread(db_load_accounts)
    if not data["accounts"]:
        # Try importing environment PAT if available (once per process)
        pat = os.getenv("QODER_PAT", "").strip()
        if pat and not _pat_import_attempted:
            _pat_import_attempted = True
            add_log("No accounts stored. Importing QODER_PAT from environment...")
            try:
                sess = await create_session(pat)
                with get_db() as conn:
                    # ON CONFLICT 只更新凭据类列，保留 enabled/quota/plan 等既有状态
                    upsert_account_credentials(
                        conn,
                        uid=sess.identity.uid,
                        name=sess.identity.name or "Environment PAT",
                        user_type=sess.identity.user_type,
                        security_oauth_token=sess.identity.security_oauth_token,
                        refresh_token=sess.identity.refresh_token,
                        machine_id=sess.machine_id,
                    )
                db_set_settings("active_uid", sess.identity.uid)
                add_log(f"Imported environment PAT as account: {sess.identity.name}")
                _local_auth_error = None
            except Exception as exc:
                add_log(f"Failed to import environment PAT: {exc}", "ERROR")

        data = await asyncio.to_thread(db_load_accounts)
        if not data["accounts"] and not _local_import_attempted:
            _local_import_attempted = True
            add_log("No accounts stored. Attempting to auto-import current local Qoder auth session...")
            try:
                await import_current_auth()
                add_log("Auto-imported current local Qoder session successfully.")
                _local_auth_error = None
            except Exception as exc:
                _local_auth_error = str(exc)
                add_log(f"Auto-import of local session failed: {exc}", "WARNING")

    try:
        return await asyncio.to_thread(get_active_session)
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"No active session available: {exc}. Please configure/import an account first."
        )


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    if not env_bool("QODER_ENABLE_LANDING", True):
        raise HTTPException(status_code=404, detail="Landing page is disabled")
    return HTMLResponse(INDEX_HTML.read_text(encoding="utf-8"))


@app.get("/console", response_class=HTMLResponse)
async def console() -> HTMLResponse:
    return HTMLResponse(CONSOLE_HTML.read_text(encoding="utf-8"))


@app.get("/documents", response_class=HTMLResponse)
async def documents() -> HTMLResponse:
    if not env_bool("QODER_ENABLE_DOCUMENTS", True):
        raise HTTPException(status_code=404, detail="Documents page is disabled")
    return HTMLResponse(DOCS_HTML.read_text(encoding="utf-8"))


@app.get("/ui/status")
async def status(verify: None = Depends(check_gateway_token)) -> dict[str, Any]:
    try:
        await get_session()
    except Exception:
        pass

    data = db_load_accounts()
    active_uid = data.get("active_uid")
    active_acc = None
    for acc in data["accounts"]:
        if acc["uid"] == active_uid:
            active_acc = acc
            break

    if active_acc is not None:
        return {
            "ready": True,
            "mode": "accounts",
            "username": active_acc["name"],
            "uid": active_acc["uid"],
            "user_type": active_acc["user_type"],
            "error": None,
            "accounts_count": len(data["accounts"])
        }
    return {
        "ready": False,
        "mode": "none",
        "username": None,
        "uid": None,
        "user_type": None,
        "error": _local_auth_error,
        "accounts_count": len(data["accounts"])
    }


@app.get("/ui/accounts")
async def get_accounts(verify: None = Depends(check_gateway_token)) -> dict[str, Any]:
    return db_load_accounts()


@app.post("/ui/accounts/import")
async def import_account(verify: None = Depends(check_gateway_token)) -> dict[str, Any]:
    try:
        acc = await import_current_auth()
        add_log(f"Imported local Qoder session account: {acc['name']}")
        return {"status": "ok", "account": acc}
    except Exception as exc:
        add_log(f"Failed to import local session account: {exc}", "ERROR")
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/ui/accounts/batch-import")
async def batch_import(payload: dict[str, Any], verify: None = Depends(check_gateway_token)) -> dict[str, Any]:
    """批量导入注册机导出的 JSON：{"accounts": [{user_id, token, refresh_token, ...}]}。"""
    records = payload.get("accounts") or payload.get("records") or []
    if not isinstance(records, list) or not records:
        raise HTTPException(status_code=400, detail="accounts 数组为空")
    result = batch_import_accounts(records)
    add_log(f"Batch imported {result['imported']} accounts (skipped {result['skipped']})")
    return {"status": "ok", **result}


@app.post("/ui/accounts/select")
async def select_account(payload: dict[str, Any], verify: None = Depends(check_gateway_token)) -> dict[str, Any]:
    uid = payload.get("uid")
    if not uid:
        raise HTTPException(status_code=400, detail="uid is required")
    with get_db() as conn:
        res = conn.execute("SELECT uid FROM accounts WHERE uid = ?", (uid,)).fetchone()
        if not res:
            raise HTTPException(status_code=404, detail="Account not found")
    db_set_settings("active_uid", uid)
    add_log(f"Selected active account UID: {uid}")
    return {"status": "ok"}


@app.post("/ui/accounts/toggle")
async def toggle_account(payload: dict[str, Any], verify: None = Depends(check_gateway_token)) -> dict[str, Any]:
    uid = payload.get("uid")
    enabled = bool(payload.get("enabled", True))
    if not uid:
        raise HTTPException(status_code=400, detail="uid is required")
    enabled_val = 1 if enabled else 0
    with get_db() as conn:
        res = conn.execute("UPDATE accounts SET enabled = ? WHERE uid = ?", (enabled_val, uid))
        if res.rowcount == 0:
            raise HTTPException(status_code=404, detail="Account not found")
    add_log(f"Account toggle enabled={enabled} for UID: {uid}")
    return {"status": "ok"}


@app.post("/ui/accounts/refresh-tokens")
async def refresh_account_tokens(verify: None = Depends(check_gateway_token)) -> dict[str, Any]:
    """手动触发：刷新所有账号的 token（drt- → deviceToken/refresh）。"""
    # 同步 httpx 放线程池执行，避免阻塞事件循环（每账号最长 25s）
    result = await asyncio.to_thread(refresh_all_account_tokens)
    add_log(f"Token refresh: ok={result['ok']} failed={result['failed']} total={result['total']}")
    return {"status": "ok", **result}


@app.get("/ui/accounts/quota")
async def accounts_quota(verify: None = Depends(check_gateway_token)) -> dict[str, Any]:
    """查看所有启用账号的限额（GET /api/v2/quota/usage）。"""
    return await asyncio.to_thread(get_all_accounts_quota)


@app.delete("/ui/accounts/{uid}")
async def delete_account(uid: str, verify: None = Depends(check_gateway_token)) -> dict[str, Any]:
    with get_db() as conn:
        res = conn.execute("DELETE FROM accounts WHERE uid = ?", (uid,))
        if res.rowcount == 0:
            raise HTTPException(status_code=404, detail="Account not found")
            
    active_uid = db_get_settings("active_uid")
    if active_uid == uid:
        data = db_load_accounts()
        new_active = data["accounts"][0]["uid"] if data["accounts"] else None
        if new_active:
            db_set_settings("active_uid", new_active)
        else:
            with get_db() as conn:
                conn.execute("DELETE FROM settings WHERE key = 'active_uid'")
    add_log(f"Deleted account UID: {uid}")
    return {"status": "ok"}


@app.get("/ui/logs")
async def get_logs(verify: None = Depends(check_gateway_token)) -> list[str]:
    return list(logs_queue)


@app.post("/ui/registrar/start")
async def registrar_start(payload: dict[str, Any] | None = None, verify: None = Depends(check_gateway_token)) -> dict[str, Any]:
    """启动注册机（无限循环：parents 个母线程 × 每批 3 个子任务，直到调用 stop）。

    body 可选：{"parents": 2}  —— 母线程数（1-6），每母线程 3 子任务并发。
    """
    payload = payload or {}
    try:
        parents = int(payload.get("parents", 2))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="parents 参数无效")
    return start_registration(parents=parents)


@app.post("/ui/registrar/stop")
async def registrar_stop(verify: None = Depends(check_gateway_token)) -> dict[str, Any]:
    """请求停止：当前批次完成后停止，返回本次注册统计。"""
    return stop_registration()


@app.get("/ui/registrar/status")
async def registrar_status(verify: None = Depends(check_gateway_token)) -> dict[str, Any]:
    """查询注册机任务状态（stage / logs / result）。"""
    return get_registrar_status()


@app.get("/ui/config")
async def get_ui_config(verify: None = Depends(check_gateway_token)) -> dict[str, Any]:
    config = load_config()
    # 管理口令不下发前端，避免明文往返与落日志
    config.pop("gateway_token", None)
    return config


@app.post("/ui/config")
async def post_ui_config(payload: dict[str, Any], verify: None = Depends(check_gateway_token)) -> dict[str, Any]:
    # 前端不再持有 gateway_token：只允许显式传入时才更新口令
    payload = {k: v for k, v in payload.items() if k != "gateway_token" or v}
    save_config(payload)
    add_log("API Key configuration updated.")
    return {"status": "ok"}


@app.post("/ui/device-auth/start")
async def device_auth_start(verify: None = Depends(check_gateway_token)) -> dict[str, Any]:
    """设备授权导入（workbuddy login 风格）：生成授权 URL，浏览器登录后轮询取凭据。

    无需 Qoder CLI。授权 URL 5 分钟有效；用 /ui/device-auth/poll 轮询结果。
    """
    now = time.time()
    expired = [k for k, v in _device_auth_sessions.items() if now > v["expires_at"]]
    for k in expired:
        _device_auth_sessions.pop(k, None)

    flow = device_flow_params()
    nonce = flow["nonce"]
    _device_auth_sessions[nonce] = {"poll_url": flow["poll_url"], "expires_at": now + _DEVICE_AUTH_TTL}
    add_log("Device auth import started, waiting for browser authorization...")
    return {"status": "ok", "auth_url": flow["auth_url"], "nonce": nonce, "expires_in": int(_DEVICE_AUTH_TTL)}


@app.post("/ui/device-auth/poll")
async def device_auth_poll(payload: dict[str, Any], verify: None = Depends(check_gateway_token)) -> dict[str, Any]:
    """轮询设备授权结果：pending=等待授权 / ok=凭据已入库 / expired=会话过期。"""
    nonce = str(payload.get("nonce") or "")
    sess = _device_auth_sessions.get(nonce)
    if not sess or time.time() > sess["expires_at"]:
        _device_auth_sessions.pop(nonce, None)
        return {"status": "expired"}

    try:
        cred = await asyncio.to_thread(device_poll_once, sess["poll_url"])
    except Exception as exc:
        return {"status": "pending", "note": f"poll error: {exc}"}

    if cred is None:
        return {"status": "pending"}

    _device_auth_sessions.pop(nonce, None)
    try:
        saved = save_device_credentials(cred)
    except Exception as exc:
        add_log(f"Device auth credential save failed: {exc}", "ERROR")
        raise HTTPException(status_code=400, detail=str(exc))

    add_log(f"Device auth import success: {saved['uid']}")
    fetch_accounts_data = db_load_accounts()
    acc = next((a for a in fetch_accounts_data["accounts"] if a["uid"] == saved["uid"]), None)
    return {"status": "ok", "account": acc or saved}


@app.post("/ui/session")
async def set_session(payload: dict[str, Any], verify: None = Depends(check_gateway_token)) -> dict[str, Any]:
    global _local_auth_error
    pat = str(payload.get("pat") or os.getenv("QODER_PAT", "")).strip()
    if not pat:
        raise HTTPException(status_code=400, detail="PAT is required")
    try:
        add_log("Attempting to save session from PAT...")
        sess = await create_session(pat)

        # Insert or update in SQLite（ON CONFLICT 保留既有账号状态，见 accounts.upsert_account_credentials）
        with get_db() as conn:
            upsert_account_credentials(
                conn,
                uid=sess.identity.uid,
                name=sess.identity.name or "PAT Account",
                user_type=sess.identity.user_type,
                security_oauth_token=sess.identity.security_oauth_token,
                refresh_token=sess.identity.refresh_token,
                machine_id=sess.machine_id,
            )

        db_set_settings("active_uid", sess.identity.uid)
        
        add_log(f"Session saved from PAT. User: {sess.identity.name}")
        _local_auth_error = None
        return {"ready": True, "id": sess.identity.uid, "name": sess.identity.name, "user_type": sess.identity.user_type}
    except Exception as exc:
        msg = f"Failed to authenticate with provided PAT: {exc}"
        add_log(msg, "ERROR")
        raise HTTPException(status_code=502, detail=msg) from exc


def is_quota_error(exc: Exception) -> bool:
    """判断是否为 quota/限流类错误（429 / quota / rate limit）。
    这类错误需先查询真实限额确认，不能直接跳过账户。"""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429
    if isinstance(exc, RuntimeError):
        msg = str(exc).lower()
        return any(k in msg for k in ("http 429", "quota", "rate limit", "insufficient"))
    return False


def is_account_error(exc: Exception) -> bool:
    """判断是否'账号级'错误（token 无效/限额/服务端拒绝）。只有这类才应跳过账户。

    网络/流中断/超时（如 httpx.ReadError 的 incomplete chunk read）是临时性问题，
    换账户也无效，不应触发 rotate。
    """
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (401, 403, 429)
    if isinstance(exc, httpx.HTTPError):
        return False  # 连接/超时/读错误等网络问题
    if isinstance(exc, RuntimeError):
        msg = str(exc).lower()
        if any(code in msg for code in ("http 401", "http 403", "http 429")):
            return True
        for kw in ("unauthorized", "invalid token", "quota", "rate limit",
                   "insufficient", "personal token", "credit"):
            if kw in msg:
                return True
    return False


def _api_key_allowed(incoming_key: str, allowed_keys: list[Any]) -> bool:
    """常量时间校验 API Key：逐个经 _constant_time_eq（SHA-256 摘要后比较），
    无长度预检、无短路泄漏，且天然兼容非 ASCII 字符。"""
    for allowed in allowed_keys:
        if _constant_time_eq(incoming_key, str(allowed)):
            return True
    return False


@app.post("/v1/chat/completions")
async def chat_completions(payload: dict[str, Any], authorization: str | None = Header(default=None)):
    # 同步 SQLite 放线程池执行，避免聊天热路径阻塞事件循环（同 /ui/accounts/* 写法）
    config = await asyncio.to_thread(load_config)
    if config.get("auth_required", False):
        allowed_keys = config.get("allowed_keys", [])
        incoming_key = None
        if authorization and authorization.startswith("Bearer "):
            incoming_key = authorization[len("Bearer "):].strip()

        if not incoming_key or not _api_key_allowed(incoming_key, allowed_keys):
            add_log("Access denied: Invalid or missing API Key in request header.", "WARNING")
            raise HTTPException(status_code=401, detail="Invalid or missing API Key")

    model = payload.get("model", "lite")
    stream = bool(payload.get("stream", False))
    messages_count = len(payload.get("messages", []))
    add_log(f"Incoming completion request: model={model}, stream={stream}, messages={messages_count}")

    accounts_data = await asyncio.to_thread(db_load_accounts)
    enabled_count = sum(1 for acc in accounts_data["accounts"] if acc.get("enabled", True))
    max_retries = max(1, enabled_count)
    sess: SessionContext | None = None

    for attempt in range(max_retries):
        try:
            sess = await get_session()
            add_log(f"Request routing via account: {sess.identity.name} ({sess.identity.uid})")
            if stream:
                gen = stream_openai_response(payload, sess)
                try:
                    first_item = await gen.__anext__()
                except StopAsyncIteration:
                    first_item = None
                
                async def stream_success_wrapper(first, g):
                    if first is not None:
                        yield first
                    async for chunk in g:
                        yield chunk
                
                add_log(f"Streaming response initiated (Attempt {attempt+1}/{max_retries}).")
                return StreamingResponse(
                    stream_success_wrapper(first_item, gen),
                    media_type="text/event-stream",
                    headers={"Cache-Control": "no-cache"}
                )
            else:
                add_log(f"Generating full completion response (Attempt {attempt+1}/{max_retries})...")
                resp = await complete_openai_response(payload, sess)
                add_log("Completion request finished successfully.")
                return resp
        except HTTPException:
            # 请求级错误（如 get_session 的 400「未配置账号」）原样上抛，
            # 不能被下面的 except Exception 吞成 502
            raise
        except Exception as exc:
            current_uid = sess.identity.uid if sess is not None else "unknown"
            if is_account_error(exc):
                if is_quota_error(exc):
                    # quota 类错误：先发一次请求确认是否真正 exceeded，而不是直接跳过
                    # 同步查询放线程池，避免 429 路径卡死事件循环与并发 SSE
                    q = await asyncio.to_thread(get_account_quota, current_uid)
                    if q.get("ok"):
                        quota = q["quota"]
                        # remaining 可能为 null/缺失：先做类型判断再比较，避免 None <= 0 抛 TypeError 变 500
                        remaining = (quota.get("userQuota") or {}).get("remaining")
                        truly_exceeded = bool(quota.get("isQuotaExceeded")) or (
                            isinstance(remaining, (int, float)) and remaining <= 0
                        )
                        if not truly_exceeded:
                            add_log(f"Quota check on {current_uid}: NOT exceeded (remaining={quota.get('userQuota', {}).get('remaining')}), not rotating.", "WARNING")
                            raise HTTPException(status_code=502, detail=f"{exc}")
                        add_log(f"Quota confirmed exceeded for {current_uid}: {exc}. Rotating...", "WARNING")
                    else:
                        # 限额查询失败：无法确认，保守不跳过账户
                        add_log(f"Quota check failed for {current_uid} ({q.get('error')}), not rotating.", "WARNING")
                        raise HTTPException(status_code=502, detail=f"{exc}")
                else:
                    add_log(f"Account-level error on {current_uid}: {exc}. Rotating to next account...", "WARNING")
                try:
                    rotate_next_account(current_uid, str(exc))
                except Exception as e:
                    add_log(f"Failed to rotate account: {e}", "ERROR")
                    raise HTTPException(status_code=502, detail=f"Request failed and no other account is available. Error: {exc}")
            else:
                add_log(f"Transient error on account {current_uid}: {exc}. Not rotating account.", "WARNING")
                raise HTTPException(status_code=502, detail=str(exc))
                
    raise HTTPException(status_code=502, detail="Request failed on all available accounts.")


def main() -> None:
    import uvicorn

    # 非 UTF-8 控制台（如 Windows cp1252/gbk）下打印中文/特殊字符会 UnicodeEncodeError：
    # 入口处统一把 stdout/stderr 重配为 UTF-8（仅当对象支持 reconfigure 时，参考独立注册机做法）
    for _stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(_stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=os.getenv("QODER_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("QODER_PORT", "5050")))
    args = parser.parse_args()
    # 刷新线程与建库都在 lifespan 中启动（init_db 先于 start_refresh_loop），
    # main() 不再提前启动刷新线程，避免其在建库完成前查询 accounts 表
    uvicorn.run("qoder2api.app:app", host=args.host, port=args.port, reload=False)

if __name__ == "__main__":
    main()
