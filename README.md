# ADK Lens

**A live whiteboard of what your ADK agents are doing. No change to your agent code.**

ADK Lens sits on top of Google's [Agent Development Kit](https://adk.dev). It draws your agents and tools as a board,
plays each request step by step, and lets you circle things, leave comments and hand them to your coding agent.

Site: https://connected-mate.github.io/adk-lens/ · [Français](https://connected-mate.github.io/adk-lens/fr/)

## Try it (no API key)

```bash
pip install "git+https://github.com/Connected-Mate/adk-lens"
adk-lens demo
```

Then open http://127.0.0.1:4790. Needs Python 3.10 or later (the `python3` that ships with macOS is 3.9:
[AGENT-SETUP.md](AGENT-SETUP.md), step 1b, shows how to get a newer one next to it).

Prefer to let your coding agent do it? Give it [AGENT-SETUP.md](AGENT-SETUP.md).

## Use it on your own agents

Use `adk-lens` wherever you type `adk`. Same commands, same options, plus the board:

```bash
adk-lens web                 # = adk web
adk-lens run my_agent        # = adk run my_agent
adk-lens api_server          # = adk api_server
adk-lens python my_script.py # your own script that builds a Runner
```

Or switch it on once, and plain `adk web`, `adk run` and your scripts show up on the board:

```bash
adk-lens on      # adk-lens off to undo
```

## What you get

- **Map**: agents, tools and workflows drawn automatically, lit up live as a request travels.
- **Two views of a run**: *Journey* follows where the prompt goes; *Story* tells it in plain words, one sentence per step.
- **Replay**: play, pause, step through any past request.
- **Whiteboard notes**: circle a zone, drop a comment or a question mark, then **copy everything as one prompt** for your coding agent (`adk-lens notes` prints it too).
- **Versions**: every time your app changes (an agent, a tool, a link, an instruction), a version is kept. Compare two
  of them. Going back to an earlier state brings that version back instead of creating a copy.

## How it stays out of the way

- Your code is not edited and not wrapped. ADK builds its `Runner` as usual; the lens then adds one
  [plugin](https://adk.dev/plugins/) to that runner's plugin list. This is ADK's own extension point.
- The plugin only observes. Every callback returns `None` (ADK's "carry on"), and any error inside the lens is swallowed.
- One more thing is watched, on ADK's side: the stream returned by `Runner.run_async` goes through a look-only relay.
  Every event and every exception reaches your code unchanged; the relay only notices that the stream is over, so a
  request that failed or was abandoned is never shown as "live" for ever (older ADK versions do not tell plugins).
- Nothing waits on the lens: events go to an in-memory queue, a background thread sends them to a separate local
  process. At exit the lens gives up after 0.3 s at most if the board does not answer.
- Everything stays on your machine (`127.0.0.1`). No account, no telemetry. `ADK_LENS_CONTENT=0` only sends names
  (agents, tools, models, memory keys), timings and counts: no prompt, no answer, no instruction, no description,
  no tool argument or result, no error message.
- Off switch: `adk-lens off`, or `ADK_LENS=0` for one command. `adk-lens stop` stops the board, and it stays stopped
  (agent programs that are still running do not bring it back) until you run `adk-lens open` or any other `adk-lens`
  command that starts it.
- If port 4790 belongs to another program, the lens says so in one line and stays off; your program runs as usual.
  Choose another port with `ADK_LENS_PORT=4791`.

You can also add it by hand, the ADK way: `adk web --extra_plugins=adk_lens.LensPlugin` (plugin only, without the
relay: on ADK before 2.5 a failed request is then closed only when the program ends).

## Commands

| Command | What it does |
|---|---|
| `adk-lens demo` | Plays a small multi-agent demo with a scripted model |
| `adk-lens <any adk command>` | Runs `adk` with the lens on |
| `adk-lens python script.py` | Runs your script with the lens on |
| `adk-lens on` / `off` | Always-on mode |
| `adk-lens notes` | Prints the board's comments as a prompt |
| `adk-lens open` / `status` / `clear` / `stop` | Open the board, check it, forget past runs, stop it |

Settings: `ADK_LENS_PORT` (default 4790), `ADK_LENS_CONTENT=0`, `ADK_LENS_QUIET=1`, `ADK_LENS_OPEN=0`.

## Remove it

```
adk-lens stop
adk-lens off
pip uninstall adk-lens
```

In that order: `stop` closes the board, `off` removes the always-on switch, then the package goes. Your agents were
never changed, so there is nothing to undo there. Notes and versions live in `~/.adk-lens`; delete that folder too if
you want nothing left.

## Limits

- Python ADK only, google-adk 1.7.0 or later (the first version with plugins). Built on 2.14; the demo and the
  test suite were also run on 1.7.0, 1.12, 1.18, 1.19, 1.22, 1.28, 1.39, 2.0.0, 2.1.0, 2.2 and 2.6. On an older ADK the lens switches
  itself off and says so in one line. TypeScript, Go and Java are not covered.
- What older ADK versions cannot tell the lens: on 1.7 and 1.8 a failing tool is not marked on its own (the request is
  still shown as failed, with the error).
- ADK 2.0.0 and 2.1.0 only: an agent that sits next to a `SequentialAgent` (or a parallel or loop agent) under the
  same parent fails with `object has no attribute 'mode'`. This is ADK's own bug, with or without the lens, fixed in
  ADK 2.2. If you must stay on 2.0 or 2.1, set `disallow_transfer_to_peers=True` on that agent. The demo does it, so
  it runs on every supported version.
- A program that lives for less than a second while no board is running may be missing from the board: the lens
  never holds a program back when it exits. Start the board first (`adk-lens open`).
- If the agent program is killed in the middle of a request, the board closes that request a few seconds later and
  marks it as interrupted.
- Tools inside a toolset (MCP, OpenAPI) appear on the map the first time they are used.
- Runs are kept in memory by the local board process (it stops by itself after 8 idle hours); notes and versions are saved in `~/.adk-lens/`.
- Local use only: the board has no login and listens on `127.0.0.1`.

The event format and the board's API are described in [PROTOCOL.md](PROTOCOL.md).

## License

MIT. Not affiliated with Google. "ADK" and "Agent Development Kit" refer to Google's open-source project.
