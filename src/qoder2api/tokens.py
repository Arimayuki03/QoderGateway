"""
Token 刷新与限额查询（openapi.qoder.sh）

- 刷新：POST /api/v1/deviceToken/refresh（drt-）或 /api/v1/jobToken/refresh（jrt-）
- 限额：GET /api/v2/quota/usage
- 后台定时刷新线程：每 6 小时刷新一次全部 enabled 账号的 token
"""
from __future__ import annotations

import threading
import time
from typing import Any

import httpx

from .database import get_db

OPENAPI = "https://openapi.qoder.sh"
UA = "qoder/1.1.16"
REFRESH_INTERVAL = 6 * 3600  # 6 小时


def _headers() -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": UA,
    }


def refresh_one_account(uid: str) -> dict[str, Any]:
    """用 refresh_token 刷新单个账号的 dt-/drt-，并回写数据库。"""
    with get_db() as conn:
        row = conn.execute(
            "SELECT uid, name, refresh_token FROM accounts WHERE uid = ?", (uid,)
        ).fetchone()
    if not row:
        return {"ok": False, "uid": uid, "error": "账号不存在"}
    rt = (row["refresh_token"] or "").strip()
    if not rt:
        return {"ok": False, "uid": uid, "error": "无 refresh_token"}

    # drt- → deviceToken/refresh；jrt- → jobToken/refresh
    if rt.startswith("jrt-"):
        url = f"{OPENAPI}/api/v1/jobToken/refresh"
        token_key = "token"
    else:
        url = f"{OPENAPI}/api/v1/deviceToken/refresh"
        token_key = "device_token"

    try:
        r = httpx.post(url, json={"refresh_token": rt}, headers=_headers(), timeout=25)
    except httpx.HTTPError as e:
        return {"ok": False, "uid": uid, "error": f"网络错误: {e}"}

    if r.status_code != 200:
        return {"ok": False, "uid": uid, "error": f"HTTP {r.status_code}: {r.text[:160]}"}

    try:
        d = r.json()
    except ValueError:
        return {"ok": False, "uid": uid, "error": f"响应非 JSON: {r.text[:160]}"}
    new_tok = str(d.get(token_key) or d.get("token") or "").strip()
    new_rt = str(d.get("refresh_token") or "").strip()
    if not new_tok:
        return {"ok": False, "uid": uid, "error": "响应缺少 token"}
    expires_at = d.get("expires_at") or ""

    # 响应未返回新 refresh_token 时保留原值，避免空串覆盖导致无法再刷新。
    # UPDATE 必须在 with 块内执行：sqlite3 的 with 负责提交事务，块外写入不落库
    with get_db() as conn:
        if new_rt:
            conn.execute(
                "UPDATE accounts SET security_oauth_token = ?, refresh_token = ?, "
                "token_expires_at = ?, last_status = 'ok', last_error = NULL WHERE uid = ?",
                (new_tok, new_rt, expires_at, uid),
            )
        else:
            conn.execute(
                "UPDATE accounts SET security_oauth_token = ?, "
                "token_expires_at = ?, last_status = 'ok', last_error = NULL WHERE uid = ?",
                (new_tok, expires_at, uid),
            )
    return {"ok": True, "uid": uid, "name": row["name"], "expires_at": expires_at}


def refresh_all_account_tokens() -> dict[str, Any]:
    """刷新所有 enabled 且有 refresh_token 的账号。"""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT uid FROM accounts WHERE enabled = 1 AND refresh_token IS NOT NULL AND refresh_token != ''"
        ).fetchall()
    results = [refresh_one_account(r["uid"]) for r in rows]
    ok = sum(1 for x in results if x.get("ok"))
    return {
        "ok": ok,
        "failed": len(results) - ok,
        "total": len(results),
        "results": results,
    }


def get_account_quota(uid: str) -> dict[str, Any]:
    """查询单个账号限额（GET /api/v2/quota/usage）。"""
    with get_db() as conn:
        row = conn.execute(
            "SELECT uid, name, security_oauth_token FROM accounts WHERE uid = ?", (uid,)
        ).fetchone()
    if not row:
        return {"ok": False, "uid": uid, "error": "账号不存在"}
    tok = row["security_oauth_token"] or ""
    if not tok:
        return {"ok": False, "uid": uid, "error": "无 token"}
    try:
        r = httpx.get(
            f"{OPENAPI}/api/v2/quota/usage",
            headers={"Authorization": f"Bearer {tok}", "Accept": "application/json"},
            timeout=20,
        )
    except httpx.HTTPError as e:
        return {"ok": False, "uid": uid, "error": f"网络错误: {e}"}
    if r.status_code != 200:
        return {"ok": False, "uid": uid, "error": f"HTTP {r.status_code}: {r.text[:160]}"}
    return {"ok": True, "uid": uid, "name": row["name"], "quota": r.json()}


def get_all_accounts_quota() -> dict[str, Any]:
    """查询所有 enabled 账号的限额。"""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT uid, name FROM accounts WHERE enabled = 1 AND security_oauth_token IS NOT NULL AND security_oauth_token != ''"
        ).fetchall()
    quotas = [get_account_quota(r["uid"]) for r in rows]
    return {"total": len(quotas), "quotas": quotas}


# ---------------------------------------------------------------------------
# 后台定时刷新
# ---------------------------------------------------------------------------
_refresh_thread: threading.Thread | None = None
_refresh_lock = threading.Lock()
_refresh_started = False  # 模块级幂等标记：lifespan 与 main() 只允许启动一次


def _refresh_loop() -> None:
    # 先立即刷新一次再进入周期睡眠：避免服务启动后最长 6 小时内 token 无人刷新
    while True:
        try:
            result = refresh_all_account_tokens()
            print(f"[refresh] ok={result['ok']} failed={result['failed']} total={result['total']}", flush=True)
        except Exception as e:
            print(f"[refresh] loop error: {e}", flush=True)
        time.sleep(REFRESH_INTERVAL)


def start_refresh_loop() -> None:
    """启动后台定时刷新线程（幂等：FastAPI lifespan 与 main() 双入口只启动一次）。"""
    global _refresh_thread, _refresh_started
    with _refresh_lock:
        if _refresh_started:
            return
        _refresh_started = True
        _refresh_thread = threading.Thread(target=_refresh_loop, daemon=True)
        _refresh_thread.start()
