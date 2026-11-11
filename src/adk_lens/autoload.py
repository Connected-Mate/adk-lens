"""Attach the lens to every ADK Runner without editing anyone's code.

`install()` wraps `Runner.__init__` so that, once ADK has built a runner exactly
as usual, the lens plugin is added to that runner's own plugin list. The user's
`App`, agents and plugin list objects are left untouched.

`bootstrap()` is what the `.pth` file calls at interpreter start. It does nothing
unless the lens is switched on, and it never imports ADK by itself: it waits
for the program to import `google.adk.runners`.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_installed = False
_TARGET = "google.adk.runners"


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
