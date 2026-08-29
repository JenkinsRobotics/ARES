"""ARES Companion control-plane packages (non-worker).

The native controller remains runnable from ``services/controller`` while the
repository root is also importable by tests and developer tools.  Expose the
controller-owned packages through the same ``core`` namespace in both cases.
"""

from pathlib import Path

_controller_core = Path(__file__).resolve().parents[1] / "services" / "controller" / "core"
if _controller_core.is_dir():
    __path__.append(str(_controller_core))
