"""Safety checks of the rail desk, plugged into the agents with ADK's own callbacks.

Three guards, each a plain ADK callback:

- `screen_prompt` (before the model): refuses a request that tries to override the desk's rules.
- `screen_page` (after a tool): removes instructions hidden in a web page before the agent reads it.
- `screen_recipient` (before a tool): refuses to e-mail an address outside the passengers' domain.

The checks are local patterns so that the demo needs no account. In a real project `screen()`
is where a call to a screening service such as Google Cloud Model Armor goes (it needs a Google
Cloud project); the callbacks around it stay the same.
"""

from __future__ import annotations

import re

from google.adk.models.llm_response import LlmResponse
from google.genai import types

ALLOWED_MAIL_DOMAIN = "example.com"

_OVERRIDE = re.compile(
    r"ignore (all |any )?(of )?(your |the |my )?(previous |prior |earlier |above )?(instructions|rules)"
    r"|disregard (your |the |all )?(previous |prior )?(instructions|rules)"
    r"|(reveal|show|print) (me )?(your |the )?system prompt"
    r"|note to (ai|the ai|ai assistants)"
    r"|you are now ", re.I)


def screen(text: str) -> dict:
    """Says whether a text tries to take control of the agent. Stand-in for a screening service."""
    found = _OVERRIDE.search(text or "")
    if found:
        return {"verdict": "blocked", "reason": "prompt injection", "match": found.group(0)}
    return {"verdict": "clean"}


def _last_user_text(llm_request) -> str:
    for content in reversed(getattr(llm_request, "contents", None) or []):
        if content.role != "user":
            continue
        text = " ".join(p.text for p in (content.parts or []) if p.text).strip()
        if text and not text.startswith("For context:"):
            return text
    return ""


def screen_prompt(callback_context, llm_request):
    """before_model_callback: a request that tries to override the rules never reaches the model."""
    check = screen(_last_user_text(llm_request))
    if check["verdict"] != "blocked":
        return None
    callback_context.state["armor_last_block"] = check["reason"]
    return LlmResponse(content=types.Content(role="model", parts=[types.Part(
        text="I can't help with that. The desk's safety check stopped this request "
             f"({check['reason']}): I only follow the station's own rules.")]))


def screen_page(tool, args, tool_context, tool_response):
    """after_tool_callback: instructions hidden in a web page are removed before the agent reads it."""
    if getattr(tool, "name", "") != "fetch_page" or not isinstance(tool_response, dict):
        return None
    lines = str(tool_response.get("text", "")).split("\n")
    kept = [line for line in lines if screen(line)["verdict"] == "clean"]
    if len(kept) == len(lines):
        return None
    return {**tool_response, "text": "\n".join(kept),
            "safety_check": {"removed_lines": len(lines) - len(kept), "reason": "instructions hidden in the page"}}


def screen_recipient(tool, args, tool_context):
    """before_tool_callback: no e-mail leaves for an address outside the passengers' domain."""
    if getattr(tool, "name", "") != "send_email":
        return None
    to = str((args or {}).get("to", ""))
    if to.lower().endswith("@" + ALLOWED_MAIL_DOMAIN):
        return None
    return {"status": "blocked", "to": to, "error": f"Safety check: {to} is not a passenger address."}
