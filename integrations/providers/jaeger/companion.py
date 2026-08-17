"""ARES onboarding adapter for Jaeger-owned Companion operations.

Defaults, existence checks, and instance creation use the versioned Jaeger
bridge. The only subprocess mutation retained here is installing Jaeger itself;
ARES never opens an instance config, identity, or credential file.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from api.providers.jaeger.gateway_streaming import local_jros_root

logger = logging.getLogger(__name__)

def companion_available() -> bool:
    """True when a local JaegerAI install is present for the naming step."""
    try:
        return local_jros_root() is not None
    except Exception:
        logger.debug("Companion availability probe failed", exc_info=True)
        return False


def install_jros_if_missing(jaeger_home: str | None = None) -> dict[str, Any]:
    """Check whether JaegerAI is installed and, if not, download and run JaegerAI's
    own installer.  Returns a status dict:

      {"installed": True, "already_present": True}  — JaegerAI already installed
      {"installed": True, "already_present": False} — JaegerAI freshly installed
      {"installed": False, "error": "..."}           — installation failed

    The installer URL and JAEGER_HOME resolution use the same env vars as
    the bash installer (JROS_INSTALL_URL, ARES_JAEGER_HOME, JAEGER_HOME).
    """
    import os
    import subprocess
    import urllib.request

    # Re-use the same detection logic as the bash installer.
    from api.providers.jaeger.paths import jaeger_home as resolve_jaeger_home, jaeger_launcher

    resolved_home = Path(jaeger_home) if jaeger_home else resolve_jaeger_home()
    launcher = resolved_home / "jaeger"

    if launcher.exists() and os.access(str(launcher), os.X_OK):
        return {"installed": True, "already_present": True, "jaeger_home": str(resolved_home)}

    # JaegerAI not found — download and run its own installer.
    install_url = os.environ.get(
        "JROS_INSTALL_URL",
        "https://raw.githubusercontent.com/JenkinsRobotics/JaegerAI/master/scripts/install.sh",
    )
    env = dict(os.environ)
    env["JAEGER_HOME"] = str(resolved_home)
    env["ARES_JAEGER_HOME"] = str(resolved_home)

    try:
        logger.info("Downloading JaegerAI installer from %s", install_url)
        req = urllib.request.Request(install_url, headers={"User-Agent": "ARES-WebUI/1.0"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            script = resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        raise RuntimeError(f"Failed to download JaegerAI installer: {exc}") from exc

    try:
        result = subprocess.run(
            ["bash", "-c", script],
            env=env,
            capture_output=True,
            text=True,
            timeout=600,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("JaegerAI installer timed out after 10 minutes.")
    except Exception as exc:
        raise RuntimeError(f"Failed to run JaegerAI installer: {exc}") from exc

    if result.returncode != 0:
        stderr = (result.stderr or "").strip()[-2000:]
        raise RuntimeError(f"JaegerAI installer exited with code {result.returncode}: {stderr}")

    # Verify installation succeeded.
    if launcher.exists() and os.access(str(launcher), os.X_OK):
        return {"installed": True, "already_present": False, "jaeger_home": str(resolved_home)}
    # The installer might have used a different JAEGER_HOME; re-probe.
    from api.providers.jaeger.paths import discover_jros_source_root
    found = discover_jros_source_root()
    if found is not None:
        return {"installed": True, "already_present": False, "jaeger_home": str(found)}
    raise RuntimeError(
        "JaegerAI installer completed but no launcher was found. "
        "Check the installer output and ensure JAEGER_HOME is set correctly."
    )


def companion_exists() -> bool:
    """True when a Companion instance has already been created."""
    try:
        from api.providers.jaeger.gateway_streaming import query_local_companion

        result = query_local_companion("instance_exists", {})
        return bool(result.get("exists"))
    except Exception:
        logger.debug("Companion existence check failed", exc_info=True)
        return False


def companion_setup_defaults() -> dict[str, Any]:
    """Host-tier model recommendation, voices, permission modes, and the
    character roster — the same recommendations ``jaeger agent create``'s
    terminal wizard prints, served for ARES's web onboarding instead."""
    from api.providers.jaeger.gateway_streaming import query_local_companion

    result = query_local_companion("setup_defaults", {})
    if not isinstance(result, dict):
        raise RuntimeError("Jaeger returned invalid setup defaults")
    return result


def list_characters() -> list[dict[str, str]]:
    """Characters available to play the Companion (id, name, role, voice)."""
    return companion_setup_defaults().get("characters", [])


def create_companion(
    *,
    character_id: str | None = None,
    name: str | None = None,
    display_name: str | None = None,
    role: str | None = None,
    personality: str | None = None,
    voice_id: str | None = None,
    awake_model: str | None = None,
    asleep_model: str | None = None,
    permission_mode: str = "confirm",
    make_default: bool = True,
) -> dict[str, Any]:
    """Ask Jaeger's bridge to create the Companion with its validated service."""
    resolved_character_id = (character_id or "").strip()
    if not resolved_character_id or resolved_character_id == "default":
        # Fall back to the first available character when the user picks
        # "Default (no character)" — the user's name, display_name and
        # personality override the character's identity anyway.
        roster = list_characters()
        if not roster:
            raise ValueError("No characters are installed. Install JaegerAI characters first.")
        resolved_character_id = roster[0]["id"]

    from api.providers.jaeger.gateway_streaming import command_local_companion

    result = command_local_companion(
        "create_instance",
        {
            "character_id": resolved_character_id,
            "name": name,
            "display_name": display_name,
            "role": role,
            "personality": personality,
            "voice_id": voice_id,
            "awake_model": awake_model,
            "asleep_model": asleep_model,
            "permission_mode": permission_mode,
            "interaction_mode": "gui",
            "make_default": make_default,
        },
    )
    if not isinstance(result, dict):
        raise RuntimeError("Jaeger returned an invalid instance-creation result")
    result = {
        "ok": True,
        "name": result.get("instance"),
        "instance_dir": result.get("root"),
        "owner": "jaeger",
    }
    return result
