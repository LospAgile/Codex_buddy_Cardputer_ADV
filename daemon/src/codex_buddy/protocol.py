from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from typing import Any


PROTOCOL_VERSION = 0
VALID_STATES = {"idle", "running", "waiting", "review", "failed"}
VALID_ANIMATIONS = {
    "idle",
    "running",
    "waiting",
    "waving",
    "jumping",
    "review",
    "failed",
    "running-right",
    "running-left",
}
ANIMATION_BY_STATE = {
    "idle": "idle",
    "running": "running",
    "waiting": "waving",
    "review": "review",
    "failed": "failed",
}
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def clean_text(value: Any, max_chars: int = 120) -> str:
    """按 Unicode 字符裁剪文本，避免把控制字符发给固件。"""

    if value is None:
        return ""
    text = _CONTROL_RE.sub("", str(value)).strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def clean_secret(value: Any, max_chars: int = 120) -> str:
    """保留密码/token 的首尾空格，只移除控制字符并做长度限制。"""

    if value is None:
        return ""
    text = _CONTROL_RE.sub("", str(value))
    return text[:max_chars]


def json_line(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"


def animation_for_state(state: str) -> str:
    return ANIMATION_BY_STATE.get(state, "idle")


def normalize_animation(animation: str, state: str = "idle") -> str:
    if animation in VALID_ANIMATIONS:
        return animation
    return animation_for_state(state)


@dataclass(frozen=True)
class Entry:
    kind: str
    text: str

    def to_json(self) -> dict[str, str]:
        return {
            "kind": clean_text(self.kind, 24),
            "text": clean_text(self.text, 80),
        }


@dataclass(frozen=True)
class PetInfo:
    pet_id: str = ""
    display_name: str = ""

    def to_json(self) -> dict[str, str]:
        if not self.pet_id and not self.display_name:
            return {}
        return {
            "id": clean_text(self.pet_id, 48),
            "displayName": clean_text(self.display_name, 48),
        }


@dataclass(frozen=True)
class Heartbeat:
    state: str = "idle"
    animation: str = ""
    summary: str = ""
    entries: list[Entry] = field(default_factory=list)
    total_tokens: int | None = None
    today_tokens: int | None = None
    pet: PetInfo = field(default_factory=PetInfo)

    def to_json(self) -> dict[str, Any]:
        state = self.state if self.state in VALID_STATES else "idle"
        payload: dict[str, Any] = {
            "v": PROTOCOL_VERSION,
            "type": "heartbeat",
            "state": state,
            "animation": normalize_animation(self.animation, state),
            "summary": clean_text(self.summary, 96),
            "entries": [entry.to_json() for entry in self.entries[:4]],
        }
        tokens: dict[str, int] = {}
        if self.total_tokens is not None:
            tokens["total"] = max(0, int(self.total_tokens))
        if self.today_tokens is not None:
            tokens["today"] = max(0, int(self.today_tokens))
        if tokens:
            payload["tokens"] = tokens
        pet_payload = self.pet.to_json()
        if pet_payload:
            payload["pet"] = pet_payload
        return payload

    def to_line(self) -> str:
        return json_line(self.to_json())


@dataclass(frozen=True)
class ApprovalRequest:
    request_id: str
    tool: str
    hint: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "v": PROTOCOL_VERSION,
            "type": "approval_request",
            "id": clean_text(self.request_id, 96),
            "tool": clean_text(self.tool, 48),
            "hint": clean_text(self.hint, 96),
            "choices": ["approve_once", "deny"],
        }

    def to_line(self) -> str:
        return json_line(self.to_json())


@dataclass(frozen=True)
class WifiConfigRequest:
    ssid: str | None = None
    password: str | None = None
    host: str | None = None
    port: int | None = None
    token: str | None = None
    clear: bool = False
    connect: bool = True

    def to_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "v": PROTOCOL_VERSION,
            "type": "wifi_config",
            "connect": self.connect,
        }
        if self.clear:
            payload["clear"] = True
        if self.ssid is not None:
            payload["ssid"] = clean_text(self.ssid, 32)
        if self.password is not None:
            payload["password"] = clean_secret(self.password, 64)
        if self.host is not None:
            payload["host"] = clean_text(self.host, 63)
        if self.port is not None:
            payload["port"] = max(1, min(65535, int(self.port)))
        if self.token is not None:
            payload["token"] = clean_secret(self.token, 95)
        return payload

    def to_line(self) -> str:
        return json_line(self.to_json())


def build_hello(source: str = "codex-buddy-daemon") -> str:
    return json_line(
        {
            "v": PROTOCOL_VERSION,
            "type": "hello",
            "source": clean_text(source, 48),
        }
    )


def build_button_event(button: str, action: str = "short") -> str:
    return json_line(
        {
            "v": PROTOCOL_VERSION,
            "type": "button",
            "button": clean_text(button, 24),
            "action": clean_text(action, 24),
        }
    )


def build_approval_decision(request_id: str, decision: str) -> str:
    if decision not in {"approve_once", "deny"}:
        raise ValueError(f"unsupported approval decision: {decision}")
    return json_line(
        {
            "v": PROTOCOL_VERSION,
            "type": "approval_decision",
            "id": clean_text(request_id, 96),
            "decision": decision,
        }
    )
