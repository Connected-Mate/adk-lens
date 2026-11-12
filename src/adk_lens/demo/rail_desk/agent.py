"""A hard multi-agent ADK app that needs no API key: the desk of a fictional railway station.

The "model" is scripted (it answers from a fixed script, so the demo behaves the same
everywhere). Everything else is real ADK and real work: hand-offs, an agent used as a
tool, steps in a row, two agents at once, a loop that ends itself, shared memory, tools
that read a web site over HTTP and send e-mail over SMTP (both local, see services.py).

Stations, trains and passengers are invented.
"""

from __future__ import annotations

import asyncio
import re
import smtplib
import urllib.error
import urllib.request
from email.message import EmailMessage
from html.parser import HTMLParser
from typing import AsyncGenerator
from urllib.parse import urljoin, urlparse

from google.adk.agents import LlmAgent, LoopAgent, ParallelAgent, SequentialAgent
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.tools import ToolContext, exit_loop
from google.adk.tools.agent_tool import AgentTool
from google.genai import types

from . import armor, services

PACE = 1.2  # seconds of "thinking", so the whiteboard is watchable
DESK_ADDRESS = "desk@example.com"

# -- the fictional railway ---------------------------------------------------------
TIMETABLE = [  # Northbridge -> Port Elm, one morning
    {"train_id": "6603", "departs": "07:40", "arrives": "08:35"},
    {"train_id": "6605", "departs": "08:10", "arrives": "09:05"},
    {"train_id": "6607", "departs": "08:40", "arrives": "09:35"},
    {"train_id": "6609", "departs": "09:10", "arrives": "10:05"},
    {"train_id": "6612", "departs": "09:25", "arrives": "10:20"},
    {"train_id": "6614", "departs": "09:40", "arrives": "10:35"},
    {"train_id": "6616", "departs": "10:10", "arrives": "11:05"},
    {"train_id": "6618", "departs": "10:40", "arrives": "11:35"},
    {"train_id": "6620", "departs": "11:10", "arrives": "12:05"},
]
LIVE = {
    "6607": {"status": "delayed", "delay_min": 12, "expected": "08:52", "platform": "2",
             "reason": "signal fault near Larkfield"},
    "6612": {"status": "cancelled", "reason": "rolling stock fault"},
    "6620": {"status": "on time", "platform": "7"},
}
FREE_SEATS = {"6618": {"coach": 3, "seat": "14C"}}  # every other train is full
PASSENGERS = {
    "6620": [
        {"name": "Ines Carver", "email": "ines.carver@example.com"},
        {"name": "Tom Brandt", "email": "t.brandt@example.com"},  # the mail sink refuses this one
        {"name": "Lena Okoye", "email": "lena.okoye@example.com"},
    ],
}
NOTICES = [
    {"kind": "works", "what": "track works between Larkfield and Port Elm", "when": "Saturday and Sunday",
     "effect": "replacement bus"},
    {"kind": "strike", "what": "signallers' walkout", "when": "Thursday", "effect": "1 train in 2"},
]


class TimetableUnavailable(RuntimeError):
    """The timetable service does not answer."""


# -- tools ---------------------------------------------------------------------------
def search_trains(origin: str, destination: str, after: str) -> dict:
    """Lists the next three departures between two stations after a time (HH:MM)."""
    if "saltmarsh" in destination.lower():
        raise TimetableUnavailable("Timetable service is not answering for the Saltmarsh branch (line 9)")
    trains = []
    if (origin.strip().lower(), destination.strip().lower()) == ("northbridge", "port elm"):
        trains = [dict(t) for t in TIMETABLE if t["departs"] > after][:3]
    return {"origin": origin, "destination": destination, "after": after, "trains": trains}


