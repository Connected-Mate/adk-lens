"""Demos: play a few requests through a real ADK app with a scripted model.

`play()` is the simple one (a travel concierge). `play_hard()` is the hard one (a rail
desk: many agents, a local web site, e-mail over SMTP to a local sink, failures).
"""

from __future__ import annotations

import asyncio
import logging

QUESTIONS = [
    "What's the weather in Lisbon this weekend?",
    "Plan a weekend trip to Marseille for me.",
    "And what's the weather in Atlantis?",
]

# The hard demo. `True` = asked in the same conversation as the request before (memory).
HARD_REQUESTS = [
    ("When are the next trains from Northbridge to Port Elm after 08:00?", False),
    ("Is train 6607 late?", False),
    ("And which platform does it leave from?", True),
    ("I left my bag on a train yesterday. Where is lost property, and is it open on Sunday?", False),
    ("Any strikes or works I should know about this week?", False),
    ("My 09:25 train 6612 from Northbridge to Port Elm is cancelled. Rebook me on the next train "
     "with a free seat and confirm to maya.ortiz@example.com.", False),
    ("Train 6620 now leaves from platform 7 instead of 3. Tell its three passengers by e-mail.", False),
    ("And the next trains from Northbridge to Saltmarsh Halt after 18:00?", False),
]


async def _ask(runner, session, question: str) -> dict:
    """Send one request, print the conversation, return what happened."""
    from google.genai import types

    print(f"  You: {question}")
    outcome = {"question": question, "session": session.id, "answers": [], "error": None}
    message = types.Content(role="user", parts=[types.Part(text=question)])
    try:
        async for event in runner.run_async(user_id="demo", session_id=session.id, new_message=message):
            if event.is_final_response() and event.content and event.content.parts:
                text = " ".join(p.text for p in event.content.parts if p.text)
                if text:
                    outcome["answers"].append((event.author, text))
                    print(f"  {event.author}: {text}")
    except Exception as error:  # some requests fail on purpose
        outcome["error"] = f"{type(error).__name__}: {error}"
        print(f"  (run failed: {error})")
    return outcome


class _QuietAdk:
    """Keep the demo's terminal to the conversation: a request fails on purpose (ADK would
    print its traceback), and recent ADK versions log a tuning hint (context_cache_config)
    when the runner is built. Only the demos do this; the level is put back at the end."""

    def __enter__(self):
        self._log = logging.getLogger("google_adk")
        self._before = self._log.level
        self._log.setLevel(logging.CRITICAL)

    def __exit__(self, *exc):
        self._log.setLevel(self._before)


async def _close(runner) -> None:
    try:
        await runner.close()
    except Exception:
        pass


async def play(questions=None, pause: float = 2.5) -> None:
    from google.adk.runners import InMemoryRunner

    from .trip_demo.agent import root_agent

    with _QuietAdk():
        runner = InMemoryRunner(agent=root_agent, app_name="trip_demo")
        for i, question in enumerate(questions or QUESTIONS):
            if i:
                await asyncio.sleep(pause)
            session = await runner.session_service.create_session(app_name="trip_demo", user_id="demo")
            await _ask(runner, session, question)
        await _close(runner)


async def play_hard(requests=None, pause: float = 2.5) -> dict:
    """Play the rail desk demo once. Its web site and mail sink run on 127.0.0.1 only while it plays.

    Returns what happened: one entry per request, the e-mails the sink accepted, the
    addresses it refused and the pages that were really fetched.
    """
    from google.adk.runners import InMemoryRunner

    from .rail_desk import services
    from .rail_desk.agent import root_agent

    outcomes = []
    with _QuietAdk(), services.running() as live:
        runner = InMemoryRunner(agent=root_agent, app_name="rail_desk")
        session = None
        try:
            for i, (question, same_conversation) in enumerate(requests or HARD_REQUESTS):
                if i:
                    await asyncio.sleep(pause)
                if session is None or not same_conversation:
                    session = await runner.session_service.create_session(
                        app_name="rail_desk", user_id="demo", state={"site_url": live.site.url})
                outcomes.append(await _ask(runner, session, question))
        finally:
            await _close(runner)
    return {"requests": outcomes, "mail": list(live.mail.messages), "refused": list(live.mail.refused),
            "pages": list(live.site.hits)}
