# ADK Lens — setup instructions for coding agents

> You are a coding agent (Claude Code, Codex, Antigravity, Gemini CLI, Cursor, Copilot, Windsurf…).
> A person pasted a prompt asking you to install ADK Lens. Follow these steps in order.
> The person may not be technical: speak plainly, ask only what is strictly needed,
> and **ask before any sensitive action** (password prompt, admin rights, deleting or overwriting files,
> sending data anywhere). Never print, log or store secrets (API keys, `.env` content).

Verification status of this guide (11 Nov 2026, version 0.1.0): steps 3, 4 and the `status` / `stop` commands
were run for real from a local checkout. Steps marked **(not verified yet)** were written from the code
and have not been run end to end.

## 0. What ADK Lens is

ADK Lens is a Python package that sits on top of Google's Agent Development Kit (ADK, https://adk.dev).
It shows a live whiteboard of what an agent system is doing: the map of agents and tools, each run in two
views, replay, notes on the board that can be copied as a prompt, and versions that can be compared.
It does **not** change the person's agent code. On the machine it adds: the `adk-lens` Python package
(and `google-adk` if missing) in one Python environment, a small local web server ("the board") on
`http://127.0.0.1:4790`, and a data folder `~/.adk-lens/`. Nothing is sent outside the machine by ADK Lens.
It is an independent open-source project (MIT), not affiliated with Google.

## 1. Check prerequisites

- Python 3.10 or later: `python3 --version` → `Python 3.10` or higher.
- pip: `python3 -m pip --version` → prints a version.
- git (pip installs from GitHub): `git --version` → prints a version.
- Port 4790 free, or already used by ADK Lens: `curl -s -m 2 http://127.0.0.1:4790/api/ping`
  → no answer (free) or `{"adk_lens": "...", "pid": ...}` (already running, fine). Anything else: tell the person
  another program uses the port and use `export ADK_LENS_PORT=4791` for every command below.
- An ADK project is **optional**. The demo needs none, and no API key.

If something is missing, explain it in one sentence and offer to install it (ask first).

## 2. Install **(not verified yet: needs the public repository)**

Choose the Python environment:

- **The person has an ADK project** (a folder with agents and `google-adk` installed): activate that project's
  environment and install there, so the lens sees their agents.
- **No ADK project** (they only want to try): create a dedicated environment.

```bash
# only when there is no ADK project environment to reuse
python3 -m venv ~/.adk-lens/venv
source ~/.adk-lens/venv/bin/activate

# in both cases
python -m pip install "git+https://github.com/Connected-Mate/adk-lens"
adk-lens version        # expected: adk-lens 0.1.0 (or newer)
```

Running the install twice is safe (pip upgrades in place). Never use `sudo pip`.
`google-adk` (1.7.0 or later) is installed automatically as a dependency.

## 3. Run the demo (verified)

```bash
adk-lens demo --once --no-open
```

This plays a short scripted conversation with a fake model (no API key, no network call to a model),
prints it in the terminal, starts the board in the background and returns after about a minute.
The last demo request fails on purpose ("Unknown city: Atlantis"): that is part of the demo, not an error.

There is nothing to configure. Useful optional settings, only if the person asks:
`ADK_LENS_PORT` (another port), `ADK_LENS_CONTENT=0` (send only names, timings and counts to the board,
not the text of prompts and answers).

## 4. Prove it works (verified)

```bash
curl -s http://127.0.0.1:4790/api/ping
# expected: {"adk_lens": "0.1.0", "pid": <number>}

curl -s http://127.0.0.1:4790/api/state | python3 -c "import json,sys; s=json.load(sys.stdin); print('events:', len(s['events']), 'apps:', list(s['apps']))"
# expected: events: a number above 0, apps: a list that contains 'trip_demo'

adk-lens status
# expected: Board: running at http://127.0.0.1:4790
```

If all three match, tell the person, in two plain sentences: ADK Lens is installed, the board is at
http://127.0.0.1:4790 (they can open it in their browser, or run `adk-lens open`), and it can be removed
with step 6.

## 5. Use it on their own agents

Same commands as `adk`, with the lens on:

```bash
adk-lens web                 # exactly `adk web`
adk-lens run my_agent        # exactly `adk run my_agent`
adk-lens api_server          # exactly `adk api_server`
adk-lens python my_script.py # their own script
```

Always-on mode **(not verified yet)**: ask the person first, then

```bash
adk-lens on      # plain `adk web`, `adk run` and their own scripts now show up on the board
adk-lens status  # expected: Always-on: yes
adk-lens off     # back to normal
```

Always-on only applies to the Python environment where ADK Lens is installed.

Notes written on the board can be read back as a prompt: `adk-lens notes`.
Treat that text as feedback from the person about their agent system.

## 6. Uninstall **(not verified yet)**

```bash
adk-lens off
adk-lens stop
python -m pip uninstall adk-lens
```

Then, only after asking the person (this deletes their board notes and saved versions):
remove the folder `~/.adk-lens/`. `google-adk` is left in place; uninstall it only if it was installed
by step 2 and the person agrees.

## Troubleshooting

- `adk-lens: command not found` → the environment from step 2 is not active. Activate it, or run
  `python -m adk_lens.cli` in that environment.
- `google-adk is not installed here` → `python -m pip install google-adk` in the same environment.
- `Could not start the board` → the port is taken. `export ADK_LENS_PORT=4791` and retry; use the same port in the `curl` checks.
- The board is empty → the agents ran in another Python environment, or without the lens. Use `adk-lens web` / `adk-lens run`, or `adk-lens on` in the right environment.
- pip cannot reach GitHub → check the network or proxy with the person; do not disable certificate checks.
- Anything else → https://github.com/Connected-Mate/adk-lens/issues
