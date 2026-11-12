# ADK Lens: hub API and event protocol

The hub is a small local web server (`python -m adk_lens.hub`, default `http://127.0.0.1:4790`).
Agent processes push events to it; the browser UI (files in `src/adk_lens/static/`) reads them.

## HTTP API (all JSON, same origin as the UI)

| Method, path | Purpose |
|---|---|
| `GET /api/ping` | `{"adk_lens": "<version>", "pid": 123}` |
| `GET /api/state` | Snapshot: `{"seq": 412, "events": [...all events kept, oldest first], "apps": {"<app>": <topology of the current version>}, "versions": {"<app>": [<version>, ...]}, "current": {"<app>": <v of the current version>}, "notes": <whatever the UI last saved, or null>}`. See [Versions](#versions). |
| `GET /api/stream?since=<seq>` | Server-sent events. Each message: `data: <one event JSON>`. Sends every event with `seq > since`, then live ones. Comment lines `: ping` every 15 s. |
| `PUT /api/notes` | Body = any JSON document (the UI's annotations). Saved to `~/.adk-lens/notes.json`. Requires header `X-ADK-Lens: 1`. |
| `GET /api/notes` | The saved document, or `null`. |
| `POST /api/clear` | Forget all runs (keeps topologies, versions, notes). Requires header `X-ADK-Lens: 1`. |
| `POST /api/ingest` | Used by agent processes: `{"events": [...]}`. Requires header `X-ADK-Lens`. |
| `POST /api/shutdown` | Stops the hub (used by `adk-lens stop`). Requires header `X-ADK-Lens: 1`. |

## Events

Every event has: `seq` (int, increasing, set by the hub), `ts` (unix seconds, float), `type`, `app` (ADK app name), `pid`.
Events that belong to a run also have `run` (one user request = one run id) and `session`.

| `type` | Extra fields | Meaning in plain words |
|---|---|---|
| `topology` | `root`, `nodes`, `edges`, `source`, `version` (int, set by the hub: the version that is now current), `reverted` (`true` only when the app went back to a version that already existed) | The shape of the app. Sent when an app starts and again whenever it changes. |
| `run_start` | `user_message` (text), `parts`, `user`, `root_agent` | Someone sent a message. |
| `agent_start` | `agent` (name), `path`, `nested` (bool) | An agent takes the floor. |
| `agent_end` | `agent`, `duration_ms` | The agent is done. |
| `model_start` | `agent`, `model`, `call_id`, `system` (instruction text), `messages` (count), `last` (parts of the last message sent), `tools` (names offered) | The agent asks the model to think. |
| `model_end` | `agent`, `call_id`, `parts`, `text`, `calls` ([{name,args}]), `tokens_in`, `tokens_out`, `duration_ms`, `finish` | The model answered (text and/or tool requests). |
| `model_error` | `agent`, `call_id`, `error`, `error_type` | The model call failed. |
| `tool_start` | `agent`, `tool`, `call_id`, `args`, `agent_tool` (bool: the tool is another agent) | The agent uses a tool. |
| `tool_end` | `agent`, `tool`, `call_id`, `result`, `duration_ms` | The tool answered. |
| `tool_error` | `agent`, `tool`, `call_id`, `error`, `error_type` | The tool failed. |
| `event` | `author`, `parts`, `text`, `final` (bool), `partial` (bool), `state_delta` (object), `transfer_to` (agent name), `escalate` (bool), `artifacts` ([names]), `branch`, `path`, `output` | Anything ADK itself records: a message, a hand-off, a memory change. `final: true` and `author` not `user` = an answer shown to the user. `final` is only ever `true` on an event that carries something (`parts` not empty before any privacy stripping): the empty event ADK records when a request fails has `final: false` and an `error` field. |
| `agent_error` | `agent`, `error`, `error_type` | An agent crashed. |
| `run_end` | `duration_ms`; sometimes `interrupted: true` with `reason` | The request is finished. With `interrupted: true` it did not finish by itself: `reason: "cancelled"` = the program that asked stopped listening before the end (sent by the agent process); `reason: "process_gone"` = the agent process disappeared in the middle (killed, crashed), sent by the hub itself a few seconds later, without `duration_ms`. |
| `run_error` | `error`, `error_type`, `duration_ms` | The request failed. |

### How a run ends

Every `run_start` is followed, sooner or later, by exactly one `run_end` or `run_error` with the same `run`, and that
event is the last one of the run:

- normal end: `run_end`;
- the request raised an error: `run_error` (on every supported ADK version, 1.7.0 and later; on ADK 1.7 and 1.8 there
  is no `tool_error` before it, the failing tool only has its `tool_start`);
- the caller stopped reading: `run_end` (recent ADK versions) or `run_end` with `interrupted: true, reason: "cancelled"`;
- the agent process died: `run_end` with `interrupted: true, reason: "process_gone"`, added by the hub once the `pid`
  of the run's `run_start` no longer exists (checked every 3 s, confirmed on two checks in a row, so 3 to 6 s later).

A UI can therefore treat a run as "live" exactly until its `run_end` / `run_error`. Steps left open inside an ended run
(a `tool_start` or `model_start` without its end) are to be shown as stopped, not as running.

`parts` is a list of `{"kind": "text"|"thought", "text"}`, `{"kind": "call", "name", "id", "args"}`,
`{"kind": "result", "name", "id", "response"}`, `{"kind": "file", "mime", "size"}`.

All text is clipped (4000 chars), so values may end with `… (+N chars)`. Any field may be missing.

### Privacy switch (`ADK_LENS_CONTENT=0`)

Events sent with `ADK_LENS_CONTENT=0` carry `"content": false` and only these fields: `type`, `app`, `run`, `session`,
`agent`, `tool`, `model`, `call_id`, `ts`, `pid`, `duration_ms`, `tokens_in`, `tokens_out`, `messages`, `finish`,
`final`, `partial`, `transfer_to`, `escalate`, `author`, `root`, `root_agent`, `error_type`, `nested`, `agent_tool`,
`path`, `branch`, `event_id`, `state_keys`, `source`, `interrupted`, `reason`, plus `calls` reduced to `[{name}]` and
`tools` (names). No `text`, `parts`, `user_message`, `system`, `last`, `args`, `result`, `error`, `output`, `state_delta`.
In a `topology`, nodes keep only `id`, `name`, `kind`, `cls`, `parent`, `model`, `output_key`, `mode`,
`max_iterations`, `prefix` (no `description`, no `instruction`), and edges keep `from`, `to`, `kind`, `order`, `label`.

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

### Versions

The hub keeps up to 30 versions per app (saved in `~/.adk-lens/versions.json`). One entry of `versions["<app>"]`:

```json
{"v": 3, "ts": 1731000000.0, "seen": 1731000900.0, "hash": "31a171e6b8", "shape": "9c0d2e11aa",
 "current": true, "topology": {"app": "…", "root": "…", "nodes": [], "edges": []}}
```

- `v`: version number, never reused. The list is ordered by `v`.
- `ts`: when this version was first seen. `seen`: when it last became the current one.
- `hash`: fingerprint of everything on the map (structure, instructions, descriptions, models).
  Two versions of one app never share a `hash`.
- `shape`: fingerprint of the structure only (node `id`, `name`, `kind`, `parent`, and its guards when it has any; edge `from`, `to`, `kind`, `order`).
- `current`: `true` on exactly one version per app. **The current version is not always the last of the list**:
  use this flag (or `state.current["<app>"]`), not the position.
- `content: false` (optional): this version was recorded with the privacy switch, its topology has no texts.

What the UI receives when an app announces its shape:

| Situation | Versions list | `topology` event |
|---|---|---|
| Same as the current version | unchanged | none (except the first one after a hub start or a clear, with `version`) |
| New: the structure or a text changed | a new entry, `current: true` | `version: <new v>` |
| Back to an earlier version (same `hash`) | no new entry; that entry gets `current: true` and a fresh `seen` | `version: <that v>`, `reverted: true` |
| Sent with `ADK_LENS_CONTENT=0` | compared on `shape` only: no new entry if the structure is known (the texts already stored are kept); a new entry with `content: false` otherwise | as above; the event itself has no texts |
| First seen with the privacy switch, later without | the same entry is completed with its texts and a new `hash` (no new version) | `version: <same v>`, with the texts |

After a `topology` event with `version`, the full list is in `GET /api/state`.

Runtime names map to nodes like this: an agent event's `agent` equals a node `name` (agent names are unique in an app);
a tool event maps to node id `<agent id>::<tool name>`. The UI must create a node on the fly when an event names
an agent or tool that is not in the topology (toolsets, dynamic tools).

### Workflows (ADK 2 graphs)

Workflow steps that are plain functions do not produce `agent_start` / `agent_end`. Their activity is visible through
`event` items: `path` looks like `my_workflow@1/clean@1` (node names with a run counter after `@`), and `output` holds
what the step returned. The last segment of `path`, without `@n`, is the name of the node that just worked.

### Agents used as tools

When an agent is used as a tool, its steps are reported inside the parent run (same `run` id), between the parent's
`tool_start` (with `agent_tool: true`) and `tool_end`. Its `agent_start` has `nested: true`.

## Guards (the agent's own callbacks)

An agent node that has ADK callbacks of its own (`before_model_callback`, `after_tool_callback`, ...) carries
`guards`: a list of `{"when": "before_model", "name": "<function name>", "about": "<first docstring line>"}`.
Adding or removing one makes a new version. With `ADK_LENS_CONTENT=0` only `when` and `name` are sent.

What a guard did, as far as it can be seen from outside:

| Event | Fields | Meaning |
|---|---|---|
| `model_end` with `guarded: true` | `guard_when: "before_model"`, `text`, `parts` | A before-model callback answered in the model's place; the model was not called. |
| `guard` | `when: "after_tool"`, `agent`, `tool`, `call_id`, `result` | An after-tool callback changed the tool's result. `result` is what the agent received; the `tool_end` with the same `call_id` has what the tool gave. |

A before-tool callback that answers in the tool's place is not visible: ADK then calls neither the tool nor the
plugins' after-tool hook, so the board shows the call and the result the agent received.
