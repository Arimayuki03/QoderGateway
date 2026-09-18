import time
import uuid
from typing import Any

from .auth import (
    AuthIdentity,
    SessionContext,
    load_local_session,
    new_session,
    new_machine,
    fetch_user_status
)
from .database import get_db


def db_get_settings(key: str, default: str | None = None, conn=None) -> str | None:
    if conn is not None:
        res = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return res[0] if res else default
    with get_db() as conn:
        res = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return res[0] if res else default


def db_set_settings(key: str, value: str, conn=None) -> None:
    if conn is not None:
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, str(value))
        )
        return
    with get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, str(value))
        )


def db_load_accounts() -> dict[str, Any]:
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM accounts").fetchall()
        accounts = []
        for r in rows:
            account = dict(r)
            account.pop("security_oauth_token", None)
            account.pop("refresh_token", None)
            account.pop("machine_id", None)
            accounts.append(account)
        active_uid = db_get_settings("active_uid")
        return {"accounts": accounts, "active_uid": active_uid}


async def import_current_auth() -> dict[str, Any]:
    """Decrypts current local auth files, queries quota status, and saves to SQLite."""
    sess = load_local_session()
    
    # Query current user quota and metadata from Qoder backend
    quota_val = 0
    is_exceeded = 0
    plan_val = "PLAN_TIER_PRO_TRIAL"
    user_tag_val = "Pro Trial"
    next_reset = None
    
    try:
        status_data = await fetch_user_status(
            sess.identity.uid,
            sess.machine_id,
            sess.machine_token,
            sess.machine_type
        )
        quota_val = status_data.get("quota", 0)
        is_exceeded = 1 if status_data.get("isQuotaExceeded", False) else 0
        plan_val = status_data.get("plan", "PLAN_TIER_PRO_TRIAL")
        user_tag_val = status_data.get("userTag", "Pro Trial")
        next_reset = status_data.get("nextResetAt")
    except Exception as e:
        # Fallback if network call fails
        print(f"Network error querying Qoder status: {e}")

    uid = sess.identity.uid
    name = sess.identity.name or "Unnamed"

    with get_db() as conn:
        # Check if already exists to keep enabled state
        existing = conn.execute("SELECT enabled FROM accounts WHERE uid = ?", (uid,)).fetchone()
        enabled = existing[0] if existing else 1

        conn.execute(
            """
            INSERT OR REPLACE INTO accounts (
                uid, name, user_type, security_oauth_token, refresh_token, machine_id,
                enabled, last_status, last_error, quota, is_quota_exceeded, plan,
                user_tag, next_reset_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                uid, name, sess.identity.user_type, sess.identity.security_oauth_token,
                sess.identity.refresh_token, sess.machine_id, enabled, "ok", None,
                quota_val, is_exceeded, plan_val, user_tag_val, next_reset
            )
        )

    # Set as active if none set
    active_uid = db_get_settings("active_uid")
    if not active_uid:
        db_set_settings("active_uid", uid)

    return {
        "uid": uid,
        "name": name,
        "user_type": sess.identity.user_type,
        "enabled": bool(enabled),
        "last_status": "ok",
        "quota": quota_val,
        "is_quota_exceeded": bool(is_exceeded),
        "plan": plan_val,
        "user_tag": user_tag_val,
        "next_reset_at": next_reset
    }


def batch_import_accounts(records: list[dict]) -> dict:
    """批量导入账号（来自注册机导出的 JSON）。

    每条记录字段：email/password/name/user_id/token/refresh_token/expires_at/...
    返回 {"imported": n, "skipped": m}。
    """
    imported = 0
    skipped = 0
    with get_db() as conn:
        for rec in records:
            uid = str(rec.get("user_id") or "").strip()
            token = str(rec.get("token") or rec.get("security_oauth_token") or "").strip()
            if not uid and not token:
                skipped += 1
                continue
            if not uid:
                # 无 user_id 时用 token 前 24 位兜底主键
                uid = "tok_" + token[:24]
            existing = conn.execute("SELECT enabled FROM accounts WHERE uid = ?", (uid,)).fetchone()
            enabled = existing[0] if existing else 1
            conn.execute(
                """
                INSERT OR REPLACE INTO accounts (
                    uid, name, user_type, security_oauth_token, refresh_token, machine_id,
                    enabled, last_status, last_error, quota, is_quota_exceeded, plan, user_tag, next_reset_at, token_expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'ok', NULL, 0, 0, 'PLAN_TIER_PRO_TRIAL', 'Pro Trial', NULL, ?)
                """,
                (
                    uid,
                    str(rec.get("name") or rec.get("email") or "Imported"),
                    "personal_standard",
                    token,
                    str(rec.get("refresh_token") or ""),
                    str(uuid.uuid4()),
                    enabled,
                    str(rec.get("expires_at") or ""),
                ),
            )
            imported += 1
        # active_uid 必须复用同一连接写入：另开连接会在本事务未提交时锁库
        if not db_get_settings("active_uid", conn=conn):
            active = conn.execute("SELECT uid FROM accounts WHERE enabled = 1 LIMIT 1").fetchone()
            if active:
                db_set_settings("active_uid", active["uid"], conn=conn)
    return {"imported": imported, "skipped": skipped}


def save_device_credentials(cred: dict) -> dict:
    """把设备授权拿到的凭据写入账号池并激活，返回账号摘要。

    cred 字段来自 deviceToken/poll 的 200 响应：
    token / refresh_token / user_id / expires_at / refresh_token_expires_at
    """
    uid = str(cred.get("user_id") or "").strip()
    token = str(cred.get("token") or "").strip()
    if not uid or not token:
        raise ValueError("device 凭据缺少 user_id 或 token，无法入库")
    machine_id = str(uuid.uuid4())

    with get_db() as conn:
        existing = conn.execute("SELECT enabled FROM accounts WHERE uid = ?", (uid,)).fetchone()
        enabled = existing[0] if existing else 1
        conn.execute(
            """
            INSERT OR REPLACE INTO accounts (
                uid, name, user_type, security_oauth_token, refresh_token, machine_id,
                enabled, last_status, last_error, quota, is_quota_exceeded, plan, user_tag,
                next_reset_at, token_expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'ok', NULL, 0, 0, 'PLAN_TIER_PRO_TRIAL', 'Pro Trial', NULL, ?)
            """,
            (
                uid, "Device Auth", "personal_standard",
                token, str(cred.get("refresh_token") or ""), machine_id,
                enabled, str(cred.get("expires_at") or ""),
            ),
        )
        # 复用同一连接写入，避免嵌套事务锁库；新账号直接激活
        db_set_settings("active_uid", uid, conn=conn)

    return {"uid": uid, "name": "Device Auth", "expires_at": cred.get("expires_at") or ""}


def get_active_session() -> SessionContext:
    """Gets the session for the active account from database."""
    active_uid = db_get_settings("active_uid")
    
    account = None
    with get_db() as conn:
        if active_uid:
            res = conn.execute("SELECT * FROM accounts WHERE uid = ? AND enabled = 1", (active_uid,)).fetchone()
            if res:
                account = dict(res)
        
        if not account:
            # Fallback to first enabled account
            res = conn.execute("SELECT * FROM accounts WHERE enabled = 1 LIMIT 1").fetchone()
            if res:
                account = dict(res)
                db_set_settings("active_uid", account["uid"], conn=conn)

    if not account:
        raise ValueError("No active or enabled accounts found in database. Please import or configure an account.")

    identity = AuthIdentity(
        name=account["name"],
        aid=account["uid"],
        uid=account["uid"],
        yx_uid="",
        organization_id="",
        organization_name="",
        user_type=account["user_type"],
        security_oauth_token=account["security_oauth_token"],
        refresh_token=account["refresh_token"]
    )
    
    _, machine_token, machine_type = new_machine()
    return new_session(
        identity,
        account["machine_id"],
        machine_token,
        machine_type
    )


# 轮转的临时失败记录（纯内存，不写表结构）：uid → 最后一次失败时间戳；
# 5 分钟内失败过的账号轮转时优先避开，进程重启即清零
_ROTATE_FAILURE_COOLDOWN = 300.0
_recent_failures: dict[str, float] = {}


def rotate_next_account(failed_uid: str, error_msg: str) -> SessionContext:
    """Marks failed account in database, rotates to the next enabled, and returns it."""
    now = time.time()
    _recent_failures[failed_uid] = now
    with get_db() as conn:
        conn.execute(
            "UPDATE accounts SET last_status = 'failed', last_error = ? WHERE uid = ?",
            (error_msg, failed_uid)
        )

        # Get all enabled accounts
        rows = conn.execute("SELECT * FROM accounts WHERE enabled = 1").fetchall()

    enabled_accounts = [dict(r) for r in rows]
    if not enabled_accounts:
        raise ValueError("All enabled accounts have failed or no enabled accounts exist.")

    # 优先排除：刚失败的账号本身 + 5 分钟内失败过的账号（失败账号不再留在轮转池）；
    # 排除后无可用账号（如单账号）则回退为全量启用账号，保证仍有请求路径
    candidates = [
        acc for acc in enabled_accounts
        if acc["uid"] != failed_uid
        and now - _recent_failures.get(acc["uid"], 0.0) >= _ROTATE_FAILURE_COOLDOWN
    ]
    if not candidates:
        candidates = enabled_accounts

    # Find next cyclic account
    next_acc = None
    try:
        failed_idx = next(i for i, acc in enumerate(candidates) if acc["uid"] == failed_uid)
        next_acc = candidates[(failed_idx + 1) % len(candidates)]
    except StopIteration:
        next_acc = candidates[0]

    db_set_settings("active_uid", next_acc["uid"])
    
    identity = AuthIdentity(
        name=next_acc["name"],
        aid=next_acc["uid"],
        uid=next_acc["uid"],
        yx_uid="",
        organization_id="",
        organization_name="",
        user_type=next_acc["user_type"],
        security_oauth_token=next_acc["security_oauth_token"],
        refresh_token=next_acc["refresh_token"]
    )
    _, machine_token, machine_type = new_machine()
    return new_session(
        identity,
        next_acc["machine_id"],
        machine_token,
        machine_type
    )
