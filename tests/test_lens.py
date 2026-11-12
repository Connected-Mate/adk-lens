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


def _adk_has(hook: str) -> bool:
    """Older ADK versions do not have every plugin hook (the suite also runs on ADK 1.7)."""
    from google.adk.plugins.base_plugin import BasePlugin

    return hasattr(BasePlugin, hook)


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
    # Anything still waiting to be sent would bring a board back when Python exits: send it,
    # then mark this (temporary) home as stopped so no board outlives the tests.
    transport.flush(2)
    transport.mark_stopped()
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
    if getattr(runner, "app", None) is not None:
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
    assert "run_error" in types_seen
    if _adk_has("on_tool_error_callback"):
        assert "tool_error" in types_seen


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
    pytest.importorskip("google.adk.apps")  # ADK 1.14 and later
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


# ---------------------------------------------------------------------------
# A second, private hub for tests that need an empty board or a special port.
# ---------------------------------------------------------------------------
@pytest.fixture
def fresh(hub, tmp_path, monkeypatch):
    """Point the lens at a new port and a new home for one test. Yields (port, home)."""
    port = _free_port()
    monkeypatch.setenv("ADK_LENS_PORT", str(port))
    monkeypatch.setenv("ADK_LENS_HOME", str(tmp_path))
    yield port, tmp_path
    from adk_lens import transport

    if transport.ping():
        _req(port, "POST", "/api/shutdown", {}, {"X-ADK-Lens": "1"})
        deadline = time.time() + 5
        while transport.port_busy() and time.time() < deadline:
            time.sleep(0.05)


def _wait(condition, seconds=10.0):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if condition():
            return True
        time.sleep(0.1)
    return bool(condition())


def _run_events(port, run=None):
    events = _state(port)["events"]
    if run is None:
        run = [e["run"] for e in events if e["type"] == "run_start"][-1]
    return [e for e in events if e.get("run") == run]


# -- a request always ends ---------------------------------------------------
def test_failed_run_is_closed_even_when_adk_has_no_run_error_hook(hub, monkeypatch):
    """ADK before 2.5 never tells plugins that a request failed: the lens notices by itself."""
    from adk_lens import autoload, transport
    from adk_lens.plugin import LensPlugin

    autoload.install()

    async def silent(self, **kwargs):
        return None

    monkeypatch.setattr(LensPlugin, "on_run_error_callback", silent)
    monkeypatch.setattr(LensPlugin, "after_run_callback", silent)
    with pytest.raises(ValueError, match="Atlantis"):  # the user's exception, unchanged
        asyncio.run(_ask(_runner(), "weather in Atlantis"))
    transport.flush(5)
    events = _run_events(hub)
    assert events[0]["type"] == "run_start"
    assert events[-1]["type"] == "run_error"
    assert events[-1]["error_type"] == "ValueError" and "Atlantis" in events[-1]["error"]
    assert [e["type"] for e in events].count("run_error") == 1

    # ...and a request that works is closed exactly once too.
    asyncio.run(_ask(_runner(), "weather in Lisbon"))
    transport.flush(5)
    kinds = [e["type"] for e in _run_events(hub)]
    assert kinds[-1] == "run_end" and kinds.count("run_end") == 1 and "run_error" not in kinds


def test_run_end_is_reported_once_with_the_hooks(hub):
    from adk_lens import autoload, transport

    autoload.install()
    with pytest.raises(ValueError):
        asyncio.run(_ask(_runner(), "weather in Atlantis"))
    transport.flush(5)
    events = _run_events(hub)
    kinds = [e["type"] for e in events]
    assert kinds.count("run_error") + kinds.count("run_end") == 1
    # ADK records an empty event when a request fails: it must not look like an answer.
    assert not [e for e in events if e["type"] == "event" and e.get("final") and not e.get("parts")]


