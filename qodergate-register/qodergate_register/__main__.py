#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
qodergate-register —— Qoder 独立注册机

无限循环注册：每母线程每批 3 个子任务并发，浏览器隐藏后台，
人机验证时置顶等你滑滑块，划完自动轮到下一个；成功注册即导出 accounts.json。

用法：
  python -m qodergate_register --parents 2            # 2 个母线程
  python -m qodergate_register --parents 1 --output ./out.json
  python -m qodergate_register --parents 1 --proxy http://127.0.0.1:7890
  python -m qodergate_register --parents 1 --export-plaintext   # 导出明文密码（默认打码）
  python -m qodergate_register --check               # 检查 YYDS_API_KEY 配置
  Ctrl+C 停止（当前批次完成后停止并打印统计）

环境变量：YYDS_API_KEY（必填，AC- 开头，也可放项目根 .env）
"""
from __future__ import annotations

import argparse
import json
import sys
import time

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from .core import (
    _yyds_key,
    get_registrar_status,
    set_export_plaintext,
    set_output_file,
    set_proxy,
    start_registration,
    stop_registration,
)


def _check() -> int:
    key = _yyds_key()
    if key:
        print(f"[check] YYDS_API_KEY 已配置: {key[:3]}...{key[-4:]}")
        return 0
    print("[check] YYDS_API_KEY 未配置：请设置环境变量或在项目根 .env 添加 YYDS_API_KEY=AC-...")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Qoder 独立注册机（无限循环）")
    parser.add_argument("--parents", type=int, default=2, help="母线程数（1-6，每母线程 3 子任务并发）")
    parser.add_argument("--output", default=None, help="JSON 导出文件路径（默认项目根 accounts.json）")
    parser.add_argument("--proxy", default=None, help="出站代理（如 http://127.0.0.1:7890），穿透浏览器与 Device 授权 HTTP 请求")
    parser.add_argument("--export-plaintext", action="store_true",
                        help="导出 accounts.json 时保留明文密码（默认打码为 <redacted:N chars>）")
    parser.add_argument("--check", action="store_true", help="检查配置后退出")
    args = parser.parse_args(argv)

    if args.check:
        return _check()

    if not _yyds_key():
        print("[error] YYDS_API_KEY 未配置：请设置环境变量或在项目根 .env 添加 YYDS_API_KEY=AC-...")
        return 1

    set_output_file(args.output)  # --output 接线到导出逻辑
    set_proxy(args.proxy)  # --proxy 接线到出站请求（浏览器 + Device 授权 HTTP）
    set_export_plaintext(args.export_plaintext)  # --export-plaintext 接线到导出脱敏开关
    r = start_registration(parents=args.parents)
    if not r.get("ok"):
        print(f"[error] {r.get('error')}")
        return 1

    if args.proxy:
        print("[main] 已启用出站代理（浏览器与 Device 授权请求将走代理）")
    if args.export_plaintext:
        print("[main] 已开启明文导出：accounts.json 将包含明文密码，请妥善保管")

    print(f"[main] 已启动 {args.parents} 个母线程，无限循环注册中。浏览器隐藏后台，滑块置顶时请操作。Ctrl+C 停止。")
    try:
        while True:
            time.sleep(3)
            st = get_registrar_status()
            stats = st["stats"]
            active = [f"{k}:{v['stage']}" for k, v in st["active"].items()]
            print(
                f"[main] 统计 成功{stats['success']} 失败{stats['failed']} 总计{stats['total']}"
                f" | 运行中 {len(active)} | 验证 {st.get('verification') or '-'}"
            )
    except KeyboardInterrupt:
        print("\n[main] 收到停止请求，当前批次完成后停止...")
        stop_registration()
        while True:
            time.sleep(2)
            st = get_registrar_status()
            if not st["running"]:
                break
        stats = st["stats"]
        print(f"[main] 已停止。本次共注册 {stats['success']} 个账户（失败 {stats['failed']}）")
        print(f"[main] 导出文件: {args.output or 'accounts.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
