# ADK Lens: hub API and event protocol

The hub is a small local web server (`python -m adk_lens.hub`, default `http://127.0.0.1:4790`).
Agent processes push events to it; the browser UI (files in `src/adk_lens/static/`) reads them.

## HTTP API (all JSON, same origin as the UI)

| Method, path | Purpose |
|---|---|
| `GET /api/ping` | `{"adk_lens": "<version>", "pid": 123}` |
| `GET /api/state` | Snapshot: `{"seq": 412, "events": [...all events kept, oldest first], "apps": {"<app>": <topology>}, "versions": {"<app>": [{"v": 1, "ts": 1731000000.0, "hash": "ab12", "topology": {...}}]}, "notes": <whatever the UI last saved, or null>}` |
| `GET /api/stream?since=<seq>` | Server-sent events. Each message: `data: <one event JSON>`. Sends every event with `seq > since`, then live ones. Comment lines `: ping` every 15 s. |
| `PUT /api/notes` | Body = any JSON document (the UI's annotations). Saved to `~/.adk-lens/notes.json`. Requires header `X-ADK-Lens: 1`. |
| `GET /api/notes` | The saved document, or `null`. |
| `POST /api/clear` | Forget all runs (keeps topologies, versions, notes). Requires header `X-ADK-Lens: 1`. |
| `POST /api/ingest` | Used by agent processes: `{"events": [...]}`. Requires header `X-ADK-Lens`. |

## Events

Every event has: `seq` (int, increasing, set by the hub), `ts` (unix seconds, float), `type`, `app` (ADK app name), `pid`.
Events that belong to a run also have `run` (one user request = one run id) and `session`.

| `type` | Extra fields | Meaning in plain words |
|---|---|---|
| `topology` | `root`, `nodes`, `edges`, `source` | The shape of the app. Sent when an app starts and again whenever it changes. |
| `run_start` | `user_message` (text), `parts`, `user`, `root_agent` | Someone sent a message. |
| `agent_start` | `agent` (name), `path`, `nested` (bool) | An agent takes the floor. |
| `agent_end` | `agent`, `duration_ms` | The agent is done. |
| `model_start` | `agent`, `model`, `call_id`, `system` (instruction text), `messages` (count), `last` (parts of the last message sent), `tools` (names offered) | The agent asks the model to think. |
| `model_end` | `agent`, `call_id`, `parts`, `text`, `calls` ([{name,args}]), `tokens_in`, `tokens_out`, `duration_ms`, `finish` | The model answered (text and/or tool requests). |
| `model_error` | `agent`, `call_id`, `error`, `error_type` | The model call failed. |
| `tool_start` | `agent`, `tool`, `call_id`, `args`, `agent_tool` (bool: the tool is another agent) | The agent uses a tool. |
| `tool_end` | `agent`, `tool`, `call_id`, `result`, `duration_ms` | The tool answered. |
| `tool_error` | `agent`, `tool`, `call_id`, `error`, `error_type` | The tool failed. |
| `event` | `author`, `parts`, `text`, `final` (bool), `partial` (bool), `state_delta` (object), `transfer_to` (agent name), `escalate` (bool), `artifacts` ([names]), `branch`, `path` | Anything ADK itself records: a message, a hand-off, a memory change. `final: true` and `author` not `user` = an answer shown to the user. |
| `agent_error` | `agent`, `error`, `error_type` | An agent crashed. |
| `run_end` | `duration_ms` | The request is finished. |
| `run_error` | `error`, `error_type` | The request failed. |

`parts` is a list of `{"kind": "text"|"thought", "text"}`, `{"kind": "call", "name", "id", "args"}`,
`{"kind": "result", "name", "id", "response"}`, `{"kind": "file", "mime", "size"}`.

All text is clipped (4000 chars), so values may end with `… (+N chars)`. Any field may be missing:
with `ADK_LENS_CONTENT=0` only names, timings and counts are sent.

## Topology

```json
{
  "app": "trip_demo",
  "root": "concierge",
  "nodes": [
    {"id": "concierge", "name": "concierge", "kind": "llm", "cls": "LlmAgent", "description": "…",
     "parent": null, "model": "gemini-flash-latest", "instruction": "…", "output_key": "plan"},
    {"id": "concierge::get_weather", "name": "get_weather", "kind": "tool", "description": "…", "parent": "concierge"}
  ],
  "edges": [
    {"from": "concierge", "to": "weather_agent", "kind": "delegate"},
    {"from": "planner", "to": "researcher", "kind": "then", "order": 1},
    {"from": "concierge", "to": "concierge::get_weather", "kind": "uses_tool"}
  ]
}
```

Node `kind`: `llm` (an agent that thinks with a model), `sequential` (runs its children one after the other),
`parallel` (runs them at the same time), `loop` (repeats them), `workflow` (ADK 2 graph), `step` (a workflow step),
`custom`, `remote` (A2A agent), `tool`, `toolset` (a pack of tools, e.g. MCP; its tools are only known when used).

Edge `kind`: `delegate` (can hand over to), `then` (with `order`), `together`, `repeat`, `uses_tool`,
`uses_agent` (agent used as a tool), `flow` (workflow edge, optional `label`), `wraps`.

Runtime names map to nodes like this: an agent event's `agent` equals a node `name` (agent names are unique in an app);
a tool event maps to node id `<agent id>::<tool name>`. The UI must create a node on the fly when an event names
an agent or tool that is not in the topology (toolsets, dynamic tools).
