"""Demo: plays a few requests through a real ADK app with a scripted model."""

from __future__ import annotations

import asyncio
import logging

QUESTIONS = [
    "What's the weather in Lisbon this weekend?",
    "Plan a weekend trip to Marseille for me.",
    "And what's the weather in Atlantis?",
]


async def play(questions=None, pause: float = 2.5) -> None:
    from google.adk.runners import InMemoryRunner
    from google.genai import types

    from .trip_demo.agent import root_agent

    runner = InMemoryRunner(agent=root_agent, app_name="trip_demo")
    # The last question fails on purpose (to show an error on the board): keep ADK's traceback out of the terminal.
    logging.getLogger("google_adk").setLevel(logging.CRITICAL)
    for i, question in enumerate(questions or QUESTIONS):
        if i:
            await asyncio.sleep(pause)
        session = await runner.session_service.create_session(app_name="trip_demo", user_id="demo")
        print(f"  You: {question}")
        message = types.Content(role="user", parts=[types.Part(text=question)])
        try:
            async for event in runner.run_async(user_id="demo", session_id=session.id, new_message=message):
                if event.is_final_response() and event.content and event.content.parts:
                    text = " ".join(p.text for p in event.content.parts if p.text)
                    if text:
                        print(f"  {event.author}: {text}")
        except Exception as error:  # the Atlantis question fails on purpose
            print(f"  (run failed: {error})")
    await runner.close()