def test_a_caller_who_stops_reading_closes_the_run(hub, monkeypatch):
    from google.genai import types

    from adk_lens import autoload, transport
    from adk_lens.plugin import LensPlugin

    autoload.install()

    async def stop_early():
        runner = _runner()
        session = await runner.session_service.create_session(app_name="trip_demo", user_id="t")
        stream = runner.run_async(user_id="t", session_id=session.id,
                                  new_message=types.Content(role="user", parts=[types.Part(text="weather in Lisbon")]))
        async for _ in stream:
            break
        await stream.aclose()

    # Recent ADK versions report the end themselves when the caller walks away...
    asyncio.run(stop_early())
    transport.flush(5)
    kinds = [e["type"] for e in _run_events(hub)]
    assert kinds[-1] == "run_end" and kinds.count("run_end") == 1

    # ...and when ADK says nothing, the lens closes the request and says why.
    async def silent(self, **kwargs):
        return None

    monkeypatch.setattr(LensPlugin, "after_run_callback", silent)
    asyncio.run(stop_early())
    transport.flush(5)
    last = _run_events(hub)[-1]
    assert last["type"] == "run_end" and last.get("interrupted") is True and last.get("reason") == "cancelled"


def test_old_adk_contexts_still_give_the_app_name():
    """ADK 1.7: callback contexts have no `session`; it sits on the private invocation context."""
    from types import SimpleNamespace as NS

    from adk_lens.plugin import LensPlugin

    plugin = LensPlugin()
    session = NS(app_name="my_app", id="s1")
    old_style = NS(invocation_id="i1", _invocation_context=NS(session=session))
    assert plugin._ctx_ids(old_style) == ("my_app", "s1", "i1")
    plugin._open["i2"] = ("my_app", "s2")
    assert plugin._ctx_ids(NS(invocation_id="i2")) == ("my_app", "s2", "i2")


def test_run_of_a_dead_process_is_closed_by_the_hub(hub):
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait()
    h = {"X-ADK-Lens": "1"}
    _req(hub, "POST", "/api/ingest", {"events": [
        {"type": "run_start", "app": "ghost", "run": "dead-run", "session": "s", "pid": child.pid},
        {"type": "run_start", "app": "ghost", "run": "alive-run", "session": "s", "pid": os.getpid()},
    ]}, h)

    def closed():
        return [e for e in _state(hub)["events"] if e.get("run") == "dead-run" and e["type"] == "run_end"]

    assert _wait(closed, 12), "the hub did not close the run of a process that is gone"
    end = closed()[0]
    assert end["interrupted"] is True and end["reason"] == "process_gone" and end["app"] == "ghost"
    assert len(closed()) == 1
    assert not [e for e in _state(hub)["events"] if e.get("run") == "alive-run" and e["type"] == "run_end"]
    _req(hub, "POST", "/api/ingest", {"events": [{"type": "run_end", "app": "ghost", "run": "alive-run"}]}, h)


# -- stop stays stopped --------------------------------------------------------
def test_stop_is_not_undone_by_a_running_agent(fresh, capsys):
    from adk_lens import cli, transport

    port, home = fresh
    sender = transport._Sender()
    sender.emit({"type": "run_start", "app": "x", "run": "r1"})
    sender.flush(8)
    assert transport.ping(), "a running agent starts the board by itself"

    assert cli.main(["stop"]) == 0
    assert (home / "stopped").exists()
    assert _wait(lambda: not transport.port_busy(), 5)

    # The agent program is still running and keeps sending: the board must stay down.
    for i in range(3):
        sender._next_try = 0.0
        sender.emit({"type": "event", "app": "x", "run": "r1", "text": str(i)})
        sender.flush(1)
    time.sleep(0.5)
    assert not transport.port_busy() and transport.ping() is None
    assert not sender._queue  # nothing is piled up for later
    assert cli.main(["status"]) == 0
    assert "stopped" in capsys.readouterr().err

    # Any explicit start lifts the stop.
    assert cli.main(["open", "--no-open"]) == 0
    assert transport.ping() and not (home / "stopped").exists()
    sender._next_try = 0.0
    sender.emit({"type": "run_end", "app": "x", "run": "r1"})
    sender.flush(5)
    assert [e["type"] for e in _state(port)["events"]] == ["run_end"]


