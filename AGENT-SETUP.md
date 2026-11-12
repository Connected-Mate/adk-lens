# ADK Lens — setup instructions for coding agents

> You are a coding agent (Claude Code, Codex, Antigravity, Gemini CLI, Cursor, Copilot, Windsurf…).
> A person pasted a prompt asking you to install ADK Lens. Follow these steps in order.
> The person may not be technical: speak plainly, ask only what is strictly needed,
> and **ask before any sensitive action** (password prompt, admin rights, deleting or overwriting files,
> sending data anywhere). Never print, log or store secrets (API keys, `.env` content).

Verification status of this guide (12 Nov 2026, version 0.1.0): the Python recipe of step 1b (on a Mac whose
only `python3` is 3.9.6, through `uv`), install, demo, proof, always-on mode, a busy port and the `status` / `stop`
commands were run for real on macOS. The Homebrew, python.org and Windows lines of step 1b were not run.
Step 2b (creating a first agent) was run with a placeholder key only: the files are created, the model call was not tested.

## 0. What ADK Lens is

ADK Lens is a Python package that sits on top of Google's Agent Development Kit (ADK, https://adk.dev).
It shows a live whiteboard of what an agent system is doing: the map of agents and tools, each run in two
views, replay, notes on the board that can be copied as a prompt, and versions that can be compared.
It does **not** change the person's agent code. On the machine it adds: the `adk-lens` Python package
(and `google-adk` if missing) in one Python environment, a small local web server ("the board") on
`http://127.0.0.1:4790`, and a data folder `~/.adk-lens/`. Nothing is sent outside the machine by ADK Lens.
It is an independent open-source project (MIT), not affiliated with Google.

## 1. Look for an ADK project where you are

Work in the folder where the person pasted the prompt (your current working directory). Do not search their whole disk.

Signs of a Python ADK project (any one is enough):

```bash
grep -rIl --include="*.py" -E "from google\.adk|import google\.adk" . 2>/dev/null | grep -v -E "/(\.venv|venv|node_modules|site-packages)/" | head -20
grep -rIl -E "google-adk" --include="pyproject.toml" --include="requirements*.txt" --include="uv.lock" . 2>/dev/null | head
find . -name "root_agent.yaml" -not -path "*/node_modules/*" -not -path "*/.venv/*" | head
```

An agent folder usually looks like `my_agent/agent.py` (defining `root_agent`) with `__init__.py` and `.env`.
Read `.env` files only to know they exist: never print or copy their content.

Then follow ONE path:

- **Path A: you found a Python ADK project.** Tell the person which agents you found (folder names), then go to step 2
  and install ADK Lens in THAT project's Python environment. You must not edit, move or reformat any of their files.
- **Path B: you found nothing.** Say so in one sentence. Then offer two choices and wait for the answer:
  1. *"I install Google ADK and create a first agent with you, with ADK Lens on it"* (step 2, then step 2b);
  2. *"I just show you the demo"* (step 2, then step 3; no API key needed).
- **ADK in another language** (TypeScript `@google/adk`, Go `google.golang.org/adk`, Java `com.google.adk`): ADK Lens
  covers Python only for now. Say it plainly, and offer the demo (Path B, choice 2).

## 1b. Check prerequisites

