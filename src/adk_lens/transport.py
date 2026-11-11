"""Ship events from the agent's process to the local lens hub.

Design rule: the agent must never wait for the lens. `emit` only appends to a
bounded in-memory queue; a daemon thread does all the networking. If the hub is
unreachable, events are dropped silently.
"""

from __future__ import annotations

import atexit
import collections
import http.client
import json
import os
import subprocess
import sys
import threading
import time

from . import __version__
from .serialize import content_enabled, redact

DEFAULT_PORT = 4790
_QUEUE_MAX = 20000


def port() -> int:
    try:
        return int(os.environ.get("ADK_LENS_PORT", DEFAULT_PORT))
    except ValueError:
        return DEFAULT_PORT


def url() -> str:
    return f"http://127.0.0.1:{port()}"


def ping(timeout: float = 0.4) -> dict | None:
    """Return the hub's identity if a lens hub answers on the port."""
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port(), timeout=timeout)
        conn.request("GET", "/api/ping")
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        data = json.loads(body)
        return data if isinstance(data, dict) and data.get("adk_lens") else None
    except Exception:
        return None


def start_hub(wait: float = 4.0) -> bool:
    """Make sure a hub is running. Starts a detached one if needed."""
    if ping():
        return True
    try:
        env = dict(os.environ)
        env.pop("ADK_LENS", None)  # the hub itself never loads the lens
        subprocess.Popen(
            [sys.executable, "-m", "adk_lens.hub", "--port", str(port())],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
            env=env,
        )
    except Exception:
        return False
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if ping(0.3):
            return True
        time.sleep(0.1)
    return False


class _Sender:
    def __init__(self) -> None:
        self._queue: collections.deque = collections.deque(maxlen=_QUEUE_MAX)
        self._wake = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._pid: int | None = None
        self._hub_ok = False
        self._next_try = 0.0
        self._announced = False
        self._send_lock = threading.Lock()

    def emit(self, event: dict) -> None:
        self._queue.append(event)
        if self._pid != os.getpid() or self._thread is None or not self._thread.is_alive():
            self._start_thread()
        self._wake.set()

    def _start_thread(self) -> None:
        with self._lock:
            if self._pid == os.getpid() and self._thread is not None and self._thread.is_alive():
                return
            self._pid = os.getpid()
            self._hub_ok = False
            self._thread = threading.Thread(target=self._loop, name="adk-lens-sender", daemon=True)
            self._thread.start()
            atexit.register(self.flush, 1.5)

    def _loop(self) -> None:
        while True:
            self._wake.wait(timeout=1.0)
            self._wake.clear()
            try:
                self._drain()
            except Exception:
                pass

    def _ensure_hub(self) -> bool:
        if self._hub_ok:
            return True
        now = time.monotonic()
        if now < self._next_try:
            return False
        self._hub_ok = start_hub()
        if not self._hub_ok:
            self._next_try = now + 5.0
        elif not self._announced:
            self._announced = True
            if os.environ.get("ADK_LENS_QUIET", "").lower() not in ("1", "true", "yes"):
                try:
                    sys.stderr.write(f"\n  ADK Lens is watching. Open {url()}\n\n")
                    sys.stderr.flush()
                except Exception:
                    pass
        return self._hub_ok

    def _drain(self, deadline: float | None = None) -> None:
        with self._send_lock:
            while self._queue:
                if deadline is not None and time.monotonic() > deadline:
                    return
                if not self._ensure_hub():
                    return
                batch = []
                while self._queue and len(batch) < 200:
                    batch.append(self._queue.popleft())
                if not self._post(batch):
                    self._hub_ok = False
                    # One retry after re-checking the hub, then give up on this batch.
                    if not (self._ensure_hub() and self._post(batch)):
                        return

    def _post(self, batch: list) -> bool:
        try:
            body = json.dumps({"events": batch}, default=str).encode("utf-8")
            conn = http.client.HTTPConnection("127.0.0.1", port(), timeout=2.0)
            conn.request(
                "POST",
                "/api/ingest",
                body=body,
                headers={"Content-Type": "application/json", "X-ADK-Lens": __version__},
            )
            ok = conn.getresponse().status == 200
            conn.close()
            return ok
        except Exception:
            return False

    def flush(self, timeout: float = 1.5) -> None:
        try:
            self._drain(deadline=time.monotonic() + timeout)
        except Exception:
            pass


_sender = _Sender()


def emit(event: dict) -> None:
    """Queue one event for the hub. Never raises, never blocks."""
    try:
        event.setdefault("ts", time.time())
        event.setdefault("pid", os.getpid())
        if not content_enabled():
            event = redact(event)
        _sender.emit(event)
    except Exception:
        pass


def flush(timeout: float = 1.5) -> None:
    _sender.flush(timeout)
