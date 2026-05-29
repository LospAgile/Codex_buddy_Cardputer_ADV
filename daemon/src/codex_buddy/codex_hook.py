from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any, Callable

from .protocol import ApprovalRequest, clean_text


HOOK_EVENT_NAME = "PermissionRequest"
SENSITIVE_KEY_PARTS = ("password", "passwd", "token", "secret", "api_key", "apikey", "auth", "cookie", "credential")
SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b([A-Z0-9_]*(?:TOKEN|KEY|SECRET|PASSWORD|PASS|AUTH)[A-Z0-9_]*)=(\"[^\"]*\"|'[^']*'|\S+)"
)


@dataclass(frozen=True)
class HookApprovalDecision:
    request_id: str
    decision: str


@dataclass(frozen=True)
class HookInputContext:
    session_id: str = ""
    cwd: str = ""


def hook_context_from_input(raw_input: str) -> HookInputContext:
    try:
        payload = _load_hook_input(raw_input)
    except Exception:
        return HookInputContext()
    session_id = clean_text(payload.get("session_id"), 96)
    tool_input = payload.get("tool_input")
    cwd = ""
    if isinstance(tool_input, dict):
        cwd = clean_text(tool_input.get("workdir") or tool_input.get("cwd"), 240)
    return HookInputContext(session_id=session_id, cwd=cwd)


def approval_request_from_hook_input(raw_input: str) -> ApprovalRequest:
    payload = _load_hook_input(raw_input)
    tool_name = clean_text(payload.get("tool_name") or "tool", 48)
    request_id = _request_id(payload)
    hint = _hint_for_tool_input(tool_name, payload.get("tool_input"))
    return ApprovalRequest(request_id, tool_name, hint)


def run_permission_request_hook(
    raw_input: str,
    send_request: Callable[[ApprovalRequest], str],
) -> str:
    try:
        request = approval_request_from_hook_input(raw_input)
        response = send_request(request)
        decision = parse_approval_decision_line(response)
    except Exception as exc:
        return fallback_to_codex_ui(f"Codex Buddy unavailable: {exc}")

    if decision.request_id != request.request_id:
        return fallback_to_codex_ui("Codex Buddy returned a mismatched approval id")

    if decision.decision == "approve_once":
        return hook_decision_output("allow")
    if decision.decision == "deny":
        return hook_decision_output("deny", "Denied on Codex Buddy hardware")
    return fallback_to_codex_ui(f"Unsupported Codex Buddy decision: {decision.decision}")


def parse_approval_decision_line(line: str) -> HookApprovalDecision:
    payload = json.loads(line)
    if payload.get("type") != "approval_decision":
        raise ValueError("expected approval_decision")
    request_id = clean_text(payload.get("id"), 96)
    decision = clean_text(payload.get("decision"), 32)
    if not request_id:
        raise ValueError("approval decision id is empty")
    if decision not in {"approve_once", "deny"}:
        raise ValueError(f"unsupported approval decision: {decision}")
    return HookApprovalDecision(request_id, decision)


def hook_decision_output(behavior: str, message: str = "") -> str:
    if behavior not in {"allow", "deny"}:
        raise ValueError(f"unsupported hook behavior: {behavior}")
    decision: dict[str, Any] = {"behavior": behavior}
    if behavior == "deny":
        decision["message"] = clean_text(message or "Denied on Codex Buddy hardware", 160)
    return _json_line(
        {
            "hookSpecificOutput": {
                "hookEventName": HOOK_EVENT_NAME,
                "decision": decision,
            }
        }
    )


def fallback_to_codex_ui(message: str) -> str:
    return _json_line(
        {
            "continue": True,
            "systemMessage": clean_text(message, 180),
        }
    )


def _load_hook_input(raw_input: str) -> dict[str, Any]:
    payload = json.loads(raw_input)
    if not isinstance(payload, dict):
        raise ValueError("hook input must be a JSON object")
    if payload.get("hook_event_name") != HOOK_EVENT_NAME:
        raise ValueError(f"unsupported hook event: {payload.get('hook_event_name')}")
    return payload


def _request_id(payload: dict[str, Any]) -> str:
    session = clean_text(payload.get("session_id"), 24)
    turn = clean_text(payload.get("turn_id"), 24)
    tool_name = clean_text(payload.get("tool_name"), 48)
    tool_input = json.dumps(payload.get("tool_input"), ensure_ascii=False, sort_keys=True)
    digest = hashlib.sha1(f"{session}|{turn}|{tool_name}|{tool_input}".encode("utf-8")).hexdigest()
    prefix = "-".join(part for part in (session[:8], turn[:8]) if part)
    return clean_text(f"{prefix}-{digest[:10]}" if prefix else digest[:16], 96)


def _hint_for_tool_input(tool_name: str, tool_input: Any) -> str:
    if isinstance(tool_input, dict):
        command = tool_input.get("command") or tool_input.get("cmd")
        if isinstance(command, str) and command.strip():
            hint = _safe_scalar(command)
            workdir = _safe_scalar(tool_input.get("workdir") or tool_input.get("cwd"))
            if workdir:
                hint = f"{hint} @ {workdir}"
            return clean_text(hint, 96)
        for key in ("name", "path", "file", "description", "justification"):
            value = tool_input.get(key)
            if isinstance(value, str) and value.strip():
                return clean_text(_safe_scalar(value), 96)
        pairs = _summary_pairs(tool_input)
        if pairs:
            return clean_text("; ".join(pairs), 96)
    return clean_text(f"Codex requests permission for {tool_name}", 96)


def _summary_pairs(tool_input: dict[str, Any]) -> list[str]:
    pairs: list[str] = []
    preferred_keys = (
        "path",
        "file",
        "url",
        "query",
        "q",
        "session_id",
        "workdir",
        "cwd",
        "chars",
        "body",
        "content",
    )
    ordered_keys = list(preferred_keys) + sorted(
        key for key in tool_input.keys() if key not in preferred_keys
    )
    for key in ordered_keys:
        if key not in tool_input:
            continue
        value = _summarize_value(key, tool_input[key])
        if not value:
            continue
        pairs.append(f"{key}={value}")
        if len("; ".join(pairs)) >= 88 or len(pairs) >= 3:
            break
    return pairs


def _summarize_value(key: str, value: Any) -> str:
    if _is_sensitive_key(key):
        return "[redacted]"
    if isinstance(value, str):
        return _safe_scalar(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    if value is None:
        return ""
    return clean_text(json.dumps(_redact_nested(value), ensure_ascii=False, sort_keys=True), 48)


def _safe_scalar(value: Any) -> str:
    if value is None:
        return ""
    return clean_text(_redact_inline_secrets(str(value)), 72)


def _redact_nested(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): "[redacted]" if _is_sensitive_key(str(key)) else _redact_nested(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_nested(item) for item in value[:4]]
    if isinstance(value, str):
        return _redact_inline_secrets(value)
    return value


def _redact_inline_secrets(text: str) -> str:
    return SECRET_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}=[redacted]", text)


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(part in normalized for part in SENSITIVE_KEY_PARTS)


def _json_line(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
