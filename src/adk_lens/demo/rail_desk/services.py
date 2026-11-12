"""The two local services the rail desk demo talks to, for real, on 127.0.0.1.

- a tiny station-information web site (a few HTML pages) read with a real HTTP GET;
- a mail sink that speaks just enough SMTP for `smtplib`: it keeps every message
  in memory and delivers nothing. No e-mail leaves the machine.

Both listen on a free port picked by the system, start with `running()` and stop
when that block ends. Importing this module starts nothing.
"""

from __future__ import annotations

import contextlib
import socketserver
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = "127.0.0.1"


def _page(title: str, body: str) -> str:
    return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'><title>{title}</title></head>"
            f"<body><h1>{title}</h1>{body}<p><a href='/'>Back to the station home page</a></p></body></html>")


PAGES = {
    "/": _page("Northbridge station", """
        <p>Everything about the station, in one place.</p>
        <ul>
          <li><a href="/accessibility.html">Lifts and accessibility</a></li>
          <li><a href="/lost-property.html">Lost property</a></li>
          <li><a href="/bikes.html">Bike spaces</a></li>
          <li><a href="/opening-hours.html">Opening hours</a></li>
        </ul>"""),
    "/accessibility.html": _page("Lifts and accessibility", """
        <p>Lifts: one lift to each platform, from the main hall.</p>
        <p>Out of order: the lift to platform 4, until Friday. Use the ramp at the north end.</p>
        <p>Help on the platform: ask at the rail desk 20 minutes before your train.</p>
        <p>The rail desk is staffed during ticket office hours (see <a href="/opening-hours.html">Opening hours</a>).</p>"""),
    "/lost-property.html": _page("Lost property", """
        <p>Where: the lost property desk is in the main hall, next to platform 1.</p>
        <p>Kept for: 30 days. Bring a description of the item and the train number if you have it.</p>
        <p>Open: during ticket office hours (see <a href="/opening-hours.html">Opening hours</a>).</p>"""),
    "/bikes.html": _page("Bike spaces", """
        <p>On trains: 6 bike spaces per train, in coach 1. Free, no booking.</p>
        <p>At the station: a locked bike room with 80 places, behind platform 1.</p>
        <p>The bike room is open during station hours (see <a href="/opening-hours.html">Opening hours</a>).</p>"""),
    "/opening-hours.html": _page("Opening hours", """
        <p>Station: every day, 05:00 to 23:30.</p>
        <p>Ticket office, Monday to Friday: 06:00 to 21:00.</p>
        <p>Ticket office, Saturday: 07:00 to 20:00.</p>
        <p>Ticket office, Sunday: 09:00 to 17:00.</p>"""),
}


class _SiteHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 (name set by http.server)
        path = self.path.split("?", 1)[0]
        if path == "/index.html":
            path = "/"
        self.server.site.hits.append(path)
        page = PAGES.get(path)
        body = (page if page is not None else _page("Page not found", "<p>No such page.</p>")).encode("utf-8")
        self.send_response(200 if page is not None else 404)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # the demo's terminal stays for the conversation
        pass


class StationSite:
    """The station's web site. `hits` lists every path that was really requested."""

    def __init__(self) -> None:
        self.hits: list[str] = []
        self._server: ThreadingHTTPServer | None = None

    def start(self) -> None:
        self._server = ThreadingHTTPServer((HOST, 0), _SiteHandler)
        self._server.daemon_threads = True
        self._server.site = self
        self._server.handle_error = lambda *a: None
        threading.Thread(target=self._server.serve_forever, daemon=True, name="rail-desk-site").start()

    @property
    def port(self) -> int:
        return self._server.server_address[1] if self._server else 0

    @property
    def url(self) -> str:
        return f"http://{HOST}:{self.port}/"

    def stop(self) -> None:
        server, self._server = self._server, None
        if server is not None:
            server.shutdown()
            server.server_close()


