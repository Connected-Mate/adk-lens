"""End-to-end tests: a real ADK app (scripted model), a real hub, real HTTP."""

import asyncio
import http.client
import json
import os
import socket
import subprocess
import sys
import time

import pytest


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def hub(tmp_path_factory):
    port = _free_port()
    home = tmp_path_factory.mktemp("lenshome")
    os.environ["ADK_LENS_PORT"] = str(port)
    os.environ["ADK_LENS_HOME"] = str(home)
    os.environ["ADK_LENS_QUIET"] = "1"
    proc = subprocess.Popen([sys.executable, "-m", "adk_lens.hub", "--port", str(port)],
                            env={**os.environ})
    from adk_lens import transport

    deadline = time.time() + 10
    while time.time() < deadline and not transport.ping():
        time.sleep(0.1)
    assert transport.ping(), "hub did not start"
    yield port
    proc.terminate()
    proc.wait(5)


def _req(port, method, path, body=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request(method, path, body=json.dumps(body).encode() if body is not None else None,
                 headers={"Content-Type": "application/json", **(headers or {})})
    resp = conn.getresponse()
    raw = resp.read()
    conn.close()
    try:
        return resp.status, json.loads(raw)
    except Exception:
        return resp.status, raw


def _state(port):
    return _req(port, "GET", "/api/state")[1]


async def _ask(runner, text, app="trip_demo"):
    from google.genai import types

    session = await runner.session_service.create_session(app_name=app, user_id="t")
    out = []
    async for event in runner.run_async(
        user_id="t", session_id=session.id,
        new_message=types.Content(role="user", parts=[types.Part(text=text)]),
    ):
        parts = event.content.parts if event.content else []
        out.append((event.author, [p.text or (p.function_call and p.function_call.name) or
                                   (p.function_response and p.function_response.name) for p in parts]))
    return out


def _runner():
    from google.adk.runners import InMemoryRunner

    from adk_lens.demo.trip_demo import agent

    agent.PACE = 0
    return InMemoryRunner(agent=agent.root_agent, app_name="trip_demo")


def test_lens_changes_nothing_and_records_everything(hub):
    from google.adk import runners

    from adk_lens import autoload, transport
    from adk_lens.plugin import LensPlugin

    # 1. Without the lens.
    plain_runner = _runner()
    assert not any(isinstance(p, LensPlugin) for p in plain_runner.plugin_manager.plugins)
    plain = asyncio.run(_ask(plain_runner, "Plan a weekend trip to Marseille"))

    # 2. With the lens: same events, in the same order.
    assert autoload.install()
    assert autoload.install()  # twice is harmless
    assert getattr(runners.Runner.__init__, "_adk_lens", False)
    runner = _runner()
    assert sum(isinstance(p, LensPlugin) for p in runner.plugin_manager.plugins) == 1
    assert runner.app.plugins == []  # the user's App object is untouched
    watched = asyncio.run(_ask(runner, "Plan a weekend trip to Marseille"))
    assert watched == plain

    transport.flush(5)
    state = _state(hub)
    types_seen = [e["type"] for e in state["events"]]
    for expected in ("topology", "run_start", "agent_start", "model_start", "model_end",
                     "tool_start", "tool_end", "event", "agent_end", "run_end"):
        assert expected in types_seen, expected
    topo = state["apps"]["trip_demo"]
    kinds = {n["name"]: n["kind"] for n in topo["nodes"]}
    assert kinds["concierge"] == "llm" and kinds["trip_planner"] == "sequential"
    assert kinds["search_places"] == "tool"
    assert {"from": "trip_planner", "to": "researcher", "kind": "then", "order": 1} in topo["edges"]
    assert any(e.get("transfer_to") == "trip_planner" for e in state["events"])
    assert any(e.get("state_keys") == ["plan"] for e in state["events"])
    assert len(state["versions"]["trip_demo"]) == 1
    runs = {e["run"] for e in state["events"] if e["type"] == "run_start"}
    assert len(runs) == 1


def test_tool_error_is_reported_and_still_raised(hub):
    from adk_lens import autoload, transport

    autoload.install()
    with pytest.raises(ValueError):
        asyncio.run(_ask(_runner(), "weather in Atlantis"))
    transport.flush(5)
    types_seen = [e["type"] for e in _state(hub)["events"]]
    assert "tool_error" in types_seen and "run_error" in types_seen


def test_a_broken_lens_never_breaks_the_agent(hub, monkeypatch):
    from adk_lens import autoload, plugin

    autoload.install()

    def boom(*a, **k):
        raise RuntimeError("lens is broken")

    monkeypatch.setattr(plugin, "emit", boom)
    monkeypatch.setattr(plugin, "parts_of", boom)
    out = asyncio.run(_ask(_runner(), "weather in Lisbon"))
    assert out[-1][1] == ["Lisbon: sunny, 15 to 24 °C."]


def test_explicit_plugin_is_not_added_twice(hub):
    from google.adk.apps import App
    from google.adk.runners import InMemoryRunner

    from adk_lens import LensPlugin, autoload
    from adk_lens.demo.trip_demo import agent

    autoload.install()
    app = App(name="trip_demo", root_agent=agent.root_agent, plugins=[LensPlugin()])
    runner = InMemoryRunner(app=app)
    assert sum(isinstance(p, LensPlugin) for p in runner.plugin_manager.plugins) == 1


def test_content_can_be_kept_out(hub, monkeypatch):
    from adk_lens import autoload, transport

    autoload.install()
    _req(hub, "POST", "/api/clear", {}, {"X-ADK-Lens": "1"})
    monkeypatch.setenv("ADK_LENS_CONTENT", "0")
    asyncio.run(_ask(_runner(), "weather in Lisbon"))
    transport.flush(5)
    dump = json.dumps([e for e in _state(hub)["events"] if e["type"] != "topology"])
    assert "Lisbon" not in dump and "sunny" not in dump
    assert "get_weather" in dump  # names and structure stay


def test_hub_guards(hub):
    # writes need the header
    assert _req(hub, "POST", "/api/ingest", {"events": []})[0] == 403
    assert _req(hub, "PUT", "/api/notes", {"items": []})[0] == 403
    # a web page from another site cannot write, even with the header
    assert _req(hub, "POST", "/api/clear", {}, {"X-ADK-Lens": "1", "Origin": "https://evil.example"})[0] == 403
    # requests under a foreign host name are refused (DNS rebinding)
    assert _req(hub, "GET", "/api/state", headers={"Host": "evil.example"})[0] == 403
    # no path escape from the static folder
    assert _req(hub, "GET", "/../hub.py")[0] == 404
    assert _req(hub, "GET", "/%2e%2e/hub.py")[0] == 404
    # bad payloads are refused, junk events ignored
    assert _req(hub, "POST", "/api/ingest", {"nope": 1}, {"X-ADK-Lens": "1"})[0] == 400
    before = _state(hub)["seq"]
    assert _req(hub, "POST", "/api/ingest", {"events": ["junk", {"no_type": 1}]}, {"X-ADK-Lens": "1"})[0] == 200
    assert _state(hub)["seq"] == before


def test_notes_roundtrip_and_cli_prompt(hub):
    from adk_lens import cli

    notes = {"items": [{"kind": "question", "text": "Why two model calls?", "target": {"name": "weather_agent"}}]}
    assert _req(hub, "PUT", "/api/notes", notes, {"X-ADK-Lens": "1"})[0] == 200
    assert _req(hub, "GET", "/api/notes")[1] == notes
    prompt = cli.notes_as_prompt(notes)
    assert "Why two model calls?" in prompt and "weather_agent" in prompt
    assert cli.notes_as_prompt({"prompt": "ready made", "items": []}) == "ready made"
    assert cli.notes_as_prompt(None) == ""


def test_stream_replays_and_follows(hub):
    conn = http.client.HTTPConnection("127.0.0.1", hub, timeout=5)
    seq = _state(hub)["seq"]
    conn.request("GET", f"/api/stream?since={seq}")
    resp = conn.getresponse()
    assert resp.status == 200 and resp.getheader("Content-Type").startswith("text/event-stream")
    _req(hub, "POST", "/api/ingest", {"events": [{"type": "run_start", "app": "x", "run": "r1"}]}, {"X-ADK-Lens": "1"})
    data = b""
    deadline = time.time() + 5
    while b'"run": "r1"' not in data and time.time() < deadline:
        data += resp.fp.readline()
    conn.close()
    assert b'"run": "r1"' in data


def test_new_shape_makes_a_new_version(hub):
    topo = {"type": "topology", "app": "vapp", "root": "a", "nodes": [{"id": "a", "name": "a", "kind": "llm"}], "edges": []}
    h = {"X-ADK-Lens": "1"}
    _req(hub, "POST", "/api/ingest", {"events": [dict(topo)]}, h)
    _req(hub, "POST", "/api/ingest", {"events": [dict(topo)]}, h)  # same shape: no new version
    changed = dict(topo, nodes=[{"id": "a", "name": "a", "kind": "llm", "instruction": "be brief"}])
    _req(hub, "POST", "/api/ingest", {"events": [changed]}, h)
    versions = _state(hub)["versions"]["vapp"]
    assert [v["v"] for v in versions] == [1, 2]


def test_serialize_is_bounded():
    from adk_lens.serialize import safe

    class Odd:
        def __repr__(self):
            raise RuntimeError("no repr")

    big = {"k" + str(i): "x" * 10000 for i in range(100)}
    out = safe(big)
    assert len(json.dumps(out)) < 250000
    assert isinstance(safe(Odd()), str)
    loop = []
    loop.append(loop)
    json.dumps(safe(loop))
