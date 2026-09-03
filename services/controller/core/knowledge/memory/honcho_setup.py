"""Setup and health check for the Honcho server.

Provides functions to check if Honcho is running locally,
and instructions for setup if it isn't.
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

from ..config import KBConfig
from .honcho_client import HonchoClient

logger = logging.getLogger(__name__)


def check_honcho(config: KBConfig) -> dict:
    """Check if Honcho is running and healthy."""
    client = HonchoClient.from_config(config)
    healthy = client.health()
    return {
        "running": healthy,
        "api_url": config.honcho_api_url,
        "has_api_key": bool(os.environ.get("HONCHO_API_KEY", "")),
        "needs_setup": not healthy,
        "setup_instructions": _setup_instructions() if not healthy else None,
    }


def _setup_instructions() -> str:
    return """
To set up Honcho locally:

1. Install Docker Desktop on the Mac:
   Download from https://www.docker.com/products/docker-desktop/

2. Install honcho-cli:
   pip3 install honcho-cli

3. Start the local stack:
   honcho start --setup

4. This starts:
   - Honcho API server on http://127.0.0.1:8000
   - Deriver (background reasoning) 
   - PostgreSQL (with pgvector)
   - Redis (caching)

5. Or use the managed API:
   Get a key at https://honcho.dev
   Set HONCHO_API_KEY in ~/.ares/.env
   Set HONCHO_API_URL=https://api.honcho.dev in ~/.ares/.env
"""


def start_honcho_local(config: KBConfig) -> dict:
    """Attempt to start Honcho locally if Docker is available."""
    docker_path = subprocess.run(
        ["which", "docker"], capture_output=True, text=True, timeout=5
    ).stdout.strip()
    if not docker_path:
        return {"ok": False, "error": "Docker is not installed"}

    honcho_path = subprocess.run(
        ["which", "honcho"], capture_output=True, text=True, timeout=5
    ).stdout.strip()
    if not honcho_path:
        return {"ok": False, "error": "honcho-cli is not installed (pip3 install honcho-cli)"}

    try:
        proc = subprocess.Popen(
            [honcho_path, "start"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={**os.environ, "HONCHO_HOME": str(config.honcho_dir)},
        )
        return {"ok": True, "pid": proc.pid}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}