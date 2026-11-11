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

Then open http://127.0.0.1:4790.

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
- **Two views of a run**: *Journey* follows where the prompt goes; *Linear* tells it as a plain story, one sentence per step.
- **Replay**: play, pause, step through any past request.
- **Whiteboard notes**: circle a zone, drop a comment or a question mark, then **copy everything as one prompt** for your coding agent (`adk-lens notes` prints it too).
- **Versions**: every time the shape of your app changes, a version is kept. Compare two of them.

## How it stays out of the way

- Your code is not edited and not wrapped. ADK builds its `Runner` as usual; the lens then adds one
  [plugin](https://adk.dev/plugins/) to that runner's plugin list. This is ADK's own extension point.
- The plugin only observes. Every callback returns `None` (ADK's "carry on"), and any error inside the lens is swallowed.
- Nothing waits on the lens: events go to an in-memory queue, a background thread sends them to a separate local process.
- Everything stays on your machine (`127.0.0.1`). No account, no telemetry. `ADK_LENS_CONTENT=0` keeps prompts, arguments
  and results out and only shows names and timings.
- Off switch: `adk-lens off`, or `ADK_LENS=0` for one command.

You can also add it by hand, the ADK way: `adk web --extra_plugins=adk_lens.LensPlugin`.

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

## Limits

- Python ADK only (1.7+; built and tested on 2.14). TypeScript, Go and Java are not covered.
- Tools inside a toolset (MCP, OpenAPI) appear on the map the first time they are used.
- Runs are kept in memory by the local board process (it stops by itself after 8 idle hours); notes and versions are saved in `~/.adk-lens/`.
- Local use only: the board has no login and listens on `127.0.0.1`.

The event format and the board's API are described in [PROTOCOL.md](PROTOCOL.md).

## License

MIT. Not affiliated with Google. "ADK" and "Agent Development Kit" refer to Google's open-source project.
