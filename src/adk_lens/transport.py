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
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import __version__
from .serialize import content_enabled, redact

DEFAULT_PORT = 4790
_QUEUE_MAX = 20000
EXIT_BUDGET = 0.3  # seconds the lens may cost at interpreter exit when the board does not answer


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


def home() -> Path:
    return Path(os.environ.get("ADK_LENS_HOME") or Path.home() / ".adk-lens")


# -- "stop" stays stopped ---------------------------------------------------
# `adk-lens stop` leaves a small marker file. While it is there, agent processes
# that are still running do not bring the board back by themselves. Any explicit
# start (`adk-lens open`, `demo`, `web`, `run`, `python`, `on`...) removes it.
def stop_file() -> Path:
    return home() / "stopped"


def stopped() -> bool:
    try:
        return stop_file().exists()
    except Exception:
        return False


def mark_stopped() -> None:
    try:
        stop_file().parent.mkdir(parents=True, exist_ok=True)
        stop_file().write_text("The board was stopped with `adk-lens stop`. `adk-lens open` starts it again.\n")
    except Exception:
        pass


def clear_stopped() -> None:
    try:
        stop_file().unlink()
    except Exception:
        pass


# -- a port used by something else -------------------------------------------
_port_said = False


def port_busy(timeout: float = 0.2) -> bool:
    """True when some program accepts connections on the port (lens hub or not)."""
    try:
        with socket.create_connection(("127.0.0.1", port()), timeout=timeout):
            return True
    except Exception:
        return False


def port_taken_by_other(timeout: float = 0.4) -> bool:
    """True when the port answers but is not an ADK Lens board (asked once via /api/ping)."""
    return ping(timeout) is None and port_busy()


def port_message() -> str:
    return (
        f"ADK Lens: port {port()} is used by another program, so the board is off. "
        f"Pick another port, for example: ADK_LENS_PORT={port() + 1}"
    )


def say_port_taken(force: bool = False) -> None:
    """One line on stderr, once per process (never when ADK_LENS_QUIET is set, unless forced)."""
    global _port_said
    if _port_said:
        return
    _port_said = True
    if not force and os.environ.get("ADK_LENS_QUIET", "").lower() in ("1", "true", "yes"):
        return
    try:
        sys.stderr.write(port_message() + "\n")
        sys.stderr.flush()
    except Exception:
        pass


def start_hub(wait: float = 4.0, explicit: bool = False) -> bool:
    """Make sure a hub is running. Starts a detached one if needed.

    `explicit=True` is for commands a person typed (`adk-lens open`, `demo`...): it
    lifts a previous `adk-lens stop`. Background senders pass False and respect it.
    Returns False at once when the port belongs to another program.
    """
    if ping():
        if explicit:
            clear_stopped()
        return True
    if port_busy():
        return False  # something else lives there: starting a hub cannot work
    if explicit:
        clear_stopped()
    elif stopped():
        return False
    try:
        env = dict(os.environ)
        env.pop("ADK_LENS", None)  # the hub itself never loads the lens
        proc = subprocess.Popen(
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
        if proc.poll() is not None:  # it gave up (port taken in the meantime): do not wait for nothing
            return ping(0.3) is not None
        time.sleep(0.05)
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
        self._off = False  # the port belongs to another program: stay off for this process
        self._send_lock = threading.Lock()

    def emit(self, event: dict) -> None:
        if self._off:
            return
        self._queue.append(event)
        if self._pid != os.getpid() or self._thread is None or not self._thread.is_alive():
            self._start_thread()
        self._wake.set()

    def _start_thread(self) -> None:
        with self._lock:
            if self._pid == os.getpid() and self._thread is not None and self._thread.is_alive():
                return
            if self._pid != os.getpid():
                self._send_lock = threading.Lock()  # a forked child must not inherit a held lock
            self._pid = os.getpid()
            self._hub_ok = False
            self._thread = threading.Thread(target=self._loop, name="adk-lens-sender", daemon=True)
            self._thread.start()
            atexit.register(self._exit_flush)

    def _loop(self) -> None:
        while not self._off:
            self._wake.wait(timeout=1.0)
            self._wake.clear()
            try:
                self._drain()
            except Exception:
                pass

    def _ensure_hub(self) -> bool:
        if self._hub_ok:
            return True
        if self._off:
            return False
        now = time.monotonic()
        if now < self._next_try:
            return False
        self._hub_ok = start_hub()
        if not self._hub_ok:
            self._next_try = now + 5.0
            if port_taken_by_other():
                # Not our board on that port: say it once and stop trying for good.
                self._off = True
                self._queue.clear()
                say_port_taken()
            elif stopped():
                self._queue.clear()  # the person said stop: nothing is kept for later
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

    def _post(self, batch: list, timeout: float = 2.0) -> bool:
        try:
            body = json.dumps({"events": batch}, default=str).encode("utf-8")
            conn = http.client.HTTPConnection("127.0.0.1", port(), timeout=timeout)
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

    def _exit_flush(self) -> None:
        """Last chance at interpreter exit. Must never hold the program back:
        no hub is started here, nothing is retried, and without a board that
        already answers we give up within about 0.3 s."""
        try:
            if self._off or self._pid != os.getpid():
                return
            begun = time.monotonic()
            # Taking the lock also waits for a batch the sender thread is posting right now:
            # without this, the end of the last request of a short script was lost.
            if not self._send_lock.acquire(timeout=EXIT_BUDGET):
                return  # the sender thread is busy looking for the board: let go
            try:
                if not self._queue:
                    return
                left = max(0.05, EXIT_BUDGET - (time.monotonic() - begun))
                if not self._hub_ok and ping(left) is None:
                    return
                deadline = time.monotonic() + 1.0  # only reached while the board keeps answering
                while self._queue and time.monotonic() < deadline:
                    batch = []
                    while self._queue and len(batch) < 200:
                        batch.append(self._queue.popleft())
                    if not self._post(batch, timeout=EXIT_BUDGET):
                        return
            finally:
                self._send_lock.release()
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