def get_live_status(train_id: str, tool_context: ToolContext) -> dict:
    """Says whether a train is on time, late or cancelled right now, and its platform."""
    tool_context.state["last_train"] = train_id  # remembered for follow-up questions
    planned = next((t for t in TIMETABLE if t["train_id"] == train_id), None)
    if planned is None:
        return {"train_id": train_id, "status": "unknown"}
    return {"train_id": train_id, "departs": planned["departs"],
            **LIVE.get(train_id, {"status": "on time", "platform": "1"})}


def list_delays() -> dict:
    """Lists the trains that are late or cancelled right now."""
    return {"delays": [{"train_id": train_id, **info} for train_id, info in LIVE.items() if info["status"] != "on time"]}


def list_notices() -> dict:
    """Lists the planned works and strike notices for this week."""
    return {"notices": [dict(n) for n in NOTICES]}


class _PageText(HTMLParser):
    """Keeps the title, the lines of text and the links of a page."""

    def __init__(self, base: str) -> None:
        super().__init__()
        self.base, self.title, self.lines, self.links = base, "", [], []
        self._buffer: list[str] = []
        self._href: str | None = None
        self._label: list[str] = []
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._in_title = True
        elif tag == "a":
            self._href, self._label = dict(attrs).get("href"), []
        elif tag in ("p", "li", "h1", "h2", "ul", "div", "br"):
            self._flush()

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag == "a" and self._href:
            self.links.append({"label": " ".join("".join(self._label).split()), "url": urljoin(self.base, self._href)})
            self._href = None
        elif tag in ("p", "li", "h1", "h2", "ul", "div"):
            self._flush()

    def handle_data(self, data):
        if self._in_title:
            self.title += data
            return
        self._buffer.append(data)
        if self._href:
            self._label.append(data)

    def _flush(self):
        line = " ".join("".join(self._buffer).split())
        self._buffer = []
        if line:
            self.lines.append(line)


def fetch_page(url: str) -> dict:
    """Reads a page of the station web site (a real HTTP GET) and returns its text and links."""
    site = services.current().site
    target = urlparse(url)
    if target.scheme != "http" or target.hostname != services.HOST or target.port != site.port:
        return {"url": url, "status": "refused", "error": "Only the station's own web site can be read."}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # straight to 127.0.0.1, no proxy
    try:
        with opener.open(url, timeout=5) as response:
            status, html = response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        return {"url": url, "status": error.code, "error": "Page not found." if error.code == 404 else str(error)}
    page = _PageText(url)
    page.feed(html)
    page.close()
    page._flush()
    return {"url": url, "status": status, "title": page.title.strip(), "text": "\n".join(page.lines), "links": page.links}


def try_hold_seat(train_id: str, tool_context: ToolContext) -> dict:
    """Tries to hold one seat on a train. A train that was already tried is not tried again."""
    tried = list(tool_context.state.get("seats_tried") or [])
    if train_id in tried:
        return {"train_id": train_id, "held": False, "reason": "already tried"}
    tool_context.state["seats_tried"] = tried + [train_id]
    seat = FREE_SEATS.get(train_id)
    if seat is None:
        return {"train_id": train_id, "held": False, "reason": "full"}
    departs = next(t["departs"] for t in TIMETABLE if t["train_id"] == train_id)
    tool_context.state["held_seat"] = f"train {train_id} at {departs}, coach {seat['coach']}, seat {seat['seat']}"
    return {"train_id": train_id, "held": True, "departs": departs, **seat}


def send_email(to: str, subject: str, body: str) -> dict:
    """Sends an e-mail to a passenger (real SMTP, to the demo's local mail sink)."""
    message = EmailMessage()
    message["From"], message["To"], message["Subject"] = DESK_ADDRESS, to, subject
    message.set_content(body)
    try:
        with smtplib.SMTP(services.HOST, services.current().mail.port, local_hostname="localhost", timeout=5) as smtp:
            smtp.send_message(message)
    except smtplib.SMTPRecipientsRefused as refused:
        code, reason = next(iter(refused.recipients.values()))
        return {"status": "refused", "to": to, "smtp_code": code, "error": reason.decode("utf-8", "replace")}
    return {"status": "sent", "to": to, "subject": subject}


