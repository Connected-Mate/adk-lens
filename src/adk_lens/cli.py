"""The `adk-lens` command.

    adk-lens demo                 play a demo (no API key) and show the lens
    adk-lens web [...]            exactly `adk web [...]`, with the lens on
    adk-lens run my_agent         exactly `adk run my_agent`, with the lens on
    adk-lens python my_script.py  run your own script with the lens on
    adk-lens on | off             always-on mode for plain `adk` and your scripts
    adk-lens notes                print the board's comments as a prompt for a coding agent
    adk-lens open | status | stop | clear
"""

from __future__ import annotations

import asyncio
import json
import os
import runpy
import sys
import webbrowser

from . import __version__, autoload, transport

HELP = __doc__

OWN = {"demo", "on", "off", "notes", "open", "status", "stop", "clear", "python", "hub", "help", "--help", "-h", "version", "--version"}


def _say(text: str = "") -> None:
    print(text, file=sys.stderr)


def _maybe_open(args: list[str]) -> list[str]:
    """Open the board in the browser when a person is at the keyboard."""
    wants = "--no-open" not in args and os.environ.get("ADK_LENS_OPEN", "1") not in ("0", "false", "no")
    args = [a for a in args if a not in ("--no-open", "--open")]
    if wants and sys.stderr.isatty() and transport.start_hub():
        try:
            webbrowser.open(transport.url())
        except Exception:
            pass
    return args


def _post(path: str) -> bool:
    import http.client

    try:
        conn = http.client.HTTPConnection("127.0.0.1", transport.port(), timeout=2)
        conn.request("POST", path, body=b"{}", headers={"Content-Type": "application/json", "X-ADK-Lens": __version__})
        ok = conn.getresponse().status == 200
        conn.close()
        return ok
    except Exception:
        return False


def _get(path: str):
    import http.client

    try:
        conn = http.client.HTTPConnection("127.0.0.1", transport.port(), timeout=3)
        conn.request("GET", path)
        data = json.loads(conn.getresponse().read())
        conn.close()
        return data
    except Exception:
        return None


def notes_as_prompt(notes) -> str:
    """Turn the saved board annotations into a prompt. The UI saves a ready-made
    `prompt` field; fall back to listing the raw items."""
    if not notes:
        return ""
    if isinstance(notes, dict) and isinstance(notes.get("prompt"), str) and notes["prompt"].strip():
        return notes["prompt"].strip()
    items = notes.get("items") if isinstance(notes, dict) else notes
    if not isinstance(items, list) or not items:
        return ""
    lines = ["Feedback from the ADK Lens board. Please take each point into account:", ""]
    for i, item in enumerate(items, 1):
        if not isinstance(item, dict):
            continue
        kind = item.get("kind") or item.get("type") or "comment"
        text = item.get("text") or item.get("comment") or ""
        target = item.get("target") or item.get("node") or item.get("anchor") or ""
        if isinstance(target, dict):
            target = target.get("name") or target.get("id") or json.dumps(target)
        lines.append(f"{i}. [{kind}] {text}" + (f" (about: {target})" if target else ""))
    return "\n".join(lines)


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    cmd = args[0] if args else "help"

    if cmd in ("help", "--help", "-h"):
        print(HELP)
        return 0
    if cmd in ("version", "--version"):
        print(f"adk-lens {__version__}")
        return 0

    if cmd == "hub":
        from . import hub

        return hub.main(args[1:])

    if cmd == "on":
        path = autoload.always_on_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("ADK Lens always-on. Delete this file or run `adk-lens off` to stop.\n")
        _say("ADK Lens is now always on: `adk web`, `adk run` and your own scripts show up on the board.")
        _say(f"Board: {transport.url()}   Turn off: adk-lens off")
        return 0
    if cmd == "off":
        try:
            autoload.always_on_file().unlink()
        except FileNotFoundError:
            pass
        _say("ADK Lens always-on mode is off. `adk-lens web` / `adk-lens run` still work.")
        return 0

    if cmd == "status":
        info = transport.ping()
        _say(f"Board:      {'running at ' + transport.url() if info else 'not running'}")
        _say(f"Always-on:  {'yes' if autoload.always_on_file().exists() else 'no'}")
        return 0
    if cmd == "stop":
        _say("Board stopped." if _post("/api/shutdown") else "The board was not running.")
        return 0
    if cmd == "clear":
        _say("Runs cleared." if _post("/api/clear") else "The board is not running.")
        return 0
    if cmd == "open":
        if not transport.start_hub():
            _say("Could not start the board.")
            return 1
        _say(f"Board: {transport.url()}")
        if "--no-open" not in args:
            webbrowser.open(transport.url())
        return 0
    if cmd == "notes":
        notes = _get("/api/notes")
        if notes is None:
            try:
                from .hub import data_dir

                notes = json.loads((data_dir() / "notes.json").read_text("utf-8"))
            except Exception:
                notes = None
        prompt = notes_as_prompt(notes)
        if not prompt:
            _say("No comments on the board yet.")
            return 0
        print(prompt)
        return 0

    # Everything below runs agents with the lens attached.
    os.environ["ADK_LENS"] = "1"  # inherited by child processes (e.g. `adk web --reload`)

    if cmd == "demo":
        rest = _maybe_open(args[1:])
        if not autoload.install():
            _say("google-adk is not installed here. Run: pip install google-adk")
            return 1
        if not transport.start_hub():
            _say("Could not start the board.")
            return 1
        os.environ["ADK_LENS_QUIET"] = "1"
        _say(f"\n  ADK Lens demo. Open {transport.url()}\n")
        from . import demo

        loops = 0
        try:
            while True:
                asyncio.run(demo.play())
                transport.flush(3.0)
                loops += 1
                if "--once" in rest:
                    break
                _say("\n  Demo finished. It replays in 20 s (Ctrl+C to quit; the board stays open).\n")
                import time

                time.sleep(20)
        except KeyboardInterrupt:
            pass
        transport.flush(3.0)
        return 0

    if cmd == "python":
        rest = _maybe_open(args[1:])
        if not rest:
            _say("Usage: adk-lens python my_script.py [args]  |  adk-lens python -m my.module [args]")
            return 2
        autoload.bootstrap()
        if rest[0] == "-m" and len(rest) > 1:
            sys.argv = rest[1:]
            runpy.run_module(rest[1], run_name="__main__", alter_sys=True)
        else:
            sys.argv = rest
            sys.path.insert(0, os.path.dirname(os.path.abspath(rest[0])))
            runpy.run_path(rest[0], run_name="__main__")
        return 0

    # Anything else is an `adk` command, passed through untouched.
    rest = _maybe_open(args)
    if not autoload.install():
        _say("google-adk is not installed here. Run: pip install google-adk")
        return 1
    try:
        from google.adk.cli import main as adk_main
    except Exception as error:
        _say(f"Could not load the adk command: {error}")
        return 1
    sys.argv = ["adk", *rest]
    result = adk_main()
    return int(result or 0)


if __name__ == "__main__":
    raise SystemExit(main())
