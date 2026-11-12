"""Read the shape of an ADK app (agents, tools, workflow steps) without running it.

Only reads attributes. Never calls user code, never opens toolset connections.
"""

from __future__ import annotations

from typing import Any

from .serialize import clip


_HOOKS = ("before_agent", "after_agent", "before_model", "after_model", "on_model_error",
          "before_tool", "after_tool", "on_tool_error")


def _guards(node: Any) -> list[dict]:
    """The agent's own callbacks (checks, filters, safety guards): when they run and their name.

    Only reads the function's name and the first line of its docstring; never calls it.
    """
    out: list[dict] = []
    for hook in _HOOKS:
        try:
            found = getattr(node, hook + "_callback", None)
        except Exception:
            found = None
        if not found:
            continue
        for fn in found if isinstance(found, (list, tuple)) else [found]:
            name = getattr(fn, "__name__", None) or type(fn).__name__
            item = {"when": hook, "name": str(name)}
            doc = (getattr(fn, "__doc__", None) or "").strip().split("\n")[0]
            if doc:
                item["about"] = clip(doc, 200)
            out.append(item)
    return out[:24]


def _kind_of(node: Any) -> str:
    names = {c.__name__ for c in type(node).__mro__}
    if "SequentialAgent" in names:
        return "sequential"
    if "ParallelAgent" in names:
        return "parallel"
    if "LoopAgent" in names:
        return "loop"
    if "LlmAgent" in names:
        return "llm"
    if "RemoteA2aAgent" in names:
        return "remote"
    if "Workflow" in names:
        return "workflow"
    if "BaseAgent" in names:
        return "custom"
    if "BaseNode" in names:
        return "step"
    return "custom"


def _model_name(agent: Any) -> str | None:
    model = getattr(agent, "model", None)
    if not model:
        # LlmAgent inherits its model from the nearest ancestor that has one.
        parent = getattr(agent, "parent_agent", None)
        hops = 0
        while parent is not None and hops < 20 and not model:
            model = getattr(parent, "model", None)
            parent = getattr(parent, "parent_agent", None)
            hops += 1
    if not model:
        return None
    if isinstance(model, str):
        return model
    return getattr(model, "model", None) or type(model).__name__


def _tool_info(tool: Any) -> dict:
    """Describe one entry of LlmAgent.tools."""
    cls = {c.__name__ for c in type(tool).__mro__}
    if "AgentTool" in cls:
        inner = getattr(tool, "agent", None)
        return {"kind": "agent_tool", "name": getattr(tool, "name", None) or getattr(inner, "name", "agent"), "agent": inner}
    if "BaseToolset" in cls:
        label = type(tool).__name__
        prefix = getattr(tool, "tool_name_prefix", None)
        return {"kind": "toolset", "name": f"{prefix} ({label})" if prefix else label, "prefix": prefix}
    if "BaseTool" in cls:
        return {
            "kind": "tool",
            "name": getattr(tool, "name", type(tool).__name__),
            "description": getattr(tool, "description", "") or "",
        }
    if callable(tool):
        return {
            "kind": "tool",
            "name": getattr(tool, "__name__", type(tool).__name__),
            "description": (getattr(tool, "__doc__", "") or "").strip(),
        }
    return {"kind": "tool", "name": type(tool).__name__, "description": ""}


def build(root: Any, app_name: str) -> dict:
    """Return {"root": id, "nodes": [...], "edges": [...]} for an agent or workflow root."""
    nodes: list[dict] = []
    edges: list[dict] = []
    seen: dict[int, str] = {}
    used_ids: set[str] = set()

    def new_id(base: str) -> str:
        nid, i = base, 2
        while nid in used_ids:
            nid, i = f"{base}#{i}", i + 1
        used_ids.add(nid)
        return nid

    def add_agent(node: Any, parent_id: str | None, relation: str, order: int | None = None) -> str | None:
        if node is None:
            return None
        if id(node) in seen:
            if parent_id:
                edges.append({"from": parent_id, "to": seen[id(node)], "kind": relation})
            return seen[id(node)]
        if len(nodes) > 400:
            return None
        name = str(getattr(node, "name", None) or type(node).__name__)
        nid = new_id(name)
        seen[id(node)] = nid
        kind = _kind_of(node)
        info: dict[str, Any] = {
            "id": nid,
            "name": name,
            "kind": kind,
            "cls": type(node).__name__,
            "description": clip(getattr(node, "description", "") or "", 400),
            "parent": parent_id,
        }
        if kind == "llm":
            info["model"] = _model_name(node)
            instruction = getattr(node, "instruction", None)
            if isinstance(instruction, str) and instruction:
                info["instruction"] = clip(instruction, 1200)
            elif instruction:
                info["instruction"] = "(computed when the agent runs)"
            if getattr(node, "output_key", None):
                info["output_key"] = str(node.output_key)
            if getattr(node, "mode", None):
                info["mode"] = str(node.mode)
        guards = _guards(node)
        if guards:
            info["guards"] = guards
        if kind == "loop" and getattr(node, "max_iterations", None):
            info["max_iterations"] = node.max_iterations
        nodes.append(info)
        if parent_id:
            edge = {"from": parent_id, "to": nid, "kind": relation}
            if order is not None:
                edge["order"] = order
            edges.append(edge)

        # Classic sub-agents.
        children = list(getattr(node, "sub_agents", None) or [])
        rel = {"sequential": "then", "parallel": "together", "loop": "repeat"}.get(kind, "delegate")
        for i, child in enumerate(children):
            add_agent(child, nid, rel, i + 1 if kind in ("sequential", "loop") else None)

        # Tools of an LLM agent.
        for tool in list(getattr(node, "tools", None) or []):
            try:
                t = _tool_info(tool)
            except Exception:
                continue
            if t["kind"] == "agent_tool":
                add_agent(t["agent"], nid, "uses_agent")
                continue
            tid = new_id(f"{nid}::{t['name']}")
            nodes.append({
                "id": tid,
                "name": str(t["name"]),
                "kind": t["kind"],
                "description": clip(t.get("description", ""), 400),
                "parent": nid,
                **({"prefix": t["prefix"]} if t.get("prefix") else {}),
            })
            edges.append({"from": nid, "to": tid, "kind": "uses_tool"})

        # ADK 2 graph workflows.
        graph = getattr(node, "graph", None)
        if kind == "workflow" and graph is not None:
            try:
                for step in list(getattr(graph, "nodes", None) or []):
                    if getattr(step, "name", "") == "__START__":
                        continue
                    if id(step) not in seen:
                        add_agent(step, None, "step")
                        nodes[[n["id"] for n in nodes].index(seen[id(step)])]["parent"] = nid
                for edge in list(getattr(graph, "edges", None) or []):
                    a, b = getattr(edge, "from_node", None), getattr(edge, "to_node", None)
                    a_id = nid if getattr(a, "name", "") == "__START__" else seen.get(id(a))
                    b_id = seen.get(id(b))
                    if a_id and b_id:
                        item = {"from": a_id, "to": b_id, "kind": "flow"}
                        route = getattr(edge, "route", None)
                        if route is not None:
                            item["label"] = clip(route, 60)
                        edges.append(item)
            except Exception:
                pass
        elif kind in ("step", "custom"):
            # Wrapper nodes (for example an LLM agent used as a workflow step).
            try:
                for child in node._iter_static_children():
                    add_agent(child, nid, "wraps")
            except Exception:
                pass
        return nid

    root_id = add_agent(root, None, "root")
    return {"app": app_name, "root": root_id, "nodes": nodes, "edges": edges}
