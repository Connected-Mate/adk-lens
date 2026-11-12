"""Attach the lens to every ADK Runner without editing anyone's code.

`install()` wraps `Runner.__init__` so that, once ADK has built a runner exactly
as usual, the lens plugin is added to that runner's own plugin list. The user's
`App`, agents and plugin list objects are left untouched.

It also lets `Runner.run_async` pass through a look-only relay (`_watch_runs`): every
event and every exception goes to the caller unchanged; the relay only notices
that the stream is over, so a request that failed or was abandoned is reported
as finished on every ADK version.

`bootstrap()` is what the `.pth` file calls at interpreter start. It does nothing
unless the lens is switched on, and it never imports ADK by itself: it waits
for the program to import `google.adk.runners`.
"""

from __future__ import annotations

import contextvars
import os
import sys
from pathlib import Path

_installed = False
_TARGET = "google.adk.runners"
MIN_ADK = (1, 7, 0)  # first ADK with plugins
_current_run: contextvars.ContextVar = contextvars.ContextVar("adk_lens_run", default=None)


def always_on_file() -> Path:
    return Path(os.environ.get("ADK_LENS_HOME") or Path.home() / ".adk-lens") / "enabled"


def enabled() -> bool:
    flag = os.environ.get("ADK_LENS", "").strip().lower()
    if flag in ("0", "false", "off", "no"):
        return False
    if flag in ("1", "true", "on", "yes"):
        return True
    try:
        return always_on_file().exists()
    except Exception:
        return False


def install() -> bool:
    """Patch Runner now (imports ADK). Safe to call many times."""
    global _installed
    if _installed:
        return True
    try:
        from google.adk import runners
    except Exception:
        return False
    _patch(runners)
    return _installed


def _adk_version() -> tuple | None:
    try:
        from importlib.metadata import version

        numbers = []
        for piece in version("google-adk").split(".")[:3]:
            digits = "".join(ch for ch in piece if ch.isdigit()) if piece[:1].isdigit() else ""
            numbers.append(int(digits or 0))
        return tuple(numbers)
    except Exception:
        return None


def supported() -> bool:
    """False on an ADK too old for the lens (says so once, on stderr)."""
    found = _adk_version()
    if found is None or found >= MIN_ADK:
        return True
    if os.environ.get("ADK_LENS_QUIET", "").lower() not in ("1", "true", "yes"):
        try:
            sys.stderr.write(
                "ADK Lens is off: it needs google-adk %s or later, this environment has %s.\n"
                % (".".join(map(str, MIN_ADK)), ".".join(map(str, found)))
            )
        except Exception:
            pass
    return False


def _watch_runs(Runner) -> None:
    """Let `Runner.run_async` pass through a look-only relay (see the module docstring)."""
    original = Runner.run_async
    if getattr(original, "_adk_lens", False):
        return
    import functools
    import inspect

    if not inspect.isasyncgenfunction(original):
        return  # an ADK we do not know: leave it alone

    @functools.wraps(original)
    async def lens_run_async(self, *args, **kwargs):
        agen = original(self, *args, **kwargs)
        holder: dict = {}
        error = None
        interrupted = False
        try:
            _current_run.set(holder)  # read by the plugin's before_run_callback, during the first step
        except Exception:
            pass
        try:
            async for event in agen:
                if "run" not in holder:
                    try:
                        holder["run"] = str(event.invocation_id or "") or None
                    except Exception:
                        pass
                yield event
        except Exception as exc:
            error = exc
            raise  # the caller gets the very same exception
        except BaseException:  # the caller stopped reading (break, cancel, Ctrl+C)
            interrupted = True
            raise
        finally:
            try:
                if interrupted:
                    await agen.aclose()  # same clean-up the caller would have triggered directly
            finally:
                try:
                    from .plugin import lens_plugin

                    lens_plugin.run_finished(holder.get("run"), error, interrupted)
                except Exception:
                    pass

    lens_run_async._adk_lens = True
    Runner.run_async = lens_run_async


def _patch(runners_module) -> None:
    global _installed
    if _installed:
        return
    try:
        Runner = runners_module.Runner
        original_init = Runner.__init__
        if getattr(original_init, "_adk_lens", False):
            _installed = True
            return
        if not supported():
            return

        def lens_init(self, *args, **kwargs):
            original_init(self, *args, **kwargs)
            try:
                _attach(self)
            except Exception:
                pass

        lens_init._adk_lens = True
        lens_init.__wrapped__ = original_init
        lens_init.__doc__ = original_init.__doc__
        lens_init.__name__ = getattr(original_init, "__name__", "__init__")
        lens_init.__qualname__ = getattr(original_init, "__qualname__", "Runner.__init__")
        Runner.__init__ = lens_init
        _installed = True
        try:
            _watch_runs(Runner)
        except Exception:
            pass
    except Exception:
        pass


def _attach(runner) -> None:
    from .plugin import PLUGIN_NAME, LensPlugin, lens_plugin

    manager = getattr(runner, "plugin_manager", None)
    if manager is None:
        return
    plugins = getattr(manager, "plugins", [])
    if not any(isinstance(p, LensPlugin) or getattr(p, "name", None) == PLUGIN_NAME for p in plugins):
        manager.register_plugin(lens_plugin)
    # Runners created inside a tool call (an agent used as a tool) are part of a
    # bigger app whose shape is already known: only announce real, top-level apps.
    if type(runner).__name__ == "_NestedRunner":
        return
    app = getattr(runner, "app", None)
    root = getattr(app, "root_agent", None) or getattr(runner, "agent", None)
    name = getattr(runner, "app_name", None) or getattr(app, "name", None) or getattr(root, "name", "app")
    lens_plugin.announce(str(name), root)


class _Finder:
    """Notices the import of google.adk.runners and patches it right after."""

    def find_spec(self, fullname, path=None, target=None):
        if fullname != _TARGET:
            return None
        try:
            sys.meta_path.remove(self)
        except ValueError:
            pass
        try:
            import importlib.util

            spec = importlib.util.find_spec(fullname)
        except Exception:
            return None
        if spec is None or spec.loader is None or not hasattr(spec.loader, "exec_module"):
            return spec
        loader = spec.loader
        original_exec = loader.exec_module

        def exec_module(module):
            original_exec(module)
            _patch(module)

        try:
            loader.exec_module = exec_module
        except Exception:
            pass
        return spec


def bootstrap() -> None:
    """Called at interpreter start by adk_lens.pth. Must be fast and silent."""
    try:
        if not enabled():
            return
        if _TARGET in sys.modules:
            _patch(sys.modules[_TARGET])
            return
        if not any(isinstance(f, _Finder) for f in sys.meta_path):
            sys.meta_path.insert(0, _Finder())
    except Exception:
        pass
