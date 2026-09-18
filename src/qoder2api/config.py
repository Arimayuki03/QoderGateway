from typing import Any

from .database import get_db


def load_config() -> dict[str, Any]:
    with get_db() as conn:
        res = conn.execute("SELECT value FROM settings WHERE key = 'auth_required'").fetchone()
        auth_required = (res[0] == "1") if res else True

        rows = conn.execute("SELECT api_key FROM allowed_keys").fetchall()
        allowed_keys = [r[0] for r in rows]

        res_tok = conn.execute("SELECT value FROM settings WHERE key = 'gateway_token'").fetchone()
        # 缺行时返回空串并让调用方 fail closed（init_db 建库时必然写入，正常不会命中）
        gateway_token = res_tok[0] if res_tok else ""

    return {
        "auth_required": auth_required,
        "allowed_keys": allowed_keys,
        "gateway_token": gateway_token
    }


def save_config(config: dict[str, Any]) -> None:
    with get_db() as conn:
        # 仅当 payload 显式包含 auth_required 时才写该行，缺失时保留现值，
        # 避免部分更新（如只改 API Key）把 API 鉴权静默关闭
        if "auth_required" in config:
            auth_required_str = "1" if config.get("auth_required") else "0"
            conn.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES ('auth_required', ?)",
                (auth_required_str,)
            )
        
        if "gateway_token" in config:
            conn.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES ('gateway_token', ?)",
                (str(config["gateway_token"]),)
            )
            
        if "allowed_keys" in config and isinstance(config["allowed_keys"], list):
            conn.execute("DELETE FROM allowed_keys")
            for key in config["allowed_keys"]:
                conn.execute("INSERT OR REPLACE INTO allowed_keys (api_key) VALUES (?)", (str(key),))
