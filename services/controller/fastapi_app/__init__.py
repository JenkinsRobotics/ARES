"""Parallel FastAPI application for the incremental ARES backend migration.

The deployable controller lives below the monorepo packages it imports.  Put
the repository root on ``sys.path`` before importing any application module so
``core`` resolves to the repository package, whose namespace also exposes the
controller-owned automation/control-plane modules.  Doing this after an early
``core.automation`` import leaves Python holding an incomplete namespace and
causes cold Uvicorn starts to fail when a later router imports
``core.knowledge``.
"""

import sys
from pathlib import Path

_MONOREPO_ROOT = Path(__file__).resolve().parents[3]
if str(_MONOREPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_MONOREPO_ROOT))

from .main import create_app

__all__ = ["create_app"]
