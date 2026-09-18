import copy
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx

from .auth import SessionContext
from .env import httpx_client_kwargs


logger = logging.getLogger("qoder2api.bridge")

# 新版协议（Qoder CLI 现行）：OpenAI 兼容端点，纯 Bearer，无 COSY 签名，响应为标准 OpenAI SSE。
# 性能远优于老版（老版默认带长 reasoning，复杂任务可到分钟级）。
QODER_CHAT_URL_NEW = "https://api2-v2.qoder.sh/model/v1/chat/completions"


def normalize_tool_arguments(arguments: Any) -> str:
    if arguments is None:
        return ""
    if isinstance(arguments, str):
        return arguments
    return json.dumps(arguments, ensure_ascii=False, separators=(",", ":"))


def normalize_tool_calls(raw_tool_calls: Any) -> list[dict[str, Any]] | None:
    if not isinstance(raw_tool_calls, list):
        return None
    normalized = []
    for raw in raw_tool_calls:
        function = raw.get("function", {}) if isinstance(raw, dict) else {}
        name = function.get("name", "")
        arguments = normalize_tool_arguments(function.get("arguments"))
        if not name and not arguments:
            continue
        normalized.append({"id": raw.get("id", ""), "type": raw.get("type", "function"), "function": {"name": name, "arguments": arguments}})
    return normalized or None


def parse_tool_calls_text(text: str | None) -> list[dict[str, Any]] | None:
    if not text:
        return None
    trimmed = text.strip()
    if not trimmed.startswith("Tool calls:"):
        return None
    payload = trimmed[len("Tool calls:") :].strip()
    if payload.startswith("```") and payload.endswith("```"):
        newline = payload.find("\n")
        if newline >= 0:
            payload = payload[newline + 1 : -3].strip()
    if not payload.startswith("["):
        return None
    try:
        return normalize_tool_calls(json.loads(payload))
    except json.JSONDecodeError:
        return None


def build_qoder_body(req: dict[str, Any], sess: SessionContext) -> tuple[dict[str, Any], str, bool]:
    """新版协议 body：OpenAI 原生格式，直接透传 messages/tools。"""
    model = req.get("model") or "lite"
    messages = req.get("messages") if isinstance(req.get("messages"), list) else []
    tools_enabled = bool(req.get("tools"))
    rid = str(uuid.uuid4())
    # 上游 schema 未验证：OpenAI 采样参数不转发，仅记录 debug 提示（文档另行更新）
    dropped = [k for k in ("temperature", "max_tokens", "top_p", "stop") if k in req]
    if dropped:
        logger.debug("采样参数未转发上游: %s", ", ".join(dropped))
    body: dict[str, Any] = {
        "model": model,
        "messages": copy.deepcopy(messages or []),
        "stream": True,
        "stream_options": {"include_usage": True},
        "metadata": {
            "context": {
                "request_id": rid,
                "request_set_id": rid,
                "session_id": str(uuid.uuid4()),
                "task_id": "common",
                "client_type": "qodercli",
            }
        },
    }
    if tools_enabled:
        body["tools"] = copy.deepcopy(req["tools"])
    return body, model, tools_enabled


@dataclass
class BridgeDelta:
    role: str = ""
    content: str = ""
    tool_calls: list[dict[str, Any]] | None = None
    # chunk 顶层的 usage（include_usage 时通常出现在最后一个 choices 为空的 chunk 上）
    usage: dict[str, Any] | None = None

    @property
    def is_empty(self) -> bool:
        return not self.role and not self.content and not self.tool_calls and not self.usage


def extract_delta(data_line: str) -> BridgeDelta:
    try:
        obj = json.loads(data_line)
        if not isinstance(obj, dict):
            return BridgeDelta()
        # 新版：标准 OpenAI chunk（choices 直接在顶层）
        if "choices" in obj:
            # 任意 chunk 顶层都可能带 usage（最后一个 chunk choices 为空、只含 usage）
            usage = obj["usage"] if isinstance(obj.get("usage"), dict) else None
            for choice in obj.get("choices", []):
                delta = choice.get("delta", {}) if isinstance(choice, dict) else {}
                role = delta.get("role") or ""
                content = delta.get("content") or ""
                tool_calls = delta.get("tool_calls") if isinstance(delta.get("tool_calls"), list) else None
                if role or content or tool_calls:
                    return BridgeDelta(role, content, tool_calls, usage)
            return BridgeDelta("", "", None, usage)
        # 老版：wrapper 内嵌 body 字符串
        inner = obj.get("body") or ""
        if not inner:
            return BridgeDelta()
        inner_json = json.loads(inner)
        usage = inner_json["usage"] if isinstance(inner_json.get("usage"), dict) else None
        for choice in inner_json.get("choices", []):
            delta = choice.get("delta", {})
            role = delta.get("role") or ""
            content = delta.get("content") or ""
            tool_calls = delta.get("tool_calls") if isinstance(delta.get("tool_calls"), list) else None
            if role or content or tool_calls:
                return BridgeDelta(role, content, tool_calls, usage)
        return BridgeDelta("", "", None, usage)
    except (TypeError, json.JSONDecodeError):
        return BridgeDelta()


