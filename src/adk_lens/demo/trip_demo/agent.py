"""A small multi-agent ADK app that needs no API key.

The "model" is scripted: it answers from a fixed script so the demo behaves the
same everywhere. Everything else (agents, tools, hand-offs, memory) is real ADK.
"""

from __future__ import annotations

import asyncio
from typing import AsyncGenerator

from google.adk.agents import LlmAgent, SequentialAgent
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

PACE = 0.9  # seconds of "thinking", so the whiteboard is watchable


def get_weather(city: str) -> dict:
    """Gives the weather forecast for a city."""
    if city.lower() == "atlantis":
        raise ValueError("Unknown city: Atlantis is not on the map")
    return {"city": city, "forecast": "sunny", "high_c": 24, "low_c": 15}


def search_places(city: str, interest: str) -> dict:
    """Finds places to visit in a city for a given interest."""
    return {"city": city, "interest": interest,
            "places": ["Old harbour walk", "Covered food market", "Hilltop viewpoint at sunset"]}


def _text(text: str) -> LlmResponse:
    return LlmResponse(
        content=types.Content(role="model", parts=[types.Part(text=text)]),
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=180 + len(text), candidates_token_count=max(8, len(text) // 4)),
    )


def _call(name: str, **args) -> LlmResponse:
    return LlmResponse(
        content=types.Content(role="model", parts=[types.Part(function_call=types.FunctionCall(name=name, args=args))]),
        usage_metadata=types.GenerateContentResponseUsageMetadata(prompt_token_count=210, candidates_token_count=14),
    )


class ScriptedModel(BaseLlm):
    """Stands in for Gemini. Decides from the agent's instruction and the last message."""

    model: str = "scripted-demo-model"

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        await asyncio.sleep(PACE)
        system = str(llm_request.config.system_instruction or "")
        last = llm_request.contents[-1] if llm_request.contents else None
        parts = list(getattr(last, "parts", None) or [])
        tool_result = next((p.function_response for p in parts if p.function_response), None)
        user_texts = [
            " ".join(p.text for p in (c.parts or []) if p.text)
            for c in llm_request.contents if c.role == "user"
        ]
        user_text = next((t for t in reversed(user_texts) if t.strip() and not t.startswith("For context:")), "").lower()
        city = "Atlantis" if "atlantis" in user_text else "Lisbon" if "lisbon" in user_text else "Marseille"

        if "[concierge]" in system:
            if tool_result is not None:
                yield _text("Done.")
            elif "weather" in user_text or "atlantis" in user_text:
                yield _call("transfer_to_agent", agent_name="weather_agent")
            elif "plan" in user_text or "trip" in user_text or "weekend" in user_text:
                yield _call("transfer_to_agent", agent_name="trip_planner")
            else:
                yield _text("Hello! I can check the weather or plan a short trip. Where would you like to go?")
        elif "[weather]" in system:
            if tool_result is None:
                yield _call("get_weather", city=city)
            elif "error" in str(tool_result.response).lower():
                yield _text(f"Sorry, I could not get the weather for {city}.")
            else:
                r = tool_result.response
                yield _text(f"{r.get('city', city)}: {r.get('forecast')}, {r.get('low_c')} to {r.get('high_c')} °C.")
        elif "[researcher]" in system:
            if tool_result is None:
                yield _call("search_places", city=city, interest="food and views")
            else:
                yield _text("Found: " + ", ".join(tool_result.response.get("places", [])))
        elif "[writer]" in system:
            yield _text(
                f"Your weekend in {city}:\n"
                "Saturday: old harbour walk, then lunch at the covered food market.\n"
                "Sunday: slow morning, hilltop viewpoint at sunset."
            )
        else:
            yield _text("OK.")


_model = ScriptedModel()

weather_agent = LlmAgent(
    name="weather_agent",
    model=_model,
    description="Answers weather questions for a city.",
    instruction="[weather] You give the weather. Always use the get_weather tool, never guess.",
    tools=[get_weather],
)

researcher = LlmAgent(
    name="researcher",
    model=_model,
    description="Looks for places worth visiting.",
    instruction="[researcher] Find three places to visit with the search_places tool.",
    tools=[search_places],
    output_key="places",
)

writer = LlmAgent(
    name="writer",
    model=_model,
    description="Writes the final day-by-day plan.",
    instruction="[writer] Write a short weekend plan from these places: {places?}",
    output_key="plan",
)

trip_planner = SequentialAgent(
    name="trip_planner",
    description="Plans a weekend: first research, then writing.",
    sub_agents=[researcher, writer],
)

root_agent = LlmAgent(
    name="concierge",
    model=_model,
    description="Welcomes the traveller and sends each request to the right specialist.",
    instruction="[concierge] You are a travel concierge. Weather questions go to weather_agent, trip planning goes to trip_planner.",
    sub_agents=[weather_agent, trip_planner],
)