# -- a port that belongs to another program -------------------------------------
@pytest.fixture
def foreign_port(fresh):
    """Some other web server is already listening on the lens port."""
    from http.server import BaseHTTPRequestHandler, HTTPServer
    import threading

    class Other(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", "5")
            self.end_headers()
            self.wfile.write(b"hello")

        do_POST = do_GET

        def log_message(self, *a):
            pass

    server = HTTPServer(("127.0.0.1", fresh[0]), Other)
    server.handle_error = lambda *a: None
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield fresh[0]
    server.shutdown()
    server.server_close()


def test_port_taken_by_another_program(foreign_port, capsys, monkeypatch):
    from adk_lens import cli, transport

    monkeypatch.delenv("ADK_LENS_QUIET", raising=False)
    monkeypatch.setattr(transport, "_port_said", False)
    assert transport.port_taken_by_other()

    began = time.monotonic()
    assert transport.start_hub() is False
    assert time.monotonic() - began < 1.0, "no 4-second wait when the port is someone else's"

    sender = transport._Sender()
    sender.emit({"type": "run_start", "app": "x", "run": "r1"})
    sender.flush(2)
    assert sender._off and not sender._queue
    sender.emit({"type": "event", "app": "x", "run": "r1"})  # dropped at once from now on
    assert not sender._queue
    began = time.monotonic()
    sender._exit_flush()
    assert time.monotonic() - began < 0.3
    said = capsys.readouterr().err
    assert said.count(f"port {foreign_port}") == 1 and "ADK_LENS_PORT=" in said  # said once, with the fix

    monkeypatch.setattr(transport, "_port_said", False)
    assert cli.main(["open", "--no-open"]) == 1
    said = capsys.readouterr().err
    assert f"port {foreign_port} is used by another program" in said and f"ADK_LENS_PORT={foreign_port + 1}" in said


def test_exit_is_never_held_back(foreign_port):
    """A whole Python program that emits events, with the port taken: it ends at once."""
    code = "import time; t=time.monotonic(); from adk_lens import transport\n" \
           "for i in range(50): transport.emit({'type': 'event', 'app': 'x', 'run': 'r'})\n" \
           "import atexit, sys; atexit.register(lambda: sys.stdout.write('ok'))"
    began = time.monotonic()
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=20,
                         env={**os.environ, "ADK_LENS": "0"})
    assert out.stdout == "ok"
    assert time.monotonic() - began < 1.5, "interpreter start + exit, without the old 1-4 s wait"


def test_exit_without_any_board_costs_almost_nothing(fresh):
    """Nothing listens and the board was stopped: leaving must not start or wait for anything."""
    from adk_lens import transport

    transport.mark_stopped()
    sender = transport._Sender()
    sender.emit({"type": "event", "app": "x", "run": "r"})
    began = time.monotonic()
    sender._exit_flush()
    assert time.monotonic() - began < 0.5
    assert not transport.port_busy()


# -- versions ---------------------------------------------------------------------
def _topo(app, tools, **node_extra):
    nodes = [{"id": "a", "name": "a", "kind": "llm", "parent": None, **node_extra}]
    edges = []
    for tool in tools:
        nodes.append({"id": f"a::{tool}", "name": tool, "kind": "tool", "parent": "a", "description": f"doc of {tool}"})
        edges.append({"from": "a", "to": f"a::{tool}", "kind": "uses_tool"})
    return {"type": "topology", "app": app, "root": "a", "nodes": nodes, "edges": edges}


def test_going_back_to_an_earlier_shape_reuses_its_version(hub):
    from adk_lens.serialize import redact

    h = {"X-ADK-Lens": "1"}
    one, two = _topo("back", ["t1"], instruction="be brief"), _topo("back", ["t1", "t2"], instruction="be brief")
    for topo in (one, two, one):
        _req(hub, "POST", "/api/ingest", {"events": [dict(topo)]}, h)
    state = _state(hub)
    versions = state["versions"]["back"]
    assert [v["v"] for v in versions] == [1, 2], "no duplicate of version 1"
    assert len({v["hash"] for v in versions}) == 2
    assert [v["current"] for v in versions] == [True, False] and state["current"]["back"] == 1
    assert state["apps"]["back"]["nodes"] == one["nodes"]
    shown = [e for e in state["events"] if e["type"] == "topology" and e["app"] == "back"]
    assert [(e["version"], e.get("reverted", False)) for e in shown] == [(1, False), (2, False), (1, True)]

    # The privacy switch strips instructions and descriptions: same structure, so no new version.
    _req(hub, "POST", "/api/ingest", {"events": [redact(dict(one))]}, h)
    state = _state(hub)
    assert [v["v"] for v in state["versions"]["back"]] == [1, 2] and state["current"]["back"] == 1
    assert state["apps"]["back"]["nodes"][0]["instruction"] == "be brief"  # what was known is kept

    # A real change of wording is still a new version, a real change of structure too (even stripped).
    _req(hub, "POST", "/api/ingest", {"events": [_topo("back", ["t1"], instruction="be long")]}, h)
    _req(hub, "POST", "/api/ingest", {"events": [redact(_topo("back", ["t9"]))]}, h)
    state = _state(hub)
    assert [v["v"] for v in state["versions"]["back"]] == [1, 2, 3, 4] and state["current"]["back"] == 4