def make_chunk(chunk_id: str, created: int, model: str, delta: dict[str, Any] | None = None, finish_reason: str | None = None) -> dict[str, Any]:
    return {"id": chunk_id, "object": "chat.completion.chunk", "created": created, "model": model, "choices": [{"index": 0, "delta": delta or {}, "finish_reason": finish_reason}]}


class ToolCallAccumulator:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def _resolve_index(self, delta: dict[str, Any]) -> int:
        """解析碎片应落入的槽位：显式 index 优先；无 index 时按 id 匹配已有 call，
        新 id 追加到末尾新槽；无 id 也无 index 视为最后一个 call 的参数碎片。"""
        index = delta.get("index")
        if isinstance(index, int) and index >= 0:
            return index
        delta_id = delta.get("id")
        if isinstance(delta_id, str) and delta_id:
            for i, call in enumerate(self.calls):
                if call["id"] and call["id"] == delta_id:
                    return i
            return len(self.calls)  # 新 call：追加到末尾
        # 无 index 无 id：延续最后一个已知 call（尚无 call 时从 0 开始）
        return len(self.calls) - 1 if self.calls else 0

    def append(self, delta_calls: list[dict[str, Any]]) -> list[int]:
        """合并一批 tool_call delta，返回每个 delta 实际落入的槽位 index（供流式下发）。"""
        indices = []
        for delta in delta_calls:
            index = self._resolve_index(delta)
            while len(self.calls) <= index:
                self.calls.append({"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
            existing = self.calls[index]
            if isinstance(delta.get("id"), str):
                existing["id"] = delta["id"]
            if isinstance(delta.get("type"), str):
                existing["type"] = delta["type"]
            function = delta.get("function") or {}
            if isinstance(function.get("name"), str):
                existing["function"]["name"] = function["name"]
            if isinstance(function.get("arguments"), str):
                existing["function"]["arguments"] += function["arguments"]
            indices.append(index)
        return indices

    def snapshot(self) -> list[dict[str, Any]]:
        return copy.deepcopy(self.calls)


async def qoder_stream_lines(sess: SessionContext, body: dict[str, Any], model: str) -> AsyncIterator[str]:
    """新版协议：POST api2-v2.qoder.sh/model/v1/chat/completions，Bearer 直连。"""
    ctx = (body.get("metadata") or {}).get("context") or {}
    headers = {
        "Authorization": f"Bearer {sess.identity.security_oauth_token}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "User-Agent": "qoder/1.1.16",
        "X-Request-ID": ctx.get("request_id", ""),
        "X-Session-ID": ctx.get("session_id", ""),
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(300, connect=15), **httpx_client_kwargs()) as client:
        async with client.stream("POST", QODER_CHAT_URL_NEW, json=body, headers=headers) as response:
            if response.status_code != 200:
                text = await response.aread()
                raise RuntimeError(f"HTTP {response.status_code} {text.decode(errors='replace')}")
            # 上游 200 但不是 SSE（如 JSON 错误体）：读 body 前 200 字符抛错，
            # 交给 is_account_error 分类与账号轮转逻辑接管，避免静默返回空补全
            content_type = response.headers.get("content-type", "")
            if "text/event-stream" not in content_type.lower():
                text = await response.aread()
                preview = text[:200].decode(errors="replace")
                raise RuntimeError(f"上游响应非 SSE 流 (Content-Type: {content_type}): {preview}")
            async for line in response.aiter_lines():
                if line:
                    yield line


async def stream_openai_response(req: dict[str, Any], sess: SessionContext) -> AsyncIterator[str]:
    body, model, tools_enabled = build_qoder_body(req, sess)
    chunk_id = "chatcmpl-" + uuid.uuid4().hex[:24]
    created = int(time.time())
    tool_calls = ToolCallAccumulator()
    emitted = False
    pending = ""
    streaming_text = False
    pending_role = "assistant"
    captured_usage: dict[str, Any] | None = None  # 顶层 usage 捕获（include_usage 尾包）
    got_data = False  # 上游是否给过任何 data 行（空流检测）

    def event(payload: dict[str, Any]) -> str:
        return f"data: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n\n"

    async for line in qoder_stream_lines(sess, body, model):
        if not line.startswith("data:"):
            continue
        got_data = True
        delta = extract_delta(line[5:].strip())
        if delta.is_empty:
            continue
        if delta.usage:
            captured_usage = delta.usage
        if delta.role:
            pending_role = delta.role
        if delta.tool_calls:
            pending = "" if tools_enabled and pending.lstrip().startswith("Tool calls:") else pending
            # 先入累计器解析真实槽位（无 index 时按 id/最后一个 call 归属，避免参数碎片串话），
            # 再按解析出的 index 下发，保证客户端聚合正确
            resolved = tool_calls.append(delta.tool_calls)
            indexed = []
            for call, index in zip(delta.tool_calls, resolved):
                item = copy.deepcopy(call)
                item["index"] = index
                indexed.append(item)
            out_delta = {"tool_calls": indexed}
            if not emitted:
                out_delta["role"] = pending_role
            emitted = True
            yield event(make_chunk(chunk_id, created, model, out_delta))
            continue
        if not delta.content:
            continue
        if not tools_enabled or streaming_text:
            out_delta = {"content": delta.content}
            if not emitted:
                out_delta["role"] = pending_role
            emitted = True
            streaming_text = True
            yield event(make_chunk(chunk_id, created, model, out_delta))
            continue
        pending += delta.content
        candidate = pending.lstrip()
        if "Tool calls:".startswith(candidate) or candidate.startswith("Tool calls:"):
            continue
        streaming_text = True
        out_delta = {"content": pending}
        if not emitted:
            out_delta["role"] = pending_role
        emitted = True
        pending = ""
        yield event(make_chunk(chunk_id, created, model, out_delta))

    # 上游 200 且流"正常"结束，但全程零 data 行 / 未产出任何内容：
    # 视为空流异常抛错，交给 is_account_error 分类与账号轮转逻辑接管，
    # 而不是返回一个"成功的空补全"
    if not got_data:
        raise RuntimeError("上游响应 200 但未返回任何 SSE data 行")
    parsed_calls = parse_tool_calls_text(pending) if tools_enabled else None
    if parsed_calls:
        indexed = []
        for index, call in enumerate(parsed_calls):
            item = copy.deepcopy(call)
            item.setdefault("index", index)
            indexed.append(item)
        tool_calls.append(indexed)
        yield event(make_chunk(chunk_id, created, model, {"tool_calls": indexed, "role": pending_role} if not emitted else {"tool_calls": indexed}))
    elif pending:
        yield event(make_chunk(chunk_id, created, model, {"content": pending, "role": pending_role} if not emitted else {"content": pending}))
    elif not emitted and not tool_calls.calls:
        raise RuntimeError("上游 SSE 流已结束但未产出任何内容（空流）")

    finish_reason = "tool_calls" if tool_calls.calls else "stop"
    yield event(make_chunk(chunk_id, created, model, {}, finish_reason))
    if captured_usage:
        # OpenAI 惯例：[DONE] 前追加一个 choices 为空、携带 usage 的 chunk（仅捕获到真实 usage 时）
        yield event({
            "id": chunk_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [],
            "usage": captured_usage,
        })
    yield "data: [DONE]\n\n"


async def complete_openai_response(req: dict[str, Any], sess: SessionContext) -> dict[str, Any]:
    body, model, tools_enabled = build_qoder_body(req, sess)
    completion_id = "chatcmpl-" + uuid.uuid4().hex[:24]
    created = int(time.time())
    full = []
    tool_calls = ToolCallAccumulator()
    captured_usage: dict[str, Any] | None = None  # 顶层 usage 捕获
    got_data = False  # 上游是否给过任何 data 行（空流检测）
    async for line in qoder_stream_lines(sess, body, model):
        if not line.startswith("data:"):
            continue
        got_data = True
        delta = extract_delta(line[5:].strip())
        if delta.usage:
            captured_usage = delta.usage
        if delta.content:
            full.append(delta.content)
        if delta.tool_calls:
            tool_calls.append(delta.tool_calls)
    if not got_data:
        raise RuntimeError("上游响应 200 但未返回任何 SSE data 行")
    content = "".join(full)
    fallback_tool_calls = None if tool_calls.calls or not tools_enabled else parse_tool_calls_text(content)
    # 空流：上游正常结束但既无内容也无工具调用，抛错交给账号错误分类/轮转处理
    if not content and not tool_calls.calls and not fallback_tool_calls:
        raise RuntimeError("上游 SSE 流已结束但未产出任何内容（空流）")
    message: dict[str, Any] = {"role": "assistant"}
    if fallback_tool_calls:
        message["content"] = None
        message["tool_calls"] = fallback_tool_calls
    elif not content and tool_calls.calls:
        message["content"] = None
    else:
        message["content"] = content
    if tool_calls.calls:
        message["tool_calls"] = tool_calls.snapshot()
    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls" if tool_calls.calls or fallback_tool_calls else "stop"}],
        # 回填捕获到的真实 usage，捕获不到保持 0
        "usage": captured_usage or {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }
