import hashlib
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


def upsert_account_credentials(
    conn,
    uid: str,
    name: str,
    user_type: str,
    security_oauth_token: str,
    refresh_token: str,
    machine_id: str,
    token_expires_at: Any = None,
) -> None:
    """写入账号凭据：新行用默认状态；已存在（uid 冲突）时只更新凭据类列。

    冲突时保留既有 enabled / last_status / last_error / quota /
    is_quota_exceeded / plan / user_tag / next_reset_at——旧的
    INSERT OR REPLACE 会把这些状态强制重置（enabled 回 1、配额/套餐清成
    默认假数据、last_status 重写为 'ok'），再导入同 uid 会抹掉用户状态。
    新插入行的默认值与本表建表默认一致（enabled=1、quota=0、
    plan='PLAN_TIER_PRO_TRIAL'、user_tag='Pro Trial'）。
    """
    conn.execute(
        """
        INSERT INTO accounts (
            uid, name, user_type, security_oauth_token, refresh_token, machine_id,
            enabled, last_status, last_error, quota, is_quota_exceeded, plan, user_tag,
            next_reset_at, token_expires_at
        ) VALUES (?, ?, ?, ?, ?, ?, 1, 'ok', NULL, 0, 0, 'PLAN_TIER_PRO_TRIAL', 'Pro Trial', NULL, ?)
        ON CONFLICT(uid) DO UPDATE SET
            name = excluded.name,
            user_type = excluded.user_type,
            security_oauth_token = excluded.security_oauth_token,
            refresh_token = excluded.refresh_token,
            machine_id = excluded.machine_id,
            token_expires_at = excluded.token_expires_at
        """,
        (uid, name, user_type, security_oauth_token, refresh_token, machine_id, token_expires_at),
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
                # 无 user_id 时用 token 的 SHA-256 前 24 位十六进制兜底主键
                # （确定性：同 token 得到同 uid，重复导入命中同一行）。
                # 注意：旧格式 "tok_" + token[:24] 的历史行不做迁移（本地小库可接受），
                # 旧格式行与新哈希 uid 视为不同账号。
                uid = "tok_" + hashlib.sha256(token.encode("utf-8")).hexdigest()[:24]
            upsert_account_credentials(
                conn,
                uid=uid,
                name=str(rec.get("name") or rec.get("email") or "Imported"),
                user_type="personal_standard",
                security_oauth_token=token,
                refresh_token=str(rec.get("refresh_token") or ""),
                machine_id=str(uuid.uuid4()),
                token_expires_at=str(rec.get("expires_at") or ""),
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
        upsert_account_credentials(
            conn,
            uid=uid,
            name="Device Auth",
            user_type="personal_standard",
            security_oauth_token=token,
            refresh_token=str(cred.get("refresh_token") or ""),
            machine_id=machine_id,
            token_expires_at=str(cred.get("expires_at") or ""),
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
    """标记失败账号后，真轮转到启用账号排序中的"下一个"（环绕）并返回其会话。

    - 真轮转：按 uid 排序，从 failed_uid 的下一个位置开始环绕，取第一个
      未处于冷却期的其他启用账号；failed_uid 自身与 5 分钟内失败过的账号
      都不作为前进目标（失败账号不再留在轮转池）。
    - 若排除后没有其他候选（如仅单账号、或其余账号全在冷却期），则返回
      failed_uid 账号本身（其已不在启用列表时取第一个启用账号），且不给予
      冷却豁免——失败记录保留在 _recent_failures 中让它正常冷却，
      避免后续轮转继续选中该失败账号无限重试。
    """
    now = time.time()
    _recent_failures[failed_uid] = now
    with get_db() as conn:
        conn.execute(
            "UPDATE accounts SET last_status = 'failed', last_error = ? WHERE uid = ?",
            (error_msg, failed_uid)
        )

        # Get all enabled accounts（按 uid 排序，保证轮转顺序确定可复现）
        rows = conn.execute("SELECT * FROM accounts WHERE enabled = 1 ORDER BY uid").fetchall()

    enabled_accounts = [dict(r) for r in rows]
    if not enabled_accounts:
        raise ValueError("All enabled accounts have failed or no enabled accounts exist.")

    uids = [acc["uid"] for acc in enabled_accounts]
    try:
        failed_pos = uids.index(failed_uid)
    except ValueError:
        # 失败账号已不在启用列表（被删除/禁用）：从队头开始找下一个
        failed_pos = -1

    next_acc = None
    for offset in range(1, len(enabled_accounts) + 1):
        cand = enabled_accounts[(failed_pos + offset) % len(enabled_accounts)]
        if cand["uid"] != failed_uid and now - _recent_failures.get(cand["uid"], 0.0) >= _ROTATE_FAILURE_COOLDOWN:
            next_acc = cand
            break
    if next_acc is None:
        # 无其他候选：返回失败账号本身，不豁免冷却（失败记录已写入 _recent_failures）
        next_acc = enabled_accounts[failed_pos] if failed_pos >= 0 else enabled_accounts[0]

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