def _address(text: str) -> str:
    """`MAIL FROM:<a@b> SIZE=1` -> `a@b`."""
    rest = text.split(":", 1)[1] if ":" in text else ""
    if "<" in rest and ">" in rest:
        return rest[rest.index("<") + 1:rest.index(">")].strip().lower()
    return (rest.split() or [""])[0].strip().lower()


class _SmtpHandler(socketserver.StreamRequestHandler):
    def _say(self, line: str) -> None:
        self.wfile.write(line.encode("utf-8") + b"\r\n")
        self.wfile.flush()

    def handle(self) -> None:
        sink: MailSink = self.server.sink
        sender, recipients = "", []
        try:
            self._say("220 rail-desk local mail sink (nothing leaves this machine)")
            while True:
                raw = self.rfile.readline()
                if not raw:
                    return
                text = raw.decode("utf-8", "replace").strip()
                upper = text.upper()
                if upper.startswith(("EHLO", "HELO")):
                    self._say("250 rail-desk")
                elif upper.startswith("MAIL FROM:"):
                    sender, recipients = _address(text), []
                    self._say("250 OK")
                elif upper.startswith("RCPT TO:"):
                    address = _address(text)
                    reason = sink.refusal(address)
                    if reason:
                        sink.refused.append(address)
                        self._say(f"550 {reason}")
                    else:
                        recipients.append(address)
                        self._say("250 OK")
                elif upper == "DATA":
                    if not recipients:
                        self._say("503 5.5.1 no valid recipient")
                        continue
                    self._say("354 End data with <CR><LF>.<CR><LF>")
                    lines = []
                    while True:
                        raw = self.rfile.readline()
                        if not raw or raw in (b".\r\n", b".\n"):
                            break
                        lines.append(raw[1:] if raw.startswith(b"..") else raw)
                    sink.messages.append({"from": sender, "to": list(recipients),
                                          "data": b"".join(lines).decode("utf-8", "replace")})
                    sender, recipients = "", []
                    self._say("250 OK: kept in memory")
                elif upper == "RSET":
                    sender, recipients = "", []
                    self._say("250 OK")
                elif upper == "NOOP":
                    self._say("250 OK")
                elif upper == "QUIT":
                    self._say("221 Bye")
                    return
                else:
                    self._say("502 5.5.2 command not recognised")
        except OSError:
            pass


class _SmtpServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def handle_error(self, *args):
        pass


class MailSink:
    """Receives mail over SMTP and keeps it. `messages` were accepted, `refused` got a 550."""

    # A mailbox that "no longer exists", so the demo shows a refusal and how the agent copes.
    UNKNOWN = {"t.brandt@example.com"}

    def __init__(self) -> None:
        self.messages: list[dict] = []
        self.refused: list[str] = []
        self._server: _SmtpServer | None = None

    def refusal(self, address: str) -> str | None:
        if address in self.UNKNOWN:
            return "mailbox unknown"
        if not address.endswith("@example.com"):
            return "this sink only accepts @example.com addresses"
        return None

    def start(self) -> None:
        self._server = _SmtpServer((HOST, 0), _SmtpHandler)
        self._server.sink = self
        threading.Thread(target=self._server.serve_forever, daemon=True, name="rail-desk-mail").start()

    @property
    def port(self) -> int:
        return self._server.server_address[1] if self._server else 0

    def stop(self) -> None:
        server, self._server = self._server, None
        if server is not None:
            server.shutdown()
            server.server_close()


class Services:
    def __init__(self) -> None:
        self.site = StationSite()
        self.mail = MailSink()


_current: Services | None = None


def current() -> Services:
    """The services of the demo that is playing. The tools call this."""
    if _current is None:
        raise RuntimeError("The rail desk services are not running (start them with services.running()).")
    return _current


@contextlib.contextmanager
def running():
    """Start the web site and the mail sink, hand them over, stop them at the end (also on Ctrl+C)."""
    global _current
    services = Services()
    try:
        services.site.start()
        services.mail.start()
        _current = services
        yield services
    finally:
        _current = None
        services.site.stop()
        services.mail.stop()