def list_passengers(train_id: str) -> dict:
    """Lists the passengers booked on a train, with their e-mail address."""
    return {"train_id": train_id, "passengers": [dict(p) for p in PASSENGERS.get(train_id, [])]}


def leave_desk_note(passenger: str, note: str, tool_context: ToolContext) -> dict:
    """Leaves a note at the rail desk for a passenger who cannot be reached by e-mail."""
    notes = list(tool_context.state.get("desk_notes") or [])
    tool_context.state["desk_notes"] = notes + [{"passenger": passenger, "note": note}]
    return {"status": "noted", "passenger": passenger}


# -- the scripted model ----------------------------------------------------------------
def _usage(prompt: int, answer: int):
    return types.GenerateContentResponseUsageMetadata(prompt_token_count=prompt, candidates_token_count=answer)


def _text(text: str) -> LlmResponse:
    return LlmResponse(content=types.Content(role="model", parts=[types.Part(text=text)]),
                       usage_metadata=_usage(260 + len(text), max(8, len(text) // 4)))


def _calls(*calls: tuple) -> LlmResponse:
    """One model turn that asks for one or several tools at once: ("name", {args}), ..."""
    parts = [types.Part(function_call=types.FunctionCall(name=name, args=args)) for name, args in calls]
    return LlmResponse(content=types.Content(role="model", parts=parts), usage_metadata=_usage(290, 14 * len(parts)))


def _between(text: str, start: str, end: str) -> str:
    """The part of an instruction that ADK filled in from memory, between two markers."""
    found = re.search(re.escape(start) + r"(.*?)" + re.escape(end), text, re.S)
    return found.group(1).strip() if found else ""


def _results(content, name: str | None = None) -> list:
    """The tool results carried by one message."""
    parts = list(getattr(content, "parts", None) or [])
    return [p.function_response for p in parts if p.function_response and name in (None, p.function_response.name)]


def _all_results(request: LlmRequest, name: str) -> list:
    return [r for content in request.contents for r in _results(content, name)]


def _question(request: LlmRequest) -> str:
    """The last thing the passenger wrote (not what other agents said)."""
    for content in reversed(request.contents):
        if content.role != "user":
            continue
        text = " ".join(p.text for p in (content.parts or []) if p.text).strip()
        if text and not text.startswith("For context:"):
            return text
    return ""


def _train(text: str) -> str | None:
    found = re.search(r"\b(\d{4})\b", text)
    return found.group(1) if found else None


def _journey(text: str) -> tuple[str, str] | None:
    found = re.search(r"from ([A-Z][A-Za-z ]+?) to ([A-Z][A-Za-z ]+?)(?= after| is| at|[?.,]|$)", text)
    return (found.group(1), found.group(2)) if found else None


def _status_line(r: dict) -> str:
    train, status = r.get("train_id"), r.get("status")
    if status == "delayed":
        return (f"Train {train} is running {r.get('delay_min')} minutes late: expected {r.get('expected')} "
                f"instead of {r.get('departs')} ({r.get('reason')}).")
    if status == "cancelled":
        return f"Train {train} is cancelled ({r.get('reason')})."
    if status == "unknown":
        return f"I do not know a train {train}."
    return f"Train {train} is on time ({r.get('departs')}, platform {r.get('platform')})."


class ScriptedModel(BaseLlm):
    """Stands in for Gemini. Decides from the agent's instruction and the messages it is given."""

    model: str = "scripted-demo-model"

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        await asyncio.sleep(PACE)
        system = str(llm_request.config.system_instruction or "")
        last = llm_request.contents[-1] if llm_request.contents else None
        tag = re.search(r"\[(desk|timetable|site|delays|notices|briefing|finder|seat_picker|seat_checker|notifier|announcer)\]", system)
        turn = getattr(self, "_" + tag.group(1), None) if tag else None
        yield turn(llm_request, system, _question(llm_request), _results(last)) if turn else _text("OK.")

    # station_desk: routes, and asks the web site reader (an agent used as a tool) itself.
    def _desk(self, request, system, question, results) -> LlmResponse:
        q = question.lower()
        if results:
            answer = results[0].response if results[0].name == "site_reader" else None
            if isinstance(answer, dict):
                answer = answer.get("result", answer)
            return _text(f"From the station web site: {answer}" if answer else "Done.")
        if "cancelled" in q or "rebook" in q:
            return _calls(("transfer_to_agent", {"agent_name": "rebooking_flow"}))
        if "passengers" in q:
            return _calls(("transfer_to_agent", {"agent_name": "announcer"}))
        if "strike" in q or "works" in q or "disruption" in q:
            return _calls(("transfer_to_agent", {"agent_name": "disruption_watch"}))
        if any(word in q for word in ("lost property", "lift", "bike", "opening hours", "open on")):
            site = _between(system, "Station web site:", "\n") or _between(system + "\n", "Station web site:", "\n")
            return _calls(("site_reader", {"request": f"Start at {site} and answer: {question}"}))
        if any(word in q for word in ("train", "platform", "late")):
            return _calls(("transfer_to_agent", {"agent_name": "timetable_agent"}))
        return _text("Hello, this is the rail desk. I can check trains, disruptions, the station web site, or rebook you.")

    def _timetable(self, request, system, question, results) -> LlmResponse:
        if not results:
            journey = _journey(question)
            if journey:
                after = re.search(r"\b(\d\d:\d\d)\b", question)
                return _calls(("search_trains", {"origin": journey[0], "destination": journey[1],
                                                 "after": after.group(1) if after else "08:00"}))
            # No train number in the question: use the one this conversation was about.
            train = _train(question) or _train(_between(system + "\n", "Last train discussed:", "\n"))
            if train:
                return _calls(("get_live_status", {"train_id": train}))
            return _text("Which train, or which journey, do you mean?")
        r = results[0].response or {}
        if results[0].name == "search_trains":
            trains = r.get("trains") or []
            if not trains:
                return _text(f"I found no train from {r.get('origin')} to {r.get('destination')} after {r.get('after')}.")
            return _text(f"Next trains from {r.get('origin')} to {r.get('destination')}: " + ", ".join(
                f"{t['train_id']} at {t['departs']} (arrives {t['arrives']})" for t in trains) + ".")
        if "platform" in question.lower() and r.get("platform"):
            when = r.get("expected") or r.get("departs")
            return _text(f"Train {r.get('train_id')} leaves from platform {r.get('platform')}, at {when}.")
        return _text(_status_line(r))

    # site_reader: reads the home page, follows the link that matches, then any "see ..." link.
    def _site(self, request, system, question, results) -> LlmResponse:
        pages = [r.response or {} for r in _all_results(request, "fetch_page")]
        if not pages:
            start = re.search(r"http://127\.0\.0\.1:\d+/\S*", question)
            if not start:
                return _text("I need the address of the station web site.")
            return _calls(("fetch_page", {"url": start.group(0)}))
        page = pages[-1]
        if page.get("error"):
            return _text(f"I could not read {page.get('url')}: {page.get('error')}")
        seen = {p.get("url") for p in pages}
        q, text = question.lower(), str(page.get("text", "")).lower()
        for link in page.get("links") or []:
            label = str(link.get("label", "")).lower()
            wanted = label in q if len(pages) == 1 else f"see {label}" in text
            if label and wanted and link.get("url") not in seen:
                return _calls(("fetch_page", {"url": link["url"]}))
        words = set(re.findall(r"[a-z]{4,}", q.split("answer:", 1)[-1]))
        best = []
        for p in pages[1:] or pages:
            lines = [line for line in str(p.get("text", "")).split("\n") if line != p.get("title")]
            score = lambda line: len(words & set(re.findall(r"[a-z]{4,}", line.lower())))  # noqa: E731
            if lines:
                best.append(max(lines, key=score))
        read = ", ".join(str(p.get("title")) for p in pages[1:] or pages)
        return _text(" ".join(best) + f" (Pages read: {read}.)")

    def _delays(self, request, system, question, results) -> LlmResponse:
        if not results:
            return _calls(("list_delays", {}))
        delays = (results[0].response or {}).get("delays") or []
        return _text("; ".join(
            f"train {d['train_id']} is {d['delay_min']} min late ({d['reason']})" if d.get("status") == "delayed"
            else f"train {d['train_id']} is cancelled ({d.get('reason')})" for d in delays) or "no delay right now")

    def _notices(self, request, system, question, results) -> LlmResponse:
        if not results:
            return _calls(("list_notices", {}))
        notices = (results[0].response or {}).get("notices") or []
        return _text("; ".join(f"{n['when']}: {n['what']} ({n['effect']})" for n in notices) or "no notice this week")

    def _briefing(self, request, system, question, results) -> LlmResponse:
        live, planned = _between(system, "LIVE:", "NOTICES:"), _between(system, "NOTICES:", "END")
        return _text(f"Disruptions at a glance.\nRight now: {live or 'nothing to report'}.\n"
                     f"Planned this week: {planned or 'nothing to report'}.")

    # rebooking_flow, step 1: two tools in the same turn.
    def _finder(self, request, system, question, results) -> LlmResponse:
        if not results:
            journey = _journey(question) or ("Northbridge", "Port Elm")
            after = re.search(r"\b(\d\d:\d\d)\b", question)
            return _calls(
                ("get_live_status", {"train_id": _train(question) or ""}),
                ("search_trains", {"origin": journey[0], "destination": journey[1],
                                   "after": after.group(1) if after else "08:00"}))
        by_name = {r.name: r.response or {} for r in results}
        trains = by_name.get("search_trains", {}).get("trains") or []
        return _text(_status_line(by_name.get("get_live_status", {})) + " Later trains: " + (", ".join(
            f"{t['train_id']} at {t['departs']}" for t in trains) or "none") + ".")

    # rebooking_flow, step 2 (the loop): try the next train that was not tried yet.
    def _seat_picker(self, request, system, question, results) -> LlmResponse:
        if results:
            r = results[0].response or {}
            if r.get("held"):
                return _text(f"Seat held: train {r['train_id']} at {r.get('departs')}, coach {r.get('coach')}, seat {r.get('seat')}.")
            return _text(f"Train {r.get('train_id')} is {r.get('reason', 'full')}.")
        candidates = re.findall(r"(\d{4}) at", _between(system, "ALTERNATIVES:", "TRIED:"))
        tried = re.findall(r"\d{4}", _between(system, "TRIED:", "END"))
        left = [c for c in candidates if c not in tried]
        return _calls(("try_hold_seat", {"train_id": left[0]})) if left else _text("No more trains to try.")

    def _seat_checker(self, request, system, question, results) -> LlmResponse:
        if results:
            return _text("The seat hunt is over.")
        status = _between(system, "STATUS:", "END").lower()
        if "seat held" in status or "no more trains" in status:
            return _calls(("exit_loop", {}))
        return _text("No seat yet, trying the next train.")

    # rebooking_flow, step 3.
    def _notifier(self, request, system, question, results) -> LlmResponse:
        held = _between(system, "HELD SEAT:", "END")
        address = re.search(r"[\w.+-]+@[\w.-]+\.\w+", question)
        to = address.group(0) if address else ""
        if results:
            r = results[0].response or {}
            if r.get("status") == "sent":
                return _text(f"You are rebooked: {held}. A confirmation was e-mailed to {r.get('to')}.")
            return _text(f"You are rebooked: {held}. The confirmation e-mail was refused ({r.get('error')}); ask the desk for a printout.")
        if not held:
            return _text("I could not hold a seat on any later train. Please come to the rail desk.")
        if not to:
            return _text(f"You are rebooked: {held}. Give me an e-mail address and I will send the confirmation.")
        return _calls(("send_email", {"to": to, "subject": f"Your new seat: {held.split(',')[0]}",
                                      "body": f"Hello,\n\nYour train was cancelled. You are now booked on {held}.\n\nThe rail desk"}))

    # announcer: three e-mails in one turn; one is refused, so a note is left at the desk instead.
    def _announcer(self, request, system, question, results) -> LlmResponse:
        train = _train(question) or ""
        platform = re.search(r"platform (\w+)", question)
        news = f"Train {train} now leaves from platform {platform.group(1) if platform else '?'}."
        if not results:
            return _calls(("list_passengers", {"train_id": train}))
        if results[0].name == "list_passengers":
            people = (results[0].response or {}).get("passengers") or []
            if not people:
                return _text(f"Nobody is booked on train {train}.")
            return _calls(*[("send_email", {"to": p["email"], "subject": f"Platform change for train {train}",
                                            "body": f"Hello {p['name']},\n\n{news}\n\nThe rail desk"}) for p in people])
        sent = [r.response for r in _all_results(request, "send_email")]
        refused = [r for r in sent if r.get("status") != "sent"]
        people = {p["email"]: p["name"] for r in _all_results(request, "list_passengers")
                  for p in (r.response or {}).get("passengers") or []}
        if results[0].name == "send_email" and refused:
            return _calls(*[("leave_desk_note", {"passenger": people.get(r.get("to"), r.get("to")), "note": news})
                            for r in refused])
        delivered = [r.get("to") for r in sent if r.get("status") == "sent"]
        report = f"Platform change sent for train {train}: {len(delivered)} e-mails delivered ({', '.join(delivered)})."
        for r in refused:
            report += (f" 1 refused by the mail server ({r.get('to')}: {r.get('smtp_code')} {r.get('error')}), "
                       f"so I left a note for {people.get(r.get('to'), 'that passenger')} at the rail desk.")
        return _text(report)


_model = ScriptedModel()

# Agents that do one job inside a flow never hand the passenger to someone else. Saying so
# also keeps the demo running on ADK 2.0 and 2.1, which trip over a neighbour that is a
# Sequential / Parallel / Loop agent when they list hand-off targets.
_STAYS = {"disallow_transfer_to_parent": True, "disallow_transfer_to_peers": True}

timetable_agent = LlmAgent(
    name="timetable_agent",
    model=_model,
    description="Finds the next trains and says whether a train is late.",
    instruction="[timetable] You answer timetable questions with search_trains and get_live_status, never from memory.\n"
                "Last train discussed: {last_train?}\n",
    tools=[search_trains, get_live_status],
    disallow_transfer_to_peers=True,
)

site_reader = LlmAgent(
    name="site_reader",
    model=_model,
    description="Answers a question by reading the station's web site, following links when needed.",
    instruction="[site] Read the station web site with fetch_page. Start at the address you are given, "
                "follow the links you need, then answer from what the pages say.",
    tools=[fetch_page],
    after_tool_callback=armor.screen_page,
)

delay_monitor = LlmAgent(
    name="delay_monitor",
    model=_model,
    description="Checks which trains are late or cancelled right now.",
    instruction="[delays] List the live delays with list_delays.",
    tools=[list_delays],
    output_key="delays",
    **_STAYS,
)

notice_monitor = LlmAgent(
    name="notice_monitor",
    model=_model,
    description="Checks the planned works and strike notices.",
    instruction="[notices] List this week's notices with list_notices.",
    tools=[list_notices],
    output_key="notices",
    **_STAYS,
)

disruption_scan = ParallelAgent(
    name="disruption_scan",
    description="Looks at live delays and planned notices at the same time.",
    sub_agents=[delay_monitor, notice_monitor],
)

briefing_writer = LlmAgent(
    name="briefing_writer",
    model=_model,
    description="Merges delays and notices into one short briefing.",
    instruction="[briefing] Write one short briefing from both lists.\nLIVE: {delays?}\nNOTICES: {notices?}\nEND",
    output_key="briefing",
    **_STAYS,
)

disruption_watch = SequentialAgent(
    name="disruption_watch",
    description="Gives an overview of strikes, works and delays: scan both sources, then merge.",
    sub_agents=[disruption_scan, briefing_writer],
)

alternatives_finder = LlmAgent(
    name="alternatives_finder",
    model=_model,
    description="Confirms the cancelled train and lists the later trains.",
    instruction="[finder] Check the passenger's train with get_live_status and list later trains with search_trains, in one go.",
    tools=[get_live_status, search_trains],
    output_key="alternatives",
    **_STAYS,
)

seat_picker = LlmAgent(
    name="seat_picker",
    model=_model,
    description="Tries to hold a seat on the next train not tried yet.",
    instruction="[seat_picker] Call try_hold_seat for the first alternative that was not tried yet.\n"
                "ALTERNATIVES: {alternatives?}\nTRIED: {seats_tried?}\nEND",
    tools=[try_hold_seat],
    output_key="seat_status",
    **_STAYS,
)

seat_checker = LlmAgent(
    name="seat_checker",
    model=_model,
    description="Stops the hunt as soon as a seat is held.",
    instruction="[seat_checker] If a seat is held, or no train is left, call exit_loop. Otherwise say we keep looking.\n"
                "STATUS: {seat_status?}\nEND",
    tools=[exit_loop],
    **_STAYS,
)

seat_hunt = LoopAgent(
    name="seat_hunt",
    description="Tries train after train until a seat is held.",
    sub_agents=[seat_picker, seat_checker],
    max_iterations=5,
)

notifier = LlmAgent(
    name="notifier",
    model=_model,
    description="E-mails the passenger the confirmation of the new seat.",
    instruction="[notifier] Send the passenger a confirmation of the held seat with send_email.\nHELD SEAT: {held_seat?}\nEND",
    tools=[send_email],
    before_tool_callback=armor.screen_recipient,
    output_key="confirmation",
    **_STAYS,
)

rebooking_flow = SequentialAgent(
    name="rebooking_flow",
    description="Rebooks a passenger whose train is cancelled: find later trains, hunt for a seat, confirm by e-mail.",
    sub_agents=[alternatives_finder, seat_hunt, notifier],
)

announcer = LlmAgent(
    name="announcer",
    model=_model,
    description="Tells every passenger of a train about a change, by e-mail.",
    instruction="[announcer] List the train's passengers, e-mail each of them, and when an address is refused "
                "leave a note at the desk instead. Report what was sent.",
    tools=[list_passengers, send_email, leave_desk_note],
    before_tool_callback=armor.screen_recipient,
    disallow_transfer_to_peers=True,
)

root_agent = LlmAgent(
    name="station_desk",
    model=_model,
    description="The rail desk: understands the request and sends it to the right specialist.",
    instruction="[desk] You are the rail desk of Northbridge station. Train times and delays go to timetable_agent, "
                "strikes and works to disruption_watch, a cancelled train to rebooking_flow, a message for a train's "
                "passengers to announcer. For anything about the station itself, ask site_reader.\n"
                "Station web site: {site_url?}\n",
    sub_agents=[timetable_agent, disruption_watch, rebooking_flow, announcer],
    tools=[AgentTool(agent=site_reader)],
    before_model_callback=armor.screen_prompt,
)