def test_private_first_then_normal_is_one_version(hub):
    from adk_lens.serialize import redact

    h = {"X-ADK-Lens": "1"}
    full = _topo("priv", ["t1"], instruction="be brief")
    _req(hub, "POST", "/api/ingest", {"events": [redact(dict(full))]}, h)
    _req(hub, "POST", "/api/ingest", {"events": [dict(full)]}, h)
    state = _state(hub)
    assert [v["v"] for v in state["versions"]["priv"]] == [1]
    assert state["apps"]["priv"]["nodes"][0]["instruction"] == "be brief"


# -- privacy switch -----------------------------------------------------------------
def test_content_off_sends_no_text_at_all(fresh, monkeypatch):
    """Dump everything a fresh board holds after a run with ADK_LENS_CONTENT=0 and search it."""
    from adk_lens import autoload, transport
    from adk_lens.demo.trip_demo import agent

    port, _ = fresh
    autoload.install()
    monkeypatch.setenv("ADK_LENS_CONTENT", "0")
    asyncio.run(_ask(_runner(), "weather in Lisbon"))
    asyncio.run(_ask(_runner(), "Plan a weekend trip to Marseille"))
    with pytest.raises(ValueError):
        asyncio.run(_ask(_runner(), "weather in Atlantis"))
    transport.flush(5)
    state = _state(port)
    expected = {"topology", "run_start", "model_start", "model_end", "tool_start", "tool_end",
                "event", "run_end", "run_error"}
    if _adk_has("on_tool_error_callback"):
        expected.add("tool_error")
    assert expected <= {e["type"] for e in state["events"]}
    dump = json.dumps(state)
    secrets = ["Lisbon", "Marseille", "Atlantis", "sunny", "harbour", "weekend", "Unknown city"]
    for a in (agent.root_agent, agent.weather_agent, agent.researcher, agent.writer, agent.trip_planner):
        secrets += [a.description, getattr(a, "instruction", None)]
    secrets += [agent.get_weather.__doc__, agent.search_places.__doc__]
    for secret in filter(None, secrets):
        assert secret not in dump, secret
    for key in ("description", "instruction", "system", "text", "user_message", "args", "result", "parts", "error", "last"):
        assert f'"{key}":' not in dump, key
    # names, structure and timings stay
    for name in ("concierge", "weather_agent", "get_weather", "search_places", "scripted-demo-model", "duration_ms"):
        assert name in dump, name
    assert all(e.get("content") is False for e in state["events"])
    assert len(state["versions"]["trip_demo"]) == 1

    # Switching content back on, same app: still one version (now with its texts).
    monkeypatch.delenv("ADK_LENS_CONTENT")
    asyncio.run(_ask(_runner(), "weather in Lisbon"))
    transport.flush(5)
    state = _state(port)
    assert len(state["versions"]["trip_demo"]) == 1
    assert "Answers weather questions" in json.dumps(state["apps"])


# -- command line ---------------------------------------------------------------------
def test_unknown_command_gets_our_own_help(capsys):
    from adk_lens import cli

    assert cli.main(["bogus-command"]) == 2
    said = capsys.readouterr().err
    assert "unknown command 'bogus-command'" in said and "adk-lens demo" in said
    assert "adk --help" not in said


