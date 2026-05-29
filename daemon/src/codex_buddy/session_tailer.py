from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
import json
import os
from pathlib import Path
import time
from typing import Any, Iterator

from .codex_state import CodexSnapshot, snapshot_from_events

ACTIVE_SESSION_FILENAME = "codex-buddy-active-session.json"
ACTIVE_SESSION_TTL_SECONDS = 12 * 60 * 60
JSONL_TAIL_CHUNK_BYTES = 64 * 1024
JSONL_TAIL_MAX_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class ActiveSessionMarker:
    session_id: str = ""
    updated_at: float = 0.0
    cwd: str = ""


def default_codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()


def iter_session_files(codex_home: Path | None = None) -> Iterator[Path]:
    home = codex_home or default_codex_home()
    sessions_dir = home / "sessions"
    if not sessions_dir.exists():
        return
    yield from sorted(
        sessions_dir.glob("**/*.jsonl"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )


def latest_session_file(
    codex_home: Path | None = None,
    *,
    session_id: str | None = None,
    session_cwd: Path | None = None,
    session_source: str | None = None,
    prefer_active: bool = True,
) -> Path | None:
    home = codex_home or default_codex_home()
    if session_id:
        return find_session_file(session_id, home)

    cwd_text = str(session_cwd.expanduser()) if session_cwd is not None else ""
    source_text = session_source.strip() if session_source else ""
    latest_path = _latest_session_file_for_filters(home, cwd_text, source_text)

    if prefer_active:
        marker = read_active_session_marker(home)
        if marker.session_id:
            active_path = find_session_file(marker.session_id, home)
            if active_path is not None and _active_marker_matches_filters(
                marker,
                active_path,
                cwd_text,
                source_text,
            ):
                latest_mtime = latest_path.stat().st_mtime if latest_path else 0.0
                if latest_path is None or marker.updated_at >= latest_mtime:
                    return active_path
                if active_path == latest_path:
                    return active_path

    return latest_path


def _latest_session_file_for_filters(
    home: Path,
    cwd_text: str,
    source_text: str,
) -> Path | None:
    for path in iter_session_files(home):
        if not _session_file_matches_filters(path, cwd_text, source_text):
            continue
        return path
    return None


def _active_marker_matches_filters(
    marker: ActiveSessionMarker,
    active_path: Path,
    cwd_text: str,
    source_text: str,
) -> bool:
    if cwd_text and marker.cwd and marker.cwd != cwd_text:
        return False
    return _session_file_matches_filters(active_path, cwd_text, source_text)


def _session_file_matches_filters(
    path: Path,
    cwd_text: str,
    source_text: str,
) -> bool:
    if cwd_text and session_cwd_from_file(path) != cwd_text:
        return False
    if source_text and session_source_from_file(path) != source_text:
        return False
    return True


def find_session_file(session_id: str, codex_home: Path | None = None) -> Path | None:
    needle = session_id.strip()
    if not needle:
        return None
    home = codex_home or default_codex_home()
    for path in iter_session_files(home):
        if needle in path.name:
            return path
    for path in iter_session_files(home):
        if session_id_from_file(path) == needle:
            return path
    return None


def read_jsonl(path: Path, max_lines: int = 2000) -> list[dict[str, Any]]:
    if not path.exists():
        return []

    lines = _tail_lines(path, max_lines=max_lines)

    events: list[dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def _tail_lines(path: Path, *, max_lines: int) -> list[str]:
    if max_lines <= 0:
        return []
    chunks: list[bytes] = []
    bytes_read = 0
    newline_count = 0
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            position = handle.tell()
            while (
                position > 0
                and newline_count <= max_lines
                and bytes_read < JSONL_TAIL_MAX_BYTES
            ):
                read_size = min(
                    JSONL_TAIL_CHUNK_BYTES,
                    position,
                    JSONL_TAIL_MAX_BYTES - bytes_read,
                )
                if read_size <= 0:
                    break
                position -= read_size
                handle.seek(position)
                chunk = handle.read(read_size)
                chunks.append(chunk)
                bytes_read += len(chunk)
                newline_count += chunk.count(b"\n")
    except OSError:
        return []

    text = b"".join(reversed(chunks)).decode("utf-8", errors="replace")
    lines = text.splitlines()
    if len(lines) > max_lines:
        lines = lines[-max_lines:]
    return lines


def snapshot_latest_session(
    codex_home: Path | None = None,
    *,
    session_id: str | None = None,
    session_cwd: Path | None = None,
    session_source: str | None = None,
) -> CodexSnapshot:
    path = latest_session_file(
        codex_home,
        session_id=session_id,
        session_cwd=session_cwd,
        session_source=session_source,
    )
    if path is None:
        return CodexSnapshot(state="idle", summary="没有找到 Codex 会话")
    events = read_jsonl(path)
    snapshot = snapshot_from_events(events, source=path)
    return replace(
        snapshot,
        today_tokens=today_token_total(codex_home),
    )


def today_token_total(codex_home: Path | None = None) -> int | None:
    today = datetime.now().date()
    total = 0
    found = False
    for path in iter_session_files(codex_home):
        file_date = datetime.fromtimestamp(path.stat().st_mtime).date()
        if file_date < today:
            break
        if file_date != today:
            continue
        snapshot = snapshot_from_events(read_jsonl(path), source=path)
        if snapshot.total_tokens is None:
            continue
        total += snapshot.total_tokens
        found = True
    return total if found else None


def record_active_session(
    codex_home: Path | None,
    session_id: str,
    *,
    cwd: str | None = None,
) -> None:
    clean_session_id = session_id.strip()
    if not clean_session_id:
        return
    home = codex_home or default_codex_home()
    home.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {
        "session_id": clean_session_id,
        "updated_at": time.time(),
    }
    if cwd:
        payload["cwd"] = cwd
    active_session_path(home).write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def read_active_session_id(codex_home: Path | None = None) -> str:
    return read_active_session_marker(codex_home).session_id


def read_active_session_marker(
    codex_home: Path | None = None,
) -> ActiveSessionMarker:
    path = active_session_path(codex_home or default_codex_home())
    if not path.exists():
        return ActiveSessionMarker()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ActiveSessionMarker()
    updated_at = payload.get("updated_at")
    if isinstance(updated_at, int | float):
        if time.time() - float(updated_at) > ACTIVE_SESSION_TTL_SECONDS:
            return ActiveSessionMarker()
    else:
        updated_at = 0.0
    session_id = payload.get("session_id")
    cwd = payload.get("cwd")
    return ActiveSessionMarker(
        session_id=session_id if isinstance(session_id, str) else "",
        updated_at=float(updated_at),
        cwd=cwd if isinstance(cwd, str) else "",
    )


def active_session_path(codex_home: Path) -> Path:
    return codex_home.expanduser() / ACTIVE_SESSION_FILENAME


def session_id_from_file(path: Path) -> str:
    payload = _session_meta_payload(path)
    session_id = payload.get("id")
    return session_id if isinstance(session_id, str) else ""


def session_cwd_from_file(path: Path) -> str:
    payload = _session_meta_payload(path)
    cwd = payload.get("cwd")
    return cwd if isinstance(cwd, str) else ""


def session_source_from_file(path: Path) -> str:
    payload = _session_meta_payload(path)
    source = payload.get("source")
    return source if isinstance(source, str) else ""


def _session_meta_payload(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(event, dict) or event.get("type") != "session_meta":
                    continue
                payload = event.get("payload")
                return payload if isinstance(payload, dict) else {}
    except OSError:
        return {}
    return {}
