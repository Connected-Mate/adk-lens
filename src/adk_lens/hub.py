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


def data_dir() -> Path:
    return Path(os.environ.get("ADK_LENS_HOME") or Path.home() / ".adk-lens")


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
        self._load()

    # -- persistence (small files: versions and notes only) ---------------
    def _load(self) -> None:
        try:
            self.versions = json.loads((data_dir() / "versions.json").read_text("utf-8"))
            for app, items in self.versions.items():
                if items:
                    self.apps[app] = items[-1]["topology"]
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
                if ev["type"] == "topology":
                    if not self._topology(ev):
                        continue  # unchanged shape: nothing new to show
                self.seq += 1
                ev["seq"] = self.seq
                self.events.append(ev)
            if len(self.events) > MAX_EVENTS:
                del self.events[: len(self.events) - MAX_EVENTS]
            self.lock.notify_all()

    def _topology(self, ev: dict) -> bool:
        app = str(ev.get("app") or "app")
        topo = {k: ev.get(k) for k in ("app", "root", "nodes", "edges")}
        digest = hashlib.sha1(json.dumps(topo, sort_keys=True, default=str).encode()).hexdigest()[:10]
        history = self.versions.setdefault(app, [])
        if history and history[-1].get("hash") == digest:
            self.apps[app] = topo
            return app not in {e.get("app") for e in self.events if e.get("type") == "topology"}
        version = (history[-1]["v"] + 1) if history else 1
        history.append({"v": version, "ts": ev.get("ts") or time.time(), "hash": digest, "topology": topo})
        del history[:-MAX_VERSIONS]
        self.apps[app] = topo
        ev["version"] = version
        self._save("versions.json", self.versions)
        return True

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "seq": self.seq,
                "events": list(self.events),
                "apps": dict(self.apps),
                "versions": {k: list(v) for k, v in self.versions.items()},
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

    threading.Thread(target=watchdog, daemon=True).start()
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
    return serve(args.port, args.idle_hours)


if __name__ == "__main__":
    raise SystemExit(main())
