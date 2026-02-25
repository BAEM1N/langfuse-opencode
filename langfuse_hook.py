#!/usr/bin/env python3
"""
OpenCode -> Langfuse hook (fail-open).

Input: JSON payload on stdin, usually forwarded by langfuse_plugin.js:
{
  "source": "opencode-plugin",
  "captured_at": "...",
  "event": { "type": "...", "properties": {...} }
}
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import fcntl  # type: ignore
except Exception:  # pragma: no cover
    fcntl = None


CONFIG_DIR = Path.home() / ".config" / "opencode"
STATE_DIR = CONFIG_DIR / "state" / "langfuse"
STATE_FILE = STATE_DIR / "state.json"
STATE_LOCK_FILE = STATE_DIR / "state.lock"
LOG_FILE = STATE_DIR / "langfuse_hook.log"
MAX_CHARS = int(os.environ.get("OPENCODE_LANGFUSE_MAX_CHARS", "20000"))
MAX_MESSAGE_EVENTS_PER_MESSAGE = int(os.environ.get("OPENCODE_LANGFUSE_MAX_MESSAGE_EVENTS_PER_MESSAGE", "30"))

_LOG_LEVELS = {"DEBUG": 10, "INFO": 20, "WARN": 30, "WARNING": 30, "ERROR": 40}


def _load_dotenv() -> None:
    env_path = CONFIG_DIR / ".env"
    try:
        if not env_path.exists():
            return
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip("'\"")
            if key and key not in os.environ:
                os.environ[key] = value
    except Exception:
        pass


def _log(level: str, message: str) -> None:
    level_name = str(level or "INFO").strip().upper()
    level_value = _LOG_LEVELS.get(level_name, _LOG_LEVELS["INFO"])

    env_level = os.environ.get("OPENCODE_LANGFUSE_LOG_LEVEL", "INFO").strip().upper()
    env_value = _LOG_LEVELS.get(env_level, _LOG_LEVELS["INFO"])
    debug_enabled = os.environ.get("OPENCODE_LANGFUSE_DEBUG", "").strip().lower() in ("1", "true", "yes", "on")
    if debug_enabled:
        env_value = _LOG_LEVELS["DEBUG"]

    if level_value < env_value:
        return
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} [{level_name}] {message}\n")
    except Exception:
        pass


def _truncate(value: Any, limit: int = MAX_CHARS) -> Any:
    if not isinstance(value, str):
        return value
    if len(value) <= limit:
        return value
    return value[:limit] + f"\n...[truncated {len(value) - limit} chars]"


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_json(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except Exception:
        return str(value)


def _parse_dt(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        # OpenCode timestamps are milliseconds since epoch.
        if value > 10_000_000_000:
            return datetime.fromtimestamp(float(value) / 1000.0, tz=timezone.utc)
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    if isinstance(value, str):
        v = value.strip()
        if not v:
            return None
        try:
            if v.endswith("Z"):
                return datetime.fromisoformat(v[:-1] + "+00:00")
            dt = datetime.fromisoformat(v)
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            return None
    return None


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _msg_key(session_id: str, message_id: str) -> str:
    return f"{session_id}:{message_id}"


def _turn_key(session_id: str, message_id: str) -> str:
    raw = f"{session_id}:{message_id}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


@contextmanager
def _state_lock():
    lock_fd = None
    locked = False
    try:
        if fcntl is not None:
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            lock_fd = STATE_LOCK_FILE.open("a+", encoding="utf-8")
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
            locked = True
    except Exception:
        locked = False
        if lock_fd is not None:
            try:
                lock_fd.close()
            except Exception:
                pass
            lock_fd = None

    try:
        yield
    finally:
        if locked and lock_fd is not None and fcntl is not None:
            try:
                fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
        if lock_fd is not None:
            try:
                lock_fd.close()
            except Exception:
                pass


def _load_state() -> Dict[str, Any]:
    try:
        if not STATE_FILE.exists():
            return {
                "messages": {},
                "message_events": {},
                "user_parts": {},
                "assistant_parts": {},
                "assistant_finish_seen": {},
                "pending_parts": {},
                "message_last_seen": {},
                "part_last_seen": {},
                "emitted": {},
                "session_lifecycle": {},
            }
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data.setdefault("messages", {})
            data.setdefault("message_events", {})
            data.setdefault("user_parts", {})
            data.setdefault("assistant_parts", {})
            data.setdefault("assistant_finish_seen", {})
            data.setdefault("pending_parts", {})
            data.setdefault("message_last_seen", {})
            data.setdefault("part_last_seen", {})
            data.setdefault("emitted", {})
            data.setdefault("session_lifecycle", {})
            return data
    except Exception:
        pass
    return {
        "messages": {},
        "message_events": {},
        "user_parts": {},
        "assistant_parts": {},
        "assistant_finish_seen": {},
        "pending_parts": {},
        "message_last_seen": {},
        "part_last_seen": {},
        "emitted": {},
        "session_lifecycle": {},
    }


def _save_state(state: Dict[str, Any]) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, STATE_FILE)
    except Exception:
        pass


def _read_payload() -> Dict[str, Any]:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return {}
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    return {}


def _event_obj(payload: Dict[str, Any]) -> Dict[str, Any]:
    ev = payload.get("event")
    if isinstance(ev, dict):
        return ev
    return payload


def _event_name(payload: Dict[str, Any]) -> str:
    ev = _event_obj(payload)
    name = ev.get("type") or ev.get("event") or ev.get("name") or payload.get("type")
    return str(name or "unknown").strip().lower()


def _event_props(payload: Dict[str, Any]) -> Dict[str, Any]:
    ev = _event_obj(payload)
    return _as_dict(ev.get("properties"))


def _session_id(payload: Dict[str, Any]) -> str:
    props = _event_props(payload)
    info = _as_dict(props.get("info"))
    part = _as_dict(props.get("part"))

    for candidate in (
        props.get("sessionID"),
        props.get("sessionId"),
        info.get("sessionID"),
        info.get("sessionId"),
        info.get("id"),  # session.created/info.id
        part.get("sessionID"),
        payload.get("session_id"),
        payload.get("sessionId"),
    ):
        if candidate:
            return str(candidate)
    return "unknown-session"


def _event_captured_at(payload: Dict[str, Any]) -> datetime:
    dt = _parse_dt(payload.get("captured_at"))
    if dt:
        return dt
    ev = _event_obj(payload)
    dt = _parse_dt(ev.get("timestamp"))
    if dt:
        return dt
    return datetime.now(timezone.utc)


def _is_older_event(last_seen: Dict[str, Any], key: str, event_dt: datetime) -> bool:
    prev = _parse_dt(last_seen.get(key))
    if prev is None:
        return False
    return event_dt < prev


def _build_client():
    try:
        from langfuse import Langfuse  # type: ignore
    except Exception:
        return None

    public_key = os.environ.get("LANGFUSE_PUBLIC_KEY", "").strip()
    secret_key = os.environ.get("LANGFUSE_SECRET_KEY", "").strip()
    base_url = os.environ.get("LANGFUSE_BASE_URL", "").strip()
    if not public_key or not secret_key:
        return None

    try:
        kwargs: Dict[str, Any] = {"public_key": public_key, "secret_key": secret_key}
        if base_url:
            kwargs["base_url"] = base_url
        return Langfuse(**kwargs)
    except TypeError:
        try:
            kwargs = {"public_key": public_key, "secret_key": secret_key}
            if base_url:
                kwargs["host"] = base_url
            return Langfuse(**kwargs)
        except Exception:
            return None
    except Exception:
        return None


def _extract_text_from_parts(parts_map: Dict[str, Any]) -> str:
    rows: List[Tuple[datetime, str, str]] = []
    for part in parts_map.values():
        p = _as_dict(part)
        if p.get("type") != "text":
            continue
        text = p.get("text")
        if not isinstance(text, str) or not text:
            continue
        ts = _parse_dt(_as_dict(p.get("time")).get("start")) or datetime.now(timezone.utc)
        rows.append((ts, str(p.get("id") or ""), text))
    rows.sort(key=lambda x: (x[0], x[1]))
    return "\n".join([r[2] for r in rows]).strip()


def _serialize_part(part: Dict[str, Any]) -> Dict[str, Any]:
    p = _as_dict(part)
    time_obj = _as_dict(p.get("time"))
    state_obj = _as_dict(p.get("state"))

    out: Dict[str, Any] = {
        "id": p.get("id"),
        "message_id": p.get("messageID"),
        "type": p.get("type"),
        "time": _safe_json(time_obj) if time_obj else {},
    }

    if isinstance(p.get("text"), str):
        out["text"] = _truncate(p.get("text"))
    if p.get("tool"):
        out["tool"] = p.get("tool")
    if p.get("metadata") is not None:
        out["metadata"] = _safe_json(p.get("metadata"))
    if state_obj:
        out["state"] = {
            "status": state_obj.get("status"),
            "input": _safe_json(state_obj.get("input")),
            "output": _truncate(state_obj.get("output")) if isinstance(state_obj.get("output"), str) else _safe_json(state_obj.get("output")),
            "error": _truncate(state_obj.get("error")) if isinstance(state_obj.get("error"), str) else _safe_json(state_obj.get("error")),
            "metadata": _safe_json(state_obj.get("metadata")),
        }
    return out


def _append_message_event(state: Dict[str, Any], key: str, info: Dict[str, Any]) -> None:
    state["message_events"].setdefault(key, [])
    state["message_events"][key].append(
        {
            "captured_at": _iso_now(),
            "info": _safe_json(info),
        }
    )
    if len(state["message_events"][key]) > MAX_MESSAGE_EVENTS_PER_MESSAGE:
        state["message_events"][key] = state["message_events"][key][-MAX_MESSAGE_EVENTS_PER_MESSAGE:]


def _parts_type_counts(parts_map: Dict[str, Any]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for part in parts_map.values():
        ptype = str(_as_dict(part).get("type") or "unknown")
        counts[ptype] = counts.get(ptype, 0) + 1
    return counts


def _build_turn_details(parts_map: Dict[str, Any]) -> Tuple[str, List[Dict[str, Any]], List[Dict[str, Any]]]:
    text_rows: List[Tuple[datetime, str, str]] = []
    reasoning_rows: List[Dict[str, Any]] = []
    tools: List[Dict[str, Any]] = []

    for part in parts_map.values():
        p = _as_dict(part)
        ptype = str(p.get("type") or "")
        pid = str(p.get("id") or "")
        time_obj = _as_dict(p.get("time"))
        ts = _parse_dt(time_obj.get("start")) or datetime.now(timezone.utc)

        if ptype == "text":
            txt = p.get("text")
            if isinstance(txt, str) and txt:
                text_rows.append((ts, pid, txt))
            continue

        if ptype == "reasoning":
            txt = p.get("text")
            if isinstance(txt, str) and txt:
                reasoning_rows.append({"id": pid, "text": txt, "timestamp": ts, "meta": _safe_json(p.get("metadata"))})
            continue

        if ptype == "tool":
            state = _as_dict(p.get("state"))
            status = str(state.get("status") or "")
            # Emit once tool reaches a terminal state.
            if status not in {"completed", "error"}:
                continue
            input_obj = state.get("input")
            output_txt = state.get("output") if status == "completed" else state.get("error")
            tools.append(
                {
                    "id": pid,
                    "name": p.get("tool") or "tool",
                    "timestamp": ts,
                    "status": status,
                    "input": json.dumps(input_obj, ensure_ascii=False) if isinstance(input_obj, (dict, list)) else str(input_obj or ""),
                    "output": str(output_txt or ""),
                    "meta": _safe_json(state.get("metadata")),
                }
            )

    text_rows.sort(key=lambda x: (x[0], x[1]))
    reasoning_rows.sort(key=lambda x: (x["timestamp"], x["id"]))
    tools.sort(key=lambda x: (x["timestamp"], x["id"]))
    output_text = "\n".join([r[2] for r in text_rows]).strip()
    return output_text, reasoning_rows, tools


def _emit_lifecycle_trace(client: Any, payload: Dict[str, Any], event_name: str, session_id: str) -> None:
    name = f"OpenCode {event_name}"
    user_id = os.environ.get("LANGFUSE_USER_ID", "opencode-user")
    metadata = {
        "product": "opencode",
        "reconstruction": "plugin-event-lifecycle",
        "source": "opencode",
        "event": event_name,
        "session_id": session_id,
        "user_id": user_id,
        "hostname": socket.gethostname(),
        "payload": _safe_json(_event_obj(payload)),
    }
    try:
        with client.start_as_current_span(name=name, metadata=metadata, input=_event_obj(payload)):
            if hasattr(client, "update_current_trace"):
                client.update_current_trace(
                    name=name,
                    session_id=session_id,
                    user_id=user_id,
                    tags=["opencode", "hook-only", "lifecycle"],
                    metadata=metadata,
                )
        client.flush()
    except Exception as exc:
        _log("DEBUG", f"lifecycle emit failed: {exc}")


def _emit_turn_trace(
    client: Any,
    session_id: str,
    user_info: Dict[str, Any],
    assistant_info: Dict[str, Any],
    user_message_events: List[Dict[str, Any]],
    assistant_message_events: List[Dict[str, Any]],
    user_parts_map: Dict[str, Any],
    assistant_parts_map: Dict[str, Any],
    input_text: str,
    output_text: str,
    reasoning: List[Dict[str, Any]],
    tools: List[Dict[str, Any]],
) -> None:
    message_id = str(assistant_info.get("id") or "unknown")
    trace_name = f"OpenCode turn {message_id}"
    user_id = os.environ.get("LANGFUSE_USER_ID", "opencode-user")
    created_at = _parse_dt(_as_dict(assistant_info.get("time")).get("created")) or datetime.now(timezone.utc)

    metadata = {
        "product": "opencode",
        "reconstruction": "plugin-event-turn-assembly",
        "source": "opencode",
        "session_id": session_id,
        "user_id": user_id,
        "hostname": socket.gethostname(),
        "message_id": message_id,
        "parent_message_id": assistant_info.get("parentID"),
        "provider_id": assistant_info.get("providerID"),
        "model_id": assistant_info.get("modelID"),
        "agent": assistant_info.get("agent"),
        "mode": assistant_info.get("mode"),
        "cost": assistant_info.get("cost"),
        "tokens": _safe_json(assistant_info.get("tokens")),
        "reasoning_count": len(reasoning),
        "tool_count": len(tools),
        "messages": {
            "user_info": _safe_json(user_info),
            "assistant_info": _safe_json(assistant_info),
        },
        "message_events": {
            "user": _safe_json(user_message_events),
            "assistant": _safe_json(assistant_message_events),
        },
        "message_events_count": {
            "user": len(user_message_events),
            "assistant": len(assistant_message_events),
        },
        "parts": {
            "user": [_serialize_part(_as_dict(p)) for p in user_parts_map.values()],
            "assistant": [_serialize_part(_as_dict(p)) for p in assistant_parts_map.values()],
        },
        "parts_count": {
            "user_total": len(user_parts_map),
            "assistant_total": len(assistant_parts_map),
            "user_by_type": _parts_type_counts(user_parts_map),
            "assistant_by_type": _parts_type_counts(assistant_parts_map),
        },
    }

    try:
        with client.start_as_current_span(
            name=trace_name,
            input={"role": "user", "content": _truncate(input_text)},
            output={"role": "assistant", "content": _truncate(output_text)},
            metadata=metadata,
        ) as root:
            if hasattr(client, "update_current_trace"):
                client.update_current_trace(
                    name=trace_name,
                    session_id=session_id,
                    user_id=user_id,
                    tags=["opencode", "hook-only", "deep-observability"],
                    metadata=metadata,
                )
            try:
                root.update(start_time=created_at)
            except Exception:
                pass

            step = timedelta(milliseconds=1)
            t_cursor = created_at + step

            if hasattr(client, "start_as_current_generation"):
                try:
                    usage = _as_dict(assistant_info.get("tokens"))
                    usage_payload = {
                        "input": int(usage.get("input") or 0),
                        "output": int(usage.get("output") or 0),
                        "total": int(usage.get("total") or 0),
                        "reasoning": int(usage.get("reasoning") or 0),
                        "input_cache_read": int(_as_dict(usage.get("cache")).get("read") or 0),
                    }
                    with client.start_as_current_generation(
                        name="assistant_turn",
                        model=assistant_info.get("modelID"),
                        input={"role": "user", "content": _truncate(input_text)},
                        output={"role": "assistant", "content": _truncate(output_text)},
                        metadata={"provider_id": assistant_info.get("providerID"), "agent": assistant_info.get("agent")},
                    ) as gen:
                        gen.update(start_time=t_cursor)
                        gen.update(usage=usage_payload)
                        gen.update(usage_details=usage_payload)
                    t_cursor = t_cursor + step
                except Exception:
                    pass

            timeline: List[Tuple[datetime, str, Dict[str, Any]]] = []
            for idx, rb in enumerate(reasoning, start=1):
                timeline.append((rb.get("timestamp") or t_cursor, "reasoning", {"index": idx, **rb}))
            for tool in tools:
                timeline.append((tool.get("timestamp") or t_cursor, "tool", tool))
            timeline.sort(key=lambda x: (x[0], x[1], str(x[2].get("id") or "")))

            for ts, kind, item in timeline:
                span_start = ts if ts > t_cursor else t_cursor + step
                if kind == "reasoning":
                    with client.start_as_current_span(
                        name=f"reasoning[{item.get('index')}]",
                        output=_truncate(item.get("text", "")),
                        metadata={"kind": "reasoning", "meta": item.get("meta")},
                    ) as span:
                        span.update(start_time=span_start)
                    t_cursor = span_start + step
                    continue

                with client.start_as_current_span(
                    name=f"tool:{item.get('name') or 'tool'}",
                    input=_truncate(item.get("input") or ""),
                    output=_truncate(item.get("output") or ""),
                    metadata={"kind": "tool", "status": item.get("status"), "meta": item.get("meta")},
                ) as span:
                    span.update(start_time=span_start)
                t_cursor = span_start + step

        client.flush()
    except Exception as exc:
        _log("DEBUG", f"turn emit failed: {exc}")


def _maybe_emit_assistant_turn(client: Any, state: Dict[str, Any], session_id: str, message_id: str, info: Dict[str, Any]) -> None:
    turn_id = _turn_key(session_id, message_id)
    if state["emitted"].get(turn_id):
        return

    parent_id = str(info.get("parentID") or "")
    user_key = _msg_key(session_id, parent_id) if parent_id else ""
    assistant_key = _msg_key(session_id, message_id)
    user_info = _as_dict(state["messages"].get(user_key))
    user_message_events = state["message_events"].get(user_key, []) if user_key else []
    assistant_message_events = state["message_events"].get(assistant_key, [])
    user_parts = _as_dict(state["user_parts"].get(user_key))
    assistant_parts = _as_dict(state["assistant_parts"].get(assistant_key))

    input_text = _extract_text_from_parts(user_parts)
    output_text, reasoning, tools = _build_turn_details(assistant_parts)
    if not output_text and not reasoning and not tools:
        _log("DEBUG", f"turn skip: no output session={session_id} message={message_id}")
        return

    _emit_turn_trace(
        client,
        session_id,
        user_info,
        info,
        user_message_events,
        assistant_message_events,
        user_parts,
        assistant_parts,
        input_text,
        output_text,
        reasoning,
        tools,
    )
    state["emitted"][turn_id] = _iso_now()
    _log(
        "INFO",
        (
            f"turn emitted session={session_id} turn_id={turn_id} "
            f"assistant_message_id={message_id} "
            f"user_message_events={len(user_message_events)} assistant_message_events={len(assistant_message_events)} "
            f"user_parts={len(user_parts)} assistant_parts={len(assistant_parts)} "
            f"reasoning={len(reasoning)} tools={len(tools)}"
        ),
    )

    # Keep memory bounded.
    state["assistant_parts"].pop(assistant_key, None)
    state["message_events"].pop(assistant_key, None)
    state["assistant_finish_seen"].pop(assistant_key, None)
    if user_key:
        state["user_parts"].pop(user_key, None)
        state["message_events"].pop(user_key, None)


def _cleanup_emitted_message_buffers(state: Dict[str, Any], session_id: str, message_id: str) -> None:
    key = _msg_key(session_id, message_id)
    state["assistant_parts"].pop(key, None)
    state["message_events"].pop(key, None)
    state["assistant_finish_seen"].pop(key, None)


def _flush_pending_assistant_turns(client: Any, state: Dict[str, Any], session_id: str, reason: str) -> None:
    if not session_id or session_id == "unknown-session":
        return

    prefix = f"{session_id}:"
    emitted_now = 0
    scanned = 0
    assistant_parts_map = _as_dict(state.get("assistant_parts"))

    for key in list(assistant_parts_map.keys()):
        if not isinstance(key, str) or not key.startswith(prefix):
            continue
        scanned += 1
        message_id = key[len(prefix):]
        if not message_id:
            continue

        turn_id = _turn_key(session_id, message_id)
        if state["emitted"].get(turn_id):
            _cleanup_emitted_message_buffers(state, session_id, message_id)
            continue

        parts_map = _as_dict(assistant_parts_map.get(key))
        if not parts_map:
            continue

        info = _as_dict(_as_dict(state.get("messages")).get(key))
        if not info:
            info = {"id": message_id, "role": "assistant", "time": {}, "parentID": ""}

        before = bool(state["emitted"].get(turn_id))
        _maybe_emit_assistant_turn(client, state, session_id, message_id, info)
        after = bool(state["emitted"].get(turn_id))
        if after and not before:
            emitted_now += 1

    if emitted_now > 0:
        _log("INFO", f"flush emitted pending turns session={session_id} reason={reason} scanned={scanned} emitted={emitted_now}")


def _handle_message_updated(client: Any, state: Dict[str, Any], payload: Dict[str, Any], session_id: str) -> None:
    info = _as_dict(_event_props(payload).get("info"))
    message_id = str(info.get("id") or "")
    if not message_id:
        return

    key = _msg_key(session_id, message_id)
    event_dt = _event_captured_at(payload)
    message_last_seen = _as_dict(state.get("message_last_seen"))
    state["message_last_seen"] = message_last_seen
    if _is_older_event(message_last_seen, key, event_dt):
        return
    message_last_seen[key] = event_dt.isoformat()

    state["messages"][key] = info

    role = str(info.get("role") or "").lower()
    if role == "assistant":
        turn_id = _turn_key(session_id, message_id)
        if state["emitted"].get(turn_id):
            _cleanup_emitted_message_buffers(state, session_id, message_id)
            return

    _append_message_event(state, key, info)

    # Reconcile out-of-order message.part.updated events.
    pending = _as_dict(state["pending_parts"].pop(key, {}))
    if pending:
        if role in {"assistant", "user"}:
            bucket = "assistant_parts" if role == "assistant" else "user_parts"
            state[bucket].setdefault(key, {}).update(pending)
        else:
            state["pending_parts"][key] = pending

    if role != "assistant":
        return

    completed = bool(_as_dict(info.get("time")).get("completed"))
    if completed:
        state["assistant_finish_seen"][key] = _iso_now()
    if completed:
        _maybe_emit_assistant_turn(client, state, session_id, message_id, info)


def _handle_message_part_updated(client: Any, state: Dict[str, Any], payload: Dict[str, Any], session_id: str) -> None:
    part = _as_dict(_event_props(payload).get("part"))
    message_id = str(part.get("messageID") or "")
    part_id = str(part.get("id") or "")
    if not message_id or not part_id:
        return

    key = _msg_key(session_id, message_id)
    event_dt = _event_captured_at(payload)
    part_key = f"{key}:{part_id}"
    part_last_seen = _as_dict(state.get("part_last_seen"))
    state["part_last_seen"] = part_last_seen
    if _is_older_event(part_last_seen, part_key, event_dt):
        return
    part_last_seen[part_key] = event_dt.isoformat()

    turn_id = _turn_key(session_id, message_id)
    if state["emitted"].get(turn_id):
        _cleanup_emitted_message_buffers(state, session_id, message_id)
        return

    msg = _as_dict(state["messages"].get(key))
    role = str(msg.get("role") or "").lower()
    part_type = str(part.get("type") or "")

    # Fallback inference when message.updated has not arrived yet.
    if not role:
        if part_type in {"reasoning", "tool", "step-start", "step-finish", "patch", "agent", "retry", "compaction"}:
            role = "assistant"
        elif part_type == "text":
            # Keep text parts pending until we know whether this message is user/assistant.
            state["pending_parts"].setdefault(key, {})
            state["pending_parts"][key][part_id] = part
            return

    bucket = "assistant_parts" if role == "assistant" else "user_parts"
    state[bucket].setdefault(key, {})
    state[bucket][key][part_id] = part

    if role == "assistant":
        if part_type == "step-finish":
            state["assistant_finish_seen"][key] = _iso_now()
        completed = bool(_as_dict(msg.get("time")).get("completed")) if msg else False
        finish_seen = bool(_as_dict(state.get("assistant_finish_seen")).get(key))
        if completed or finish_seen:
            _maybe_emit_assistant_turn(client, state, session_id, message_id, msg or {"id": message_id, "role": "assistant"})


def main() -> None:
    _load_dotenv()

    if os.environ.get("TRACE_TO_LANGFUSE", "").strip().lower() != "true":
        return

    payload = _read_payload()
    if not payload:
        return

    client = _build_client()
    if client is None:
        return

    event_name = _event_name(payload)
    session_id = _session_id(payload)
    _log("DEBUG", f"event={event_name} session={session_id}")
    with _state_lock():
        state = _load_state()
        lifecycle_map = _as_dict(state.get("session_lifecycle"))
        state["session_lifecycle"] = lifecycle_map

        if event_name == "message.updated":
            _handle_message_updated(client, state, payload, session_id)
        elif event_name == "message.part.updated":
            _handle_message_part_updated(client, state, payload, session_id)
            last = _as_dict(lifecycle_map.get(session_id))
            last_event = str(last.get("event") or "")
            if last_event in {"session.idle", "session.error", "session.compacted"}:
                _flush_pending_assistant_turns(client, state, session_id, f"{last_event}:post-part")
        elif event_name in {"message.removed", "message.part.removed"}:
            # Best-effort cleanup events can be handled later if needed.
            pass

        if event_name in {"session.created", "session.idle", "session.error", "session.compacted"}:
            event_dt = _event_captured_at(payload)
            prev = _as_dict(lifecycle_map.get(session_id))
            prev_dt = _parse_dt(prev.get("at"))
            if prev_dt is None or event_dt >= prev_dt:
                lifecycle_map[session_id] = {"event": event_name, "at": event_dt.isoformat()}

        if event_name in {"session.idle", "session.error", "session.compacted"}:
            _flush_pending_assistant_turns(client, state, session_id, event_name)

        if event_name in {"session.created", "session.idle", "session.error", "session.compacted"}:
            _emit_lifecycle_trace(client, payload, event_name, session_id)

        _save_state(state)
        _log(
            "DEBUG",
            (
                "state-saved "
                f"messages={len(_as_dict(state.get('messages')))} "
                f"message_events={len(_as_dict(state.get('message_events')))} "
                f"user_parts={len(_as_dict(state.get('user_parts')))} "
                f"assistant_parts={len(_as_dict(state.get('assistant_parts')))} "
                f"assistant_finish_seen={len(_as_dict(state.get('assistant_finish_seen')))} "
                f"pending_parts={len(_as_dict(state.get('pending_parts')))} "
                f"emitted={len(_as_dict(state.get('emitted')))}"
            ),
        )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        try:
            _load_dotenv()
            _log("ERROR", f"fatal exception: {exc}")
        except Exception:
            pass
        # fail-open: never block OpenCode
        pass