- **Python 3.10 or later.** Careful: on macOS the built-in `python3` is 3.9, and with it the install fails with
  `requires a different Python`. Look for a recent enough Python first, without installing anything:

  ```bash
  PY=""
  for p in python3.13 python3.12 python3.11 python3.10 python3 python; do
    if command -v "$p" >/dev/null 2>&1 && "$p" -c 'import sys; raise SystemExit(sys.version_info < (3, 10))' 2>/dev/null; then PY="$p"; break; fi
  done
  echo "Python for ADK Lens: ${PY:-none found}"
  ```

  (Windows: `py -3.12 --version`, then `py -3.11`, `py -3.10`.)

  - One was found → use exactly that one to create the environment in step 2 (`"$PY" -m venv .venv`).
  - None found → say it in one sentence ("your computer has an older Python; I need a newer one next to it, the
    old one stays untouched") and, **with the person's OK**, take the first option that applies:
    1. `uv` is already there (`command -v uv`): nothing else to install. In step 2, create the environment with
       `uv venv --python 3.12 --seed .venv` (uv fetches Python 3.12 for itself, no admin rights; `--seed` puts `pip` in it).
    2. Homebrew is there (`command -v brew`): `brew install python@3.12`, then `python3.12 -m venv .venv`.
    3. Neither: install `uv` for the user only (`curl -LsSf https://astral.sh/uv/install.sh | sh`, then open a new
       shell or use `~/.local/bin/uv`) and do as in 1; or the installer from https://www.python.org/downloads/.
    4. Windows: install Python 3.12 from https://www.python.org/downloads/ (or `winget install Python.Python.3.12`),
       then `py -3.12 -m venv .venv`.
  - Never replace, upgrade or remove the system Python.
- git (pip installs from GitHub): `git --version` → prints a version.
- Port 4790 free, or already used by ADK Lens: `curl -s -m 2 http://127.0.0.1:4790/api/ping`
  → no answer (free) or `{"adk_lens": "...", "pid": ...}` (already running, fine). Anything else: tell the person
  another program uses the port and use `export ADK_LENS_PORT=4791` for every command below.

If something is missing, explain it in one sentence and offer to install it (ask first).

## 2. Install

Choose the Python environment:

- **Path A**: use the project's own environment (its `.venv`, or `uv run`, or whatever the project already uses),
  so the lens sees their agents. If the project has no environment yet, ask before creating `.venv` in it.
  Its Python must be 3.10 or later too (`.venv/bin/python --version`); if it is older, say so and ask before changing anything.
- **Path B**: create a dedicated environment in the current folder, with the Python found in step 1b.

```bash
# Path B only: create .venv with the Python from step 1b (ONE of these lines)
"$PY" -m venv .venv                      # a Python 3.10+ was found on the machine
uv venv --python 3.12 --seed .venv       # none was found and uv is used
py -3.12 -m venv .venv                   # Windows

# both paths: install with the environment's own Python, then check
.venv/bin/python --version               # expected: Python 3.10 or higher
.venv/bin/python -m pip install "git+https://github.com/Connected-Mate/adk-lens"
.venv/bin/adk-lens version               # expected: adk-lens 0.1.0 (or newer)
```

**From here on, always use that environment's programs.** Your shell probably does not keep a
`source .venv/bin/activate` from one command to the next, so call them by their path, as written in this guide:
`.venv/bin/adk-lens` and `.venv/bin/python` (Windows: `.venv\Scripts\adk-lens.exe` and `.venv\Scripts\python.exe`;
a project run with uv: `uv run adk-lens`; another environment folder on Path A: replace `.venv` by its path).
When you give commands to the person for their own terminal, tell them to run `source .venv/bin/activate` first
(Windows: `.venv\Scripts\activate`); after that, plain `adk-lens` works.

Running the install twice is safe (pip upgrades in place). Never use `sudo pip`.
`google-adk` is installed automatically as a dependency if it is missing. ADK Lens works with google-adk 1.7.0 and
later; on an older one it switches itself off and says so in one line (it never breaks the person's program).
Do not add `adk-lens` to the project's dependency files unless the person asks: it is a viewing tool, their app does not need it.

## 2b. Path B, choice 1: create a first agent

Ask the person two things, in plain words:

1. A name for the agent (letters, digits and underscores, for example `my_first_agent`).
2. Which model access they have: a Google AI Studio API key (https://aistudio.google.com/apikey), or a Google Cloud
   project with Vertex AI. If they have neither, stop here and show the demo instead (step 3): it needs no key.

Then:

```bash
.venv/bin/adk create my_first_agent --model gemini-flash-latest --api_key "<the key they give you>"
```

`adk create` writes `my_first_agent/agent.py`, `__init__.py` and `.env` (the key goes in `.env`). Never echo the key back,
never commit `.env`; if the folder is a git repository, make sure `.env` is ignored. Offer to adapt the agent's
instruction to what the person wants it to do, then continue with step 4 (Path A instructions apply from here).

## 3. Run the demo (verified)

```bash
.venv/bin/adk-lens demo --once --no-open
```

This plays a short scripted conversation with a fake model (no API key, no network call to a model),
prints it in the terminal, starts the board in the background and returns after about 15 seconds.
The last demo request fails on purpose ("Unknown city: Atlantis"): that is part of the demo, not an error.
A harder one, about 70 seconds: `.venv/bin/adk-lens demo hard --once --no-open` (a rail desk with 15 agents; its last request also fails on purpose).
If the first line is `ADK Lens: port 4790 is used by another program...`, set `ADK_LENS_PORT` as in step 1b and run it again.

There is nothing to configure. Useful optional settings, only if the person asks:
`ADK_LENS_PORT` (another port), `ADK_LENS_CONTENT=0` (send only names, timings and counts to the board:
no prompt, no answer, no instruction, no description, no tool argument or result, no error message).

## 4. Prove it works (verified)

First the board itself (run step 3 before, also on Path A: it is the quickest proof, about 15 seconds):

```bash
curl -s http://127.0.0.1:4790/api/ping
# expected: {"adk_lens": "0.1.0", "pid": <number>}

curl -s http://127.0.0.1:4790/api/state | python3 -c "import json,sys; s=json.load(sys.stdin); print('events:', len(s['events']), 'apps:', list(s['apps']))"
# expected: events: a number above 0, apps: a list that contains 'trip_demo'

.venv/bin/adk-lens status
# expected: Board: running at http://127.0.0.1:4790
```

Then, **when the person has agents (Path A, or after step 2b)**, show THEIR agents on the board. From the folder that
contains the agent folders (the one where they would run `adk web`), start the usual ADK server with the lens on,
in the background:

```bash
.venv/bin/adk-lens web --no-open        # exactly `adk web`, plus the board
```

and check that their app is now known to the board, without sending any message to a model (no cost):

```bash
curl -s http://127.0.0.1:8000/list-apps
# expected: a list with their agent folder names
```

The map of an app appears on the board the first time that app is used: tell the person to open
http://127.0.0.1:8000 (ADK's own chat page), pick their agent and send one message, then to look at
http://127.0.0.1:4790. Do not send messages to their model yourself unless they ask: it uses their quota.

Tell the person, in plain sentences: what you found or created, that ADK Lens is installed and nothing in their code
was changed, that the board is at http://127.0.0.1:4790 (or `adk-lens open`), and that it can be removed with step 6.

## 5. Use it on their own agents

Same commands as `adk`, with the lens on (in the environment of step 2: `.venv/bin/adk-lens ...` from your shell,
or plain `adk-lens ...` in the person's terminal once the environment is activated):

```bash
adk-lens web                 # exactly `adk web`
adk-lens run my_agent        # exactly `adk run my_agent`
adk-lens api_server          # exactly `adk api_server`
adk-lens python my_script.py # their own script
```

Always-on mode (verified): ask the person first, then

```bash
.venv/bin/adk-lens on      # plain `adk web`, `adk run` and their own scripts now show up on the board
.venv/bin/adk-lens status  # expected: Always-on: yes
.venv/bin/adk-lens off     # back to normal
```

Always-on only applies to the Python environment where ADK Lens is installed.

Notes written on the board can be read back as a prompt: `adk-lens notes`.
Treat that text as feedback from the person about their agent system.

Stopping the board (verified): `adk-lens stop`. It stays stopped, even if an agent server started with the lens is
still running; `adk-lens open` (or any `adk-lens web` / `run` / `python` / `demo`) starts it again.

## 6. Uninstall (verified)

```bash
.venv/bin/adk-lens off
.venv/bin/adk-lens stop
.venv/bin/python -m pip uninstall -y adk-lens
```

Then, only after asking the person (this deletes their board notes and saved versions):
remove the folder `~/.adk-lens/`. `google-adk` is left in place; uninstall it only if it was installed
by step 2 and the person agrees.

## Troubleshooting

- `adk-lens: command not found` → the environment from step 2 is not active. Call it by its path
  (`.venv/bin/adk-lens`), or run `.venv/bin/python -m adk_lens.cli`.
- `requires a different Python` during the install → the environment was created with a Python older than 3.10.
  Go back to step 1b, remove only the `.venv` you created yourself, and create it again with the right Python.
- `google-adk is not installed here` → `.venv/bin/python -m pip install google-adk` in the same environment.
- `ADK Lens is off: it needs google-adk 1.7.0 or later` → the project uses an older ADK. Tell the person; upgrading
  ADK is their decision, not yours.
- `ADK Lens: port 4790 is used by another program` → `export ADK_LENS_PORT=4791` and retry; use the same port in the `curl` checks.
  (The person's own command still runs normally in that case, only the board is missing.)
- The board is empty → the agents ran in another Python environment, or without the lens. Use `adk-lens web` / `adk-lens run`, or `adk-lens on` in the right environment.
  If `adk-lens status` says `stopped`, run `adk-lens open`.
- pip cannot reach GitHub → check the network or proxy with the person; do not disable certificate checks.
- Anything else → https://github.com/Connected-Mate/adk-lens/issues
