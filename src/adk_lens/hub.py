"""The lens hub: a tiny local web server that keeps the events and serves the UI.

Standard library only. Listens on 127.0.0.1 only. Runs as its own process
(`python -m adk_lens.hub`) so it never shares anything with the agent's process
and outlives short agent runs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import __version__

STATIC = Path(__file__).parent / "static"
MAX_EVENTS = 40000
MAX_BODY = 32 * 1024 * 1024
MAX_VERSIONS = 30
PARTIAL_KEEP = 300  # streamed text chunks are noisy; keep them short in history


REAP_EVERY = 3.0  # seconds between two looks at the processes that have a request in progress


def data_dir() -> Path:
    return Path(os.environ.get("ADK_LENS_HOME") or Path.home() / ".adk-lens")


def _sha(value) -> str:
    return hashlib.sha1(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()[:10]


def shape_hash(topo: dict) -> str:
    """Fingerprint of the structure only: which nodes (id, name, kind, parent) and which edges.

    It does not look at instructions, descriptions or model names, so it is the same
    with and without ADK_LENS_CONTENT=0.
    """
    nodes = sorted(
        [str(n.get("id")), str(n.get("name")), str(n.get("kind")), str(n.get("parent"))]
        for n in topo.get("nodes") or [] if isinstance(n, dict)
    )
    edges = sorted(
        [str(e.get("from")), str(e.get("to")), str(e.get("kind")), str(e.get("order"))]
        for e in topo.get("edges") or [] if isinstance(e, dict)
    )
    return _sha([str(topo.get("root")), nodes, edges])


def full_hash(topo: dict) -> str:
    """Fingerprint of everything shown on the map (structure, instructions, descriptions, models)."""
    return _sha([topo.get("root"), topo.get("nodes"), topo.get("edges")])


def pid_alive(pid) -> bool:
    """Is that process still there? When in doubt, say yes."""
    try:
        pid = int(pid)
        if pid <= 0:
            return True
        if os.name == "nt":
            import ctypes

            kernel = ctypes.windll.kernel32
            handle = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
            if not handle:
                return kernel.GetLastError() == 5  # access denied: it exists
            try:
                code = ctypes.c_ulong()
                return not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259
            finally:
                kernel.CloseHandle(handle)
        os.kill(pid, 0)  # signal 0: only checks, sends nothing
        return True
    except ProcessLookupError:
        return False
    except Exception:
        return True


class Store:
    def __init__(self) -> None:
        self.lock = threading.Condition()
        self.events: list[dict] = []
        self.seq = 0
        self.apps: dict[str, dict] = {}
        self.versions: dict[str, list[dict]] = {}
        self.notes = None
        self.last_activity = time.monotonic()
        self.clients = 0
        self.open_runs: dict[str, dict] = {}  # run id -> {app, session, pid} until run_end / run_error
        self._suspects: set = set()
        self._load()

    # -- persistence (small files: versions and notes only) ---------------
    def _load(self) -> None:
        try:
            self.versions = json.loads((data_dir() / "versions.json").read_text("utf-8"))
            for app, items in self.versions.items():
                if not items:
                    continue
                for item in items:  # files written by an older lens: fill in what is new
                    topo = item["topology"]
                    item["shape"] = shape_hash(topo)
                    item["hash"] = item["shape"] if item.get("content") is False else full_hash(topo)
                    item.setdefault("seen", item.get("ts"))
                current = [item for item in items if item.get("current")]
                for item in items:
                    item["current"] = item is (current[-1] if current else items[-1])
                self.apps[app] = self._current(items)["topology"]
        except Exception:
            self.versions = {}
        try:
            self.notes = json.loads((data_dir() / "notes.json").read_text("utf-8"))
        except Exception:
            self.notes = None

    def _save(self, name: str, value) -> None:
        try:
            folder = data_dir()
            folder.mkdir(parents=True, exist_ok=True)
            tmp = folder / (name + ".tmp")
            tmp.write_text(json.dumps(value), "utf-8")
            tmp.replace(folder / name)
        except Exception:
            pass

    # -- events ------------------------------------------------------------
    def add(self, incoming: list) -> None:
        with self.lock:
            self.last_activity = time.monotonic()
            for ev in incoming:
                if not isinstance(ev, dict) or not isinstance(ev.get("type"), str):
                    continue
                kind = ev["type"]
                if kind == "topology":
                    if not self._topology(ev):
                        continue  # unchanged shape: nothing new to show
                run = ev.get("run")
                if isinstance(run, str) and run:
                    if kind == "run_start":
                        self.open_runs[run] = {"app": ev.get("app"), "session": ev.get("session"), "pid": ev.get("pid")}
                    elif kind in ("run_end", "run_error"):
                        self.open_runs.pop(run, None)
                self.seq += 1
                ev["seq"] = self.seq
                self.events.append(ev)
            if len(self.events) > MAX_EVENTS:
                del self.events[: len(self.events) - MAX_EVENTS]
            self.lock.notify_all()

    def reap(self, alive=pid_alive) -> int:
        """Close the requests whose process is gone (killed, crashed, Ctrl+C).

        A process must be seen missing on two looks in a row, so that the last
        events it sent while exiting have arrived. Returns how many were closed.
        """
        with self.lock:
            pids = {r.get("pid") for r in self.open_runs.values() if isinstance(r.get("pid"), int)}
        gone = {pid for pid in pids if not alive(pid)}
        confirmed, self._suspects = gone & self._suspects, gone
        if not confirmed:
            return 0
        closing = []
        with self.lock:
            for run, info in list(self.open_runs.items()):
                if info.get("pid") in confirmed:
                    closing.append({
                        "type": "run_end", "app": info.get("app"), "session": info.get("session"), "run": run,
                        "pid": info.get("pid"), "ts": time.time(), "interrupted": True, "reason": "process_gone",
                    })
        if closing:
            activity = self.last_activity
            self.add(closing)
            self.last_activity = activity  # house-keeping is not a sign of life
        return len(closing)

    @staticmethod
    def _current(history: list) -> dict | None:
        for item in history:
            if item.get("current"):
                return item
        return history[-1] if history else None

    def _topology(self, ev: dict) -> bool:
        """Record the app's shape. True when the event is worth showing (new or changed)."""
        app = str(ev.get("app") or "app")
        topo = {k: ev.get(k) for k in ("app", "root", "nodes", "edges")}
        stripped = ev.get("content") is False  # sent with ADK_LENS_CONTENT=0: no instructions, no descriptions
        shape = shape_hash(topo)
        digest = shape if stripped else full_hash(topo)
        history = self.versions.setdefault(app, [])
        current = self._current(history)
        recent_first = ([current] if current else []) + [v for v in reversed(history) if v is not current]

        match = None
        completed = False
        if stripped:
            # Without content we can only compare structures.
            match = next((v for v in recent_first if v.get("shape") == shape), None)
        else:
            match = next((v for v in recent_first if v.get("hash") == digest), None)
            if match is None:
                # The same structure was first recorded without content: complete it, it is not a change.
                match = next((v for v in recent_first if v.get("shape") == shape and v.get("content") is False), None)
                if match is not None:
                    match.pop("content", None)
                    match.update(hash=digest, topology=topo)
                    completed = True
                    self._save("versions.json", self.versions)

        if match is not None and match is current:
            self.apps[app] = match["topology"]
            ev["version"] = match["v"]
            return completed or app not in {e.get("app") for e in self.events if e.get("type") == "topology"}

        now = ev.get("ts") or time.time()
        for item in history:
            item["current"] = False
        if match is not None:
            # Back to a shape we already know: no duplicate, that version is the current one again.
            match.update(current=True, seen=now)
            ev["reverted"] = True
        else:
            match = {"v": max((v["v"] for v in history), default=0) + 1, "ts": now, "seen": now,
                     "hash": digest, "shape": shape, "current": True, "topology": topo}
            if stripped:
                match["content"] = False
            history.append(match)
            while len(history) > MAX_VERSIONS:
                history.remove(next(v for v in history if v is not match))
        self.apps[app] = match["topology"]
        ev["version"] = match["v"]
        self._save("versions.json", self.versions)
        return True

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "seq": self.seq,
                "events": list(self.events),
                "apps": dict(self.apps),
                "versions": {k: list(v) for k, v in self.versions.items()},
                "current": {k: self._current(v)["v"] for k, v in self.versions.items() if v},
                "notes": self.notes,
                "version": __version__,
            }

    def since(self, seq: int, timeout: float) -> list[dict]:
        with self.lock:
            if self.seq <= seq:
                self.lock.wait(timeout)
            if self.seq <= seq:
                return []
            # events are ordered by seq; find the first newer one from the end
            i = len(self.events)
            while i > 0 and self.events[i - 1]["seq"] > seq:
                i -= 1
            return self.events[i:]

    def clear(self) -> None:
        with self.lock:
            self.events = []
            # open_runs is kept: a request still running after a clear must be closed
            # like any other when it ends or when its program disappears.
            self.seq += 1
            self.events.append({"seq": self.seq, "ts": time.time(), "type": "cleared"})
            self.lock.notify_all()

    def set_notes(self, notes) -> None:
        with self.lock:
            self.notes = notes
        self._save("notes.json", notes)