def test_demo_answers_all_three_questions():
    """The whole demo script, on whatever ADK is installed (CI also runs it on 2.0.0, where
    hand-offs next to a SequentialAgent used to break the two weather questions)."""
    runner = _runner()
    weather = asyncio.run(_ask(runner, "What's the weather in Lisbon this weekend?"))
    assert ("weather_agent", ["Lisbon: sunny, 15 to 24 °C."]) in weather
    trip = asyncio.run(_ask(runner, "Plan a weekend trip to Marseille for me."))
    assert any(author == "writer" and "Marseille" in (texts[0] or "") for author, texts in trip)
    with pytest.raises(ValueError, match="Atlantis"):
        asyncio.run(_ask(runner, "And what's the weather in Atlantis?"))


SHORT_SCRIPT = """
import asyncio, sys
from google.adk.runners import InMemoryRunner
from google.genai import types
from adk_lens.demo.trip_demo import agent
agent.PACE = 0
async def main():
    runner = InMemoryRunner(agent=agent.root_agent, app_name="short_script")
    session = await runner.session_service.create_session(app_name="short_script", user_id="t")
    try:
        async for _ in runner.run_async(user_id="t", session_id=session.id,
                new_message=types.Content(role="user", parts=[types.Part(text=sys.argv[1])])):
            pass
    except ValueError:
        pass
asyncio.run(main())
"""


@pytest.mark.parametrize("question, ending", [("weather in Atlantis", "run_error"), ("weather in Lisbon", "run_end")])
def test_last_request_of_a_short_script_keeps_its_real_ending(hub, question, ending):
    """A script that exits right after its last request: the ending must reach the board,
    not be replaced later by "interrupted"."""
    for _ in range(4):
        _req(hub, "POST", "/api/clear", {}, {"X-ADK-Lens": "1"})
        subprocess.run([sys.executable, "-c", SHORT_SCRIPT, question], timeout=30, check=True,
                       capture_output=True, env={**os.environ, "ADK_LENS": "1", "ADK_LENS_QUIET": "1"})
        ends = [e for e in _state(hub)["events"]
                if e["type"] in ("run_end", "run_error") and e.get("app") == "short_script"]
        assert [e["type"] for e in ends] == [ending] and not ends[0].get("interrupted"), ends


def test_clear_does_not_orphan_a_running_request(hub):
    """Cleared while a request runs, then its program dies: the request is still closed."""
    h = {"X-ADK-Lens": "1"}
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        _req(hub, "POST", "/api/ingest", {"events": [
            {"type": "run_start", "app": "orphan", "run": "orphan-1", "session": "s", "pid": proc.pid}]}, h)
        _req(hub, "POST", "/api/clear", {}, h)
    finally:
        proc.kill()
        proc.wait(5)
    assert _wait(lambda: any(e["type"] == "run_end" and e.get("run") == "orphan-1" and e.get("interrupted")
                             for e in _state(hub)["events"]), 20)


# -- the hard demo (rail desk) ----------------------------------------------------------
RAIL_AGENTS = {"station_desk", "timetable_agent", "site_reader", "disruption_watch", "disruption_scan",
               "delay_monitor", "notice_monitor", "briefing_writer", "rebooking_flow", "alternatives_finder",
               "seat_hunt", "seat_picker", "seat_checker", "notifier", "announcer"}


def _local(url):
    import urllib.request

    return urllib.request.build_opener(urllib.request.ProxyHandler({})).open(url, timeout=5)


def test_rail_desk_services_are_local_and_stop():
    """The web site and the mail sink of the hard demo: real HTTP and SMTP, on 127.0.0.1 only."""
    import smtplib

    from adk_lens.demo.rail_desk import services

    with pytest.raises(RuntimeError):
        services.current()  # importing the demo started nothing
    with services.running() as live:
        assert services.current() is live
        assert "Lost property" in _local(live.site.url).read().decode()
        with pytest.raises(Exception):
            _local(live.site.url + "nope.html")
        with smtplib.SMTP("127.0.0.1", live.mail.port, local_hostname="localhost", timeout=5) as smtp:
            smtp.sendmail("desk@example.com", ["a@example.com"], "Subject: hi\r\n\r\n.starts with a dot\r\nbye")
            for bad in ("t.brandt@example.com", "someone@elsewhere.test"):
                with pytest.raises(smtplib.SMTPRecipientsRefused) as refused:
                    smtplib.SMTP.sendmail(smtp, "desk@example.com", [bad], "Subject: hi\r\n\r\nx")
                assert refused.value.recipients[bad][0] == 550
        assert [m["to"] for m in live.mail.messages] == [["a@example.com"]]
        assert ".starts with a dot" in live.mail.messages[0]["data"]
        assert live.mail.refused == ["t.brandt@example.com", "someone@elsewhere.test"]
        assert live.site.hits == ["/", "/nope.html"]
        ports = [live.site.port, live.mail.port]
    with pytest.raises(RuntimeError):
        services.current()
    for port in ports:  # both stopped listening
        with socket.socket() as s:
            assert s.connect_ex(("127.0.0.1", port)) != 0


