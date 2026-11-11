"""ADK Lens: a live whiteboard of what your ADK agents are doing.

Nothing to change in your agent code. See README.md.
"""

__version__ = "0.1.0"

__all__ = ["LensPlugin", "lens_plugin", "install", "__version__"]


def __getattr__(name):  # lazy: importing adk_lens must not import google.adk
    if name in ("LensPlugin", "lens_plugin"):
        from . import plugin

        return getattr(plugin, name)
    if name == "install":
        from .autoload import install

        return install
    raise AttributeError(name)
