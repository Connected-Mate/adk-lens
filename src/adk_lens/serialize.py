"""Turn ADK objects into small, safe JSON. Never raises, never mutates."""

from __future__ import annotations

import os
from typing import Any

MAX_STR = 4000
MAX_ITEMS = 40
MAX_DEPTH = 6


def content_enabled() -> bool:
    """ADK_LENS_CONTENT=0 keeps prompts, arguments and results out of the lens."""
    return os.environ.get("ADK_LENS_CONTENT", "1").strip().lower() not in ("0", "false", "off", "no")


def clip(text: Any, limit: int = MAX_STR) -> str:
    try:
        s = text if isinstance(text, str) else str(text)
    except Exception:
        return "<unprintable>"
    if len(s) > limit:
        return s[:limit] + f"… (+{len(s) - limit} chars)"
    return s


def safe(obj: Any, depth: int = 0) -> Any:
    """Best-effort conversion to JSON-compatible data with size limits."""
    try:
        if obj is None or isinstance(obj, (bool, int, float)):
            return obj
        if isinstance(obj, str):
            return clip(obj)
        if isinstance(obj, (bytes, bytearray, memoryview)):
            return f"<{len(obj)} bytes>"
        if depth >= MAX_DEPTH:
            return clip(repr(obj), 200)
        if isinstance(obj, dict) or hasattr(obj, "items") and callable(obj.items):
            out = {}
            for i, (k, v) in enumerate(obj.items()):
                if i >= MAX_ITEMS:
                    out["…"] = f"+{len(obj) - MAX_ITEMS} more"
                    break
                out[clip(k, 200)] = safe(v, depth + 1)
            return out
        if isinstance(obj, (list, tuple, set, frozenset)):
            items = list(obj)
            out_list = [safe(v, depth + 1) for v in items[:MAX_ITEMS]]
            if len(items) > MAX_ITEMS:
                out_list.append(f"… +{len(items) - MAX_ITEMS} more")
            return out_list
        dump = getattr(obj, "model_dump", None)
        if callable(dump):
            try:
                return safe(dump(mode="json", exclude_none=True), depth + 1)
            except Exception:
                pass
        return clip(repr(obj), 500)
    except Exception:
        return "<unserializable>"


def parts_of(content: Any) -> list[dict]:
    """Flatten a google.genai Content into simple parts."""
    out: list[dict] = []
    try:
        for part in getattr(content, "parts", None) or []:
            text = getattr(part, "text", None)
            fc = getattr(part, "function_call", None)
            fr = getattr(part, "function_response", None)
            blob = getattr(part, "inline_data", None)
            if text:
                kind = "thought" if getattr(part, "thought", None) else "text"
                out.append({"kind": kind, "text": clip(text)})
            elif fc is not None:
                out.append({
                    "kind": "call",
                    "name": clip(getattr(fc, "name", "") or "", 200),
                    "id": getattr(fc, "id", None),
                    "args": safe(getattr(fc, "args", None)),
                })
            elif fr is not None:
                out.append({
                    "kind": "result",
                    "name": clip(getattr(fr, "name", "") or "", 200),
                    "id": getattr(fr, "id", None),
                    "response": safe(getattr(fr, "response", None)),
                })
            elif blob is not None:
                data = getattr(blob, "data", None) or b""
                out.append({
                    "kind": "file",
                    "mime": getattr(blob, "mime_type", None),
                    "size": len(data),
                })
            else:
                out.append({"kind": "other"})
    except Exception:
        pass
    return out


def text_of(content: Any) -> str:
    return "\n".join(p["text"] for p in parts_of(content) if p.get("kind") == "text")


def redact(event: dict) -> dict:
    """Drop content fields, keep structure (names, timings, counts)."""
    keep = {
        "type", "app", "run", "session", "agent", "tool", "model", "call_id", "ts", "pid",
        "duration_ms", "tokens_in", "tokens_out", "final", "partial", "transfer_to",
        "escalate", "author", "nodes", "edges", "root", "error_type", "nested", "path",
        "state_keys", "calls", "source",
    }
    slim = {k: v for k, v in event.items() if k in keep}
    if "calls" in slim:
        slim["calls"] = [{"name": c.get("name")} for c in slim["calls"] or []]
    if event.get("type") == "topology":
        slim["nodes"] = [
            {k: v for k, v in n.items() if k not in ("instruction",)} for n in event.get("nodes", [])
        ]
    return slim