def test_hard_demo_plays_every_request_and_the_board_sees_it_all(fresh):
    """The whole rail desk script, with the lens on, on whatever ADK is installed."""
    from adk_lens import autoload, demo, transport
    from adk_lens.demo.rail_desk import agent, services

    port, _ = fresh
    autoload.install()
    agent.PACE = 0
    out = asyncio.run(demo.play_hard(pause=0))
    with pytest.raises(RuntimeError):
        services.current()  # the web site and the mail sink stopped with the demo

    # 1. Each request ends as the script says.
    asked = out["requests"]
    assert [r["question"] for r in asked] == [q for q, _ in demo.HARD_REQUESTS] and len(asked) == 8
    said = [" ".join(text for _, text in r["answers"]) for r in asked]
    assert [bool(r["error"]) for r in asked] == [False] * 7 + [True]
    assert "6605 at 08:10" in said[0] and "6609 at 09:10" in said[0]
    assert "12 minutes late" in said[1]
    assert asked[2]["session"] == asked[1]["session"], "the follow-up is asked in the same conversation"
    assert "Train 6607 leaves from platform 2" in said[2]  # no train number in the question: memory
    assert len({r["session"] for r in asked}) == 7
    assert asked[3]["answers"][-1][0] == "station_desk"
    assert "next to platform 1" in said[3] and "Sunday: 09:00 to 17:00" in said[3]
    assert asked[4]["answers"][-1][0] == "briefing_writer"
    assert "6607 is 12 min late" in said[4] and "signallers' walkout" in said[4]
    assert "Train 6614 is full." in said[5] and "Train 6616 is full." in said[5]
    assert asked[5]["answers"][-1] == ("notifier", "You are rebooked: train 6618 at 10:40, coach 3, seat 14C. "
                                       "A confirmation was e-mailed to maya.ortiz@example.com.")
    assert "2 e-mails delivered" in said[6] and "550 mailbox unknown" in said[6] and "note for Tom Brandt" in said[6]
    assert asked[7]["error"].startswith("TimetableUnavailable") and not asked[7]["answers"]

    # 2. Real work: pages fetched over HTTP, mail sent over SMTP (three accepted in all, one refused).
    assert out["pages"] == ["/", "/lost-property.html", "/opening-hours.html"]
    assert [m["to"] for m in out["mail"]] == [["maya.ortiz@example.com"], ["ines.carver@example.com"],
                                              ["lena.okoye@example.com"]]
    assert "Subject: Platform change for train 6620" in out["mail"][1]["data"] and "platform 7" in out["mail"][2]["data"]
    assert len([m for m in out["mail"] if "Platform change" in m["data"]]) == 2 and out["refused"] == ["t.brandt@example.com"]

    # 3. The board: one app, one shape, with every kind of structure.
    transport.flush(5)
    state = _state(port)
    assert list(state["apps"]) == ["rail_desk"] and len(state["versions"]["rail_desk"]) == 1
    topo = state["apps"]["rail_desk"]
    kinds = {n["name"]: n["kind"] for n in topo["nodes"]}
    assert topo["root"] == "station_desk" and len(topo["nodes"]) == 28
    assert {name for name, kind in kinds.items() if kind != "tool"} == RAIL_AGENTS
    assert (kinds["disruption_watch"], kinds["disruption_scan"], kinds["seat_hunt"]) == ("sequential", "parallel", "loop")
    assert next(n for n in topo["nodes"] if n["name"] == "seat_hunt")["max_iterations"] == 5
    links = {(e["from"], e["to"], e["kind"]) for e in topo["edges"]}
    assert {("station_desk", "site_reader", "uses_agent"), ("station_desk", "rebooking_flow", "delegate"),
            ("disruption_scan", "delay_monitor", "together"), ("disruption_scan", "notice_monitor", "together"),
            ("seat_hunt", "seat_picker", "repeat"), ("seat_hunt", "seat_checker", "repeat"),
            ("rebooking_flow", "notifier", "then"), ("site_reader", "site_reader::fetch_page", "uses_tool")} <= links

    # 4. Every request is opened once and closed once; nothing is recorded outside a request.
    events = [e for e in state["events"] if e["type"] != "topology"]
    assert {e["app"] for e in events} == {"rail_desk"}
    runs = [e["run"] for e in events if e["type"] == "run_start"]
    endings = [e for e in events if e["type"] in ("run_end", "run_error")]
    assert len(runs) == 8 and [e["run"] for e in endings] == runs
    assert [e["type"] for e in endings] == ["run_end"] * 7 + ["run_error"]
    assert not any(e.get("interrupted") for e in endings) and "Saltmarsh" in endings[-1]["error"]
    assert {e["run"] for e in events} == set(runs)

    def of(run, kind):
        return [e for e in events if e["run"] == runs[run] and e["type"] == kind]

    assert {e["agent"] for e in events if e["type"] == "agent_start"} == RAIL_AGENTS
    tools = [e["tool"] for e in events if e["type"] == "tool_start"]
    assert {t: tools.count(t) for t in ("search_trains", "get_live_status", "site_reader", "fetch_page", "list_delays",
                                        "list_notices", "try_hold_seat", "exit_loop", "send_email", "list_passengers",
                                        "leave_desk_note")} == {
        "search_trains": 3, "get_live_status": 3, "site_reader": 1, "fetch_page": 3, "list_delays": 1,
        "list_notices": 1, "try_hold_seat": 3, "exit_loop": 1, "send_email": 4, "list_passengers": 1,
        "leave_desk_note": 1}
    assert len([e for e in events if e["type"] == "model_start"]) == len([e for e in events if e["type"] == "model_end"]) == 41
    # every tool call is closed (old ADK versions say nothing about the one that raises)
    assert len([e for e in events if e["type"] == "tool_end"]) == len(tools) - 1
    # the agent used as a tool works inside the request that called it
    assert [e["tool"] for e in of(3, "tool_start")] == ["site_reader", "fetch_page", "fetch_page", "fetch_page"]
    assert any(e["agent"] == "site_reader" and e.get("nested") for e in of(3, "agent_start"))
    # several tools asked in one model turn, and their results stay in the request
    assert sorted(len(e["calls"]) for e in events if e["type"] == "model_end" and len(e["calls"]) > 1) == [2, 3]
    assert any(len([p for p in e["parts"] if p.get("kind") == "result"]) == 3 for e in of(6, "event"))
    # memory written by tools and agents, the loop ended by exit_loop, both branches of the parallel step
    keys = {k for e in events if e["type"] == "event" for k in e.get("state_keys", [])}
    assert {"last_train", "delays", "notices", "briefing", "alternatives", "seats_tried", "seat_status",
            "held_seat", "confirmation", "desk_notes"} <= keys
    assert any(e.get("escalate") for e in of(5, "event"))
    assert [e["agent"] for e in of(5, "agent_start")].count("seat_picker") == 3
    assert {"delay_monitor", "notice_monitor"} <= {e["agent"] for e in of(4, "agent_start")}
    if _adk_has("on_tool_error_callback"):
        assert [e["tool"] for e in of(7, "tool_error")] == ["search_trains"]