class Handler(BaseHTTPRequestHandler):
    server_version = "adk-lens"
    protocol_version = "HTTP/1.1"
    store: Store

    def log_message(self, *args) -> None:  # silent
        pass

    # -- helpers -----------------------------------------------------------
    def _host_ok(self) -> bool:
        """Refuse requests that reach us under a foreign host name (DNS rebinding)."""
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]").lower()
        return host in ("127.0.0.1", "localhost", "::1")

    def _origin_ok(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True
        host = (urlparse(origin).hostname or "").lower()
        return host in ("127.0.0.1", "localhost", "::1")

    def _json(self, value, status: int = 200) -> None:
        body = json.dumps(value, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY:
            return None
        try:
            return json.loads(self.rfile.read(length))
        except Exception:
            return None

    def _guard_write(self) -> bool:
        if not self.headers.get("X-ADK-Lens") or not self._origin_ok():
            self._json({"error": "forbidden"}, 403)
            return False
        return True

    # -- routes ------------------------------------------------------------
    def do_GET(self) -> None:
        if not self._host_ok():
            return self._json({"error": "forbidden"}, 403)
        url = urlparse(self.path)
        if url.path == "/api/ping":
            return self._json({"adk_lens": __version__, "pid": os.getpid()})
        if url.path == "/api/state":
            return self._json(self.store.snapshot())
        if url.path == "/api/notes":
            return self._json(self.store.notes)
        if url.path == "/api/stream":
            return self._stream(url)
        return self._static(url.path)

    def do_POST(self) -> None:
        if not self._host_ok():
            return self._json({"error": "forbidden"}, 403)
        path = urlparse(self.path).path
        if path == "/api/ingest":
            if not self._guard_write():
                return
            body = self._body()
            events = body.get("events") if isinstance(body, dict) else None
            if not isinstance(events, list):
                return self._json({"error": "bad request"}, 400)
            self.store.add(events)
            return self._json({"ok": True})
        if path == "/api/clear":
            if not self._guard_write():
                return
            self._body()
            self.store.clear()
            return self._json({"ok": True})
        if path == "/api/shutdown":
            if not self._guard_write():
                return
            self._body()
            self._json({"ok": True})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        self._json({"error": "not found"}, 404)

    def do_PUT(self) -> None:
        if not self._host_ok():
            return self._json({"error": "forbidden"}, 403)
        if urlparse(self.path).path != "/api/notes":
            return self._json({"error": "not found"}, 404)
        if not self._guard_write():
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY:
            return self._json({"error": "bad request"}, 400)
        try:
            notes = json.loads(self.rfile.read(length))
        except Exception:
            return self._json({"error": "bad request"}, 400)
        self.store.set_notes(notes)
        self._json({"ok": True})

    def _stream(self, url) -> None:
        try:
            seq = int(parse_qs(url.query).get("since", ["0"])[0])
        except ValueError:
            seq = 0
        last_id = self.headers.get("Last-Event-ID")
        if last_id and last_id.isdigit():
            seq = max(seq, int(last_id))
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        self.close_connection = True
        store = self.store
        with store.lock:
            store.clients += 1
        try:
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            while True:
                batch = store.since(seq, timeout=15.0)
                if not batch:
                    self.wfile.write(b": ping\n\n")
                else:
                    out = []
                    for ev in batch:
                        seq = ev["seq"]
                        out.append(f"id: {seq}\ndata: {json.dumps(ev, default=str)}\n\n")
                    self.wfile.write("".join(out).encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            with store.lock:
                store.clients -= 1
                store.last_activity = time.monotonic()

    def _static(self, path: str) -> None:
        rel = "index.html" if path in ("", "/") else path.lstrip("/")
        try:
            target = (STATIC / rel).resolve()
            target.relative_to(STATIC.resolve())
        except Exception:
            return self._json({"error": "not found"}, 404)
        if not target.is_file():
            return self._json({"error": "not found"}, 404)
        body = target.read_bytes()
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(body)


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address) -> None:
        pass  # a client that hangs up early is not worth a traceback


def serve(port: int, idle_hours: float = 8.0) -> int:
    store = Store()
    handler = type("LensHandler", (Handler,), {"store": store})
    try:
        server = _Server(("127.0.0.1", port), handler)
    except OSError:
        return 2  # port taken (most likely another hub won the race)

    def watchdog() -> None:
        # Stop by itself when nobody has used it for a long time.
        while True:
            time.sleep(60)
            with store.lock:
                idle = time.monotonic() - store.last_activity
                busy = store.clients > 0
            if not busy and idle > idle_hours * 3600:
                server.shutdown()
                return

    def reaper() -> None:
        while True:
            time.sleep(REAP_EVERY)
            try:
                store.reap()
            except Exception:
                pass

    threading.Thread(target=watchdog, daemon=True).start()
    threading.Thread(target=reaper, daemon=True).start()
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="adk_lens.hub")
    parser.add_argument("--port", type=int, default=int(os.environ.get("ADK_LENS_PORT", 4790)))
    parser.add_argument("--idle-hours", type=float, default=8.0)
    args = parser.parse_args(argv)
    code = serve(args.port, args.idle_hours)
    if code == 2:
        import sys

        print(f"ADK Lens: port {args.port} is already in use. Pick another one, for example: "
              f"ADK_LENS_PORT={args.port + 1}", file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
