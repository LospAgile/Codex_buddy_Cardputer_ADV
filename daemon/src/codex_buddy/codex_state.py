from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .protocol import Entry, Heartbeat, PetInfo, clean_text


@dataclass(frozen=True)
class CodexSnapshot:
    state: str = "idle"
    animation: str = ""
    summary: str = ""
    entries: list[Entry] = field(default_factory=list)
    total_tokens: int | None = None
    today_tokens: int | None = None
    source: Path | None = None

    def to_heartbeat(self, pet: PetInfo | None = None) -> Heartbeat:
        return Heartbeat(
            state=self.state,
            animation=self.animation,
            summary=self.summary,
            entries=self.entries,
            total_tokens=self.total_tokens,
            today_tokens=self.today_tokens,
            pet=pet or PetInfo(),
        )


def snapshot_from_events(
    events: Iterable[dict[str, Any]], source: Path | None = None
) -> CodexSnapshot:
    state = "idle"
    summary = ""
    entries: list[Entry] = []
    total_tokens: int | None = None

    for event in events:
        event_type = str(event.get("type", ""))

        if event_type == "event_msg":
            payload = _payload(event)
            name = _event_name(payload)
            if name in {"task_started", "turn_started", "agent_started"}:
                state = "running"
                summary = "Codex 正在处理任务"
            elif name in {"user_message", "user_prompt_submit"}:
                state = "running"
                message = _event_message_text(payload)
                if message:
                    summary = message
                    entries = _append_entry(entries, Entry("user", message))
                else:
                    summary = "收到新的用户请求"
            elif name == "agent_message":
                state = "review"
                message = _event_message_text(payload)
                if message:
                    summary = message
                    entries = _append_entry(entries, Entry("assistant", message))
                else:
                    summary = "Codex 有新回复"
            elif name == "token_count":
                total_tokens = _extract_token_count(payload, total_tokens)
            elif "error" in name or "failed" in name:
                state = "failed"
                summary = "Codex 任务失败"
            continue

        if event_type == "response_item":
            item = _response_item(event)
            item_type = str(item.get("type", ""))
            if item_type == "function_call":
                state = "running"
                tool_name = item.get("name") or item.get("tool_name") or "tool"
                entries = _append_entry(entries, Entry("tool", clean_text(tool_name, 80)))
                summary = f"正在调用工具：{clean_text(tool_name, 48)}"
            elif item_type == "function_call_output":
                state = "running"
                summary = "工具调用已返回，Codex 正在整理结果"
            elif item_type == "message":
                role = str(item.get("role", ""))
                message = _extract_message_text(item)
                if role == "user":
                    state = "running"
                    if _is_displayable_message(message):
                        summary = message
                        entries = _append_entry(entries, Entry("user", message))
                if role == "assistant":
                    state = "review"
                    if message:
                        summary = message
                        entries = _append_entry(entries, Entry("assistant", message))
                    else:
                        summary = "Codex 有新回复"
            elif item_type in {"reasoning", "reasoning_summary"}:
                if state == "idle":
                    state = "running"
                summary = summary or "Codex 正在推理"
            elif "permission" in item_type or "approval" in item_type:
                state = "waiting"
                summary = "Codex 正在等待审批"
            elif "error" in item_type or "failed" in item_type:
                state = "failed"
                summary = "Codex 任务失败"
            continue

        if "permission" in event_type or "approval" in event_type:
            state = "waiting"
            summary = "Codex 正在等待审批"
        elif "error" in event_type or "failed" in event_type:
            state = "failed"
            summary = "Codex 任务失败"

    return CodexSnapshot(
        state=state,
        animation=_animation_for_state(state),
        summary=clean_text(summary or "Codex 空闲", 96),
        entries=entries[-4:],
        total_tokens=total_tokens,
        today_tokens=None,
        source=source,
    )


def _animation_for_state(state: str) -> str:
    if state == "waiting":
        return "waving"
    if state == "running":
        return "running"
    if state == "review":
        return "review"
    if state == "failed":
        return "failed"
    return "idle"


def _payload(event: dict[str, Any]) -> dict[str, Any]:
    payload = event.get("payload")
    if isinstance(payload, dict):
        return payload
    return event


def _event_name(payload: dict[str, Any]) -> str:
    for key in ("event", "name", "msg", "message_type", "kind", "type"):
        value = payload.get(key)
        if isinstance(value, str):
            return value
    return ""


def _response_item(event: dict[str, Any]) -> dict[str, Any]:
    item = event.get("item")
    if isinstance(item, dict):
        return item
    payload = event.get("payload")
    if isinstance(payload, dict):
        nested = payload.get("item")
        if isinstance(nested, dict):
            return nested
        return payload
    return event


def _extract_message_text(item: dict[str, Any]) -> str:
    content = item.get("content")
    if isinstance(content, str):
        return _display_text(content)
    if not isinstance(content, list):
        return ""

    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict):
            value = block.get("text") or block.get("content")
            if isinstance(value, str):
                parts.append(value)
    return _display_text(" ".join(parts))


def _event_message_text(payload: dict[str, Any]) -> str:
    for key in ("message", "text", "prompt", "input"):
        value = payload.get(key)
        if isinstance(value, str):
            text = _display_text(value)
            return text if _is_displayable_message(text) else ""
    return ""


def _display_text(value: Any, max_chars: int = 96) -> str:
    return clean_text(" ".join(str(value).split()), max_chars)


def _is_displayable_message(text: str) -> bool:
    if not text:
        return False
    stripped = text.lstrip()
    hidden_prefixes = (
        "# AGENTS.md instructions",
        "<INSTRUCTIONS>",
        "<environment_context>",
        "<developer_context>",
    )
    return not any(stripped.startswith(prefix) for prefix in hidden_prefixes)


def _extract_token_count(payload: dict[str, Any], fallback: int | None) -> int | None:
    direct = _extract_token_count_value(payload)
    if direct is not None:
        return direct

    info = payload.get("info")
    if isinstance(info, dict):
        info_direct = _extract_token_count_value(info)
        if info_direct is not None:
            return info_direct
        for key in ("total_token_usage", "totalTokenUsage", "usage"):
            nested = info.get(key)
            if isinstance(nested, dict):
                nested_total = _extract_token_count(nested, None)
                if nested_total is not None:
                    return nested_total

    for key in ("total_token_usage", "totalTokenUsage", "usage"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            nested_total = _extract_token_count(nested, None)
            if nested_total is not None:
                return nested_total
    return fallback


def _extract_token_count_value(payload: dict[str, Any]) -> int | None:
    candidates = (
        payload.get("total"),
        payload.get("total_tokens"),
        payload.get("totalTokenCount"),
        payload.get("total_token_count"),
    )
    for candidate in candidates:
        if isinstance(candidate, int):
            return candidate
        if isinstance(candidate, str) and candidate.isdigit():
            return int(candidate)
    return None


def _append_entry(entries: list[Entry], entry: Entry) -> list[Entry]:
    if not entry.text:
        return entries
    if entries and entries[-1].kind == entry.kind and entries[-1].text == entry.text:
        return entries
    return [*entries, entry][-4:]