def test_hard_demo_stops_its_services_when_interrupted():
    from adk_lens import demo
    from adk_lens.demo.rail_desk import agent, services

    agent.PACE = 0

    async def interrupted():
        task = asyncio.ensure_future(demo.play_hard(pause=30))
        for _ in range(200):  # the first request is played, then the demo waits
            await asyncio.sleep(0.05)
            if services._current is not None and services._current.site.port:
                break
        live = services._current
        ports = [live.site.port, live.mail.port]
        await asyncio.sleep(0.3)
        task.cancel()  # what Ctrl+C does to the demo
        with pytest.raises(asyncio.CancelledError):
            await task
        return ports

    ports = asyncio.run(interrupted())
    assert services._current is None
    for port in ports:
        with socket.socket() as s:
            assert s.connect_ex(("127.0.0.1", port)) != 0


def test_demo_command_picks_the_right_demo(fresh, monkeypatch, capsys):
    from adk_lens import cli, demo

    played = []

    async def simple():
        played.append("simple")

    async def hard():
        played.append("hard")

    monkeypatch.setattr(demo, "play", simple)
    monkeypatch.setattr(demo, "play_hard", hard)
    assert cli.main(["demo", "--once", "--no-open"]) == 0
    assert cli.main(["demo", "hard", "--once", "--no-open"]) == 0
    assert cli.main(["demo", "--once", "hard", "--no-open"]) == 0
    assert played == ["simple", "hard", "hard"]
    assert "rail desk" in capsys.readouterr().err
    assert "adk-lens demo hard" in cli.HELP


