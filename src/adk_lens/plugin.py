"""The ADK plugin that watches a run and reports it to the lens.

It only observes: every callback returns None (ADK's "carry on" value), nothing
is modified, and any error inside the lens is swallowed so it can never break
an agent.
"""

from __future__ import annotations

import functools
import time
from typing import Any

from google.adk.plugins.base_plugin import BasePlugin

from . import topology
from .serialize import clip, parts_of, safe, text_of
from .transport import emit

PLUGIN_NAME = "adk_lens"


def _quiet(fn):
    """Run a callback, never let an exception out, always return None."""

    @functools.wraps(fn)
    async def wrapper(self, *args, **kwargs):
        try:
            await fn(self, *args, **kwargs)
        except Exception:
            pass
        return None

    return wrapper


class LensPlugin(BasePlugin):
    """Observer plugin. Usable as `--extra_plugins=adk_lens.LensPlugin` too."""

    def __init__(self, name: str = PLUGIN_NAME) -> None:
        super().__init__(name=PLUGIN_NAME if name in ("", None) else name)
        self._run_alias: dict[str, str] = {}      # nested invocation id -> top run id
        self._nested_waiting: dict[tuple, str] = {}  # (app, agent name) -> top run id
        self._started: dict[tuple, float] = {}
        self._model_seq = 0
        self._model_open: dict[tuple, list] = {}
        self._topology_sent: dict[str, int] = {}

    # -- helpers -----------------------------------------------------------
    def _run(self, invocation_id: str) -> str:
        return self._run_alias.get(invocation_id, invocation_id)

    @staticmethod
    def _ctx_ids(ctx: Any) -> tuple[str, str, str]:
        """(app, session id, invocation id) from any ADK context."""
        session = getattr(ctx, "session", None)
        app = getattr(session, "app_name", None) or getattr(ctx, "app_name", None) or "app"
        return str(app), str(getattr(session, "id", "") or ""), str(getattr(ctx, "invocation_id", "") or "")

    def _base(self, ctx: Any, kind: str, **extra: Any) -> dict:
        app, session, invocation = self._ctx_ids(ctx)
        return {"type": kind, "app": app, "session": session, "run": self._run(invocation), **extra}

    def _took(self, key: tuple) -> float | None:
        start = self._started.pop(key, None)
        return None if start is None else round((time.monotonic() - start) * 1000, 1)

    def announce(self, app_name: str, root: Any, source: str = "runner") -> None:
        """Send the app's shape (called when a Runner is created)."""
        try:
            if root is None:
                return
            topo = topology.build(root, app_name)
            emit({"type": "topology", "source": source, **topo})
        except Exception:
            pass

    # -- run ---------------------------------------------------------------
    @_quiet
    async def before_run_callback(self, *, invocation_context) -> None:
        app, session, invocation = self._ctx_ids(invocation_context)
        agent = getattr(invocation_context, "agent", None)
        agent_name = getattr(agent, "name", None)
        parent = self._nested_waiting.pop((app, agent_name), None)
        if parent is not None:
            # An agent used as a tool runs in its own little runner: fold it into the parent run.
            self._run_alias[invocation] = parent
            return
        if len(self._run_alias) > 5000:
            self._run_alias.clear()
        content = getattr(invocation_context, "user_content", None)
        self._started[("run", invocation)] = time.monotonic()
        emit({
            "type": "run_start", "app": app, "session": session, "run": invocation,
            "user": getattr(invocation_context, "user_id", None),
            "root_agent": agent_name,
            "user_message": text_of(content),
            "parts": parts_of(content),
        })

    @_quiet
    async def after_run_callback(self, *, invocation_context) -> None:
        app, session, invocation = self._ctx_ids(invocation_context)
        if invocation in self._run_alias:
            self._run_alias.pop(invocation, None)
            return
        emit({"type": "run_end", "app": app, "session": session, "run": invocation,
              "duration_ms": self._took(("run", invocation))})

    @_quiet
    async def on_run_error_callback(self, *, invocation_context, error) -> None:
        app, session, invocation = self._ctx_ids(invocation_context)
        if invocation in self._run_alias:
            self._run_alias.pop(invocation, None)
            return
        emit({"type": "run_error", "app": app, "session": session, "run": invocation,
              "error": clip(error, 2000), "error_type": type(error).__name__,
              "duration_ms": self._took(("run", invocation))})

    @_quiet
    async def on_event_callback(self, *, invocation_context, event) -> None:
        actions = getattr(event, "actions", None)
        partial = bool(getattr(event, "partial", False))
        parts = parts_of(getattr(event, "content", None))
        text = "\n".join(p["text"] for p in parts if p.get("kind") == "text")
        try:
            final = bool(event.is_final_response())
        except Exception:
            final = False
        out = self._base(
            invocation_context, "event",
            author=getattr(event, "author", None),
            parts=parts if not partial else [],
            text=clip(text, 300) if partial else text,
            final=final,
            partial=partial,
            branch=getattr(event, "branch", None),
            event_id=getattr(event, "id", None),
        )
        # an event carries its own invocation id; prefer it (nested runs)
        ev_inv = getattr(event, "invocation_id", None)
        if ev_inv:
            out["run"] = self._run(str(ev_inv))
        node_info = getattr(event, "node_info", None)
        if getattr(node_info, "path", None):
            out["path"] = node_info.path
        if getattr(event, "output", None) is not None:
            out["output"] = safe(event.output)
        if actions is not None:
            delta = getattr(actions, "state_delta", None)
            if delta:
                out["state_delta"] = safe(delta)
                out["state_keys"] = [str(k) for k in list(delta)[:40]]
            if getattr(actions, "transfer_to_agent", None):
                out["transfer_to"] = actions.transfer_to_agent
            if getattr(actions, "escalate", None):
                out["escalate"] = True
            artifacts = getattr(actions, "artifact_delta", None)
            if artifacts:
                out["artifacts"] = [str(k) for k in list(artifacts)[:40]]
        if getattr(event, "error_message", None) or getattr(event, "error_code", None):
            out["error"] = clip(getattr(event, "error_message", None) or getattr(event, "error_code", ""), 2000)
        emit(out)

    # -- agents ------------------------------------------------------------
    @_quiet
    async def before_agent_callback(self, *, agent, callback_context) -> None:
        _, _, invocation = self._ctx_ids(callback_context)
        name = getattr(agent, "name", None)
        self._started[("agent", invocation, name)] = time.monotonic()
        emit(self._base(callback_context, "agent_start", agent=name,
                        nested=invocation in self._run_alias,
                        path=getattr(callback_context, "node_path", None) or None))

    @_quiet
    async def after_agent_callback(self, *, agent, callback_context) -> None:
        _, _, invocation = self._ctx_ids(callback_context)
        name = getattr(agent, "name", None)
        emit(self._base(callback_context, "agent_end", agent=name,
                        duration_ms=self._took(("agent", invocation, name))))

    @_quiet
    async def on_agent_error_callback(self, *, agent, callback_context, error) -> None:
        _, _, invocation = self._ctx_ids(callback_context)
        name = getattr(agent, "name", None)
        self._started.pop(("agent", invocation, name), None)
        emit(self._base(callback_context, "agent_error", agent=name,
                        error=clip(error, 2000), error_type=type(error).__name__))

    # -- model -------------------------------------------------------------
    @_quiet
    async def before_model_callback(self, *, callback_context, llm_request) -> None:
        _, _, invocation = self._ctx_ids(callback_context)
        agent = getattr(callback_context, "agent_name", None)
        self._model_seq += 1
        call_id = f"m{self._model_seq}"
        self._model_open.setdefault((invocation, agent), []).append(call_id)
        self._started[("model", call_id)] = time.monotonic()
        config = getattr(llm_request, "config", None)
        system = getattr(config, "system_instruction", None)
        if system is not None and not isinstance(system, str):
            system = text_of(system) or clip(system, 2000)
        contents = list(getattr(llm_request, "contents", None) or [])
        emit(self._base(
            callback_context, "model_start", agent=agent, call_id=call_id,
            model=getattr(llm_request, "model", None),
            system=clip(system or "", 3000),
            messages=len(contents),
            last=parts_of(contents[-1]) if contents else [],
            tools=[str(k) for k in list(getattr(llm_request, "tools_dict", None) or {})[:60]],
        ))

    def _close_model(self, callback_context) -> tuple[str | None, str | None]:
        _, _, invocation = self._ctx_ids(callback_context)
        agent = getattr(callback_context, "agent_name", None)
        stack = self._model_open.get((invocation, agent)) or []
        call_id = stack.pop() if stack else None
        if not stack:
            self._model_open.pop((invocation, agent), None)
        return agent, call_id

    @_quiet
    async def after_model_callback(self, *, callback_context, llm_response) -> None:
        if getattr(llm_response, "partial", False):
            return  # streamed chunks: the complete answer follows
        agent, call_id = self._close_model(callback_context)
        parts = parts_of(getattr(llm_response, "content", None))
        usage = getattr(llm_response, "usage_metadata", None)
        finish = getattr(llm_response, "finish_reason", None)
        out = self._base(
            callback_context, "model_end", agent=agent, call_id=call_id,
            parts=parts,
            text="\n".join(p["text"] for p in parts if p.get("kind") == "text"),
            calls=[{"name": p.get("name"), "args": p.get("args")} for p in parts if p.get("kind") == "call"],
            tokens_in=getattr(usage, "prompt_token_count", None),
            tokens_out=getattr(usage, "candidates_token_count", None),
            finish=getattr(finish, "name", None) or (str(finish) if finish else None),
            duration_ms=self._took(("model", call_id)) if call_id else None,
        )
        if getattr(llm_response, "error_message", None):
            out["error"] = clip(llm_response.error_message, 2000)
        emit(out)

    @_quiet
    async def on_model_error_callback(self, *, callback_context, llm_request, error) -> None:
        agent, call_id = self._close_model(callback_context)
        if call_id:
            self._started.pop(("model", call_id), None)
        emit(self._base(callback_context, "model_error", agent=agent, call_id=call_id,
                        error=clip(error, 2000), error_type=type(error).__name__))

    # -- tools -------------------------------------------------------------
    @staticmethod
    def _call_id(tool, tool_context) -> str:
        return str(getattr(tool_context, "function_call_id", None) or f"{getattr(tool, 'name', 'tool')}@{id(tool_context)}")

    @_quiet
    async def before_tool_callback(self, *, tool, tool_args, tool_context) -> None:
        app, _, invocation = self._ctx_ids(tool_context)
        call_id = self._call_id(tool, tool_context)
        self._started[("tool", call_id)] = time.monotonic()
        inner = getattr(tool, "agent", None)
        is_agent_tool = inner is not None and hasattr(inner, "name")
        if is_agent_tool:
            if len(self._nested_waiting) > 500:
                self._nested_waiting.clear()
            self._nested_waiting[(app, inner.name)] = self._run(invocation)
        emit(self._base(tool_context, "tool_start",
                        agent=getattr(tool_context, "agent_name", None),
                        tool=getattr(tool, "name", None), call_id=call_id,
                        args=safe(tool_args), agent_tool=is_agent_tool))

    @_quiet
    async def after_tool_callback(self, *, tool, tool_args, tool_context, result) -> None:
        call_id = self._call_id(tool, tool_context)
        emit(self._base(tool_context, "tool_end",
                        agent=getattr(tool_context, "agent_name", None),
                        tool=getattr(tool, "name", None), call_id=call_id,
                        result=safe(result), duration_ms=self._took(("tool", call_id))))

    @_quiet
    async def on_tool_error_callback(self, *, tool, tool_args, tool_context, error) -> None:
        call_id = self._call_id(tool, tool_context)
        emit(self._base(tool_context, "tool_error",
                        agent=getattr(tool_context, "agent_name", None),
                        tool=getattr(tool, "name", None), call_id=call_id,
                        error=clip(error, 2000), error_type=type(error).__name__,
                        duration_ms=self._took(("tool", call_id))))


# One shared instance, also usable as `--extra_plugins=adk_lens.plugin.lens_plugin`.
lens_plugin = LensPlugin()