def test_agent_used_as_a_tool_on_old_adk_stays_inside_its_request(monkeypatch):
    """Before ADK 2.2 an agent used as a tool runs in a plain Runner (1.x: under its own name).
    Its work belongs to the request that called it, and its small shape must not replace the app's."""
    from types import SimpleNamespace as NS

    from adk_lens import autoload, plugin
    from adk_lens.plugin import LensPlugin

    sent = []
    monkeypatch.setattr(plugin, "emit", sent.append)
    lens = LensPlugin()
    monkeypatch.setattr(plugin, "lens_plugin", lens)
    reader = NS(name="reader", sub_agents=[], tools=[])
    outer = NS(invocation_id="top", session=NS(app_name="desk_app", id="s1"), agent=NS(name="desk"), user_id="u",
               user_content=None)
    tool_ctx = NS(invocation_id="top", session=outer.session, agent_name="desk", function_call_id="c1")

    async def scenario():
        await lens.before_run_callback(invocation_context=outer)
        assert not lens.called_as_tool("reader")
        await lens.before_tool_callback(tool=NS(name="reader", agent=reader), tool_args={}, tool_context=tool_ctx)
        assert lens.called_as_tool("reader")
        # the inner runner is created now: no shape is announced for it
        manager = NS(plugins=[lens], register_plugin=lambda p: None)
        autoload._attach(NS(plugin_manager=manager, app=None, agent=reader, app_name="reader"))
        assert not [e for e in sent if e["type"] == "topology"]
        # ADK 1.x: the inner run is named after the agent and has its own session
        inner = NS(invocation_id="inner", session=NS(app_name="reader", id="s2"), agent=reader, user_id="tmp",
                   user_content=None)
        await lens.before_run_callback(invocation_context=inner)
        await lens.before_agent_callback(agent=reader, callback_context=inner)
        # ADK 1.x groups several tool results in an event with a made-up invocation id
        grouped = NS(invocation_id="made-up", author="reader", content=None, actions=None, partial=False, id="e1",
                     is_final_response=lambda: False)
        await lens.on_event_callback(invocation_context=inner, event=grouped)
        await lens.after_run_callback(invocation_context=inner)
        await lens.after_tool_callback(tool=NS(name="reader", agent=reader), tool_args={}, tool_context=tool_ctx, result="ok")
        assert not lens.called_as_tool("reader")
        await lens.after_run_callback(invocation_context=outer)

    asyncio.run(scenario())
    assert [e["type"] for e in sent] == ["run_start", "tool_start", "agent_start", "event", "tool_end", "run_end"]
    assert {(e["app"], e["run"]) for e in sent} == {("desk_app", "top")}
    assert sent[2]["nested"] is True
    # ...and once the tool call is over, a real app with that root agent is announced as usual.
    autoload._attach(NS(plugin_manager=NS(plugins=[lens], register_plugin=lambda p: None), app=None, agent=reader,
                        app_name="reader"))
    assert [e["app"] for e in sent if e["type"] == "topology"] == ["reader"]
