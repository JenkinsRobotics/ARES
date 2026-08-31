#!/usr/bin/env python3
"""Install launchd jobs for Agentgateway and managed Apple containers."""

from __future__ import annotations

import json
import os
import plistlib
import shutil
import subprocess
from pathlib import Path

PUBLIC_ENV_KEYS = {
    "ARES_A2A_PUBLIC_URL",
    "ARES_WEBUI_TAILSCALE_USERS",
    "ARES_WEBUI_HOST",
    "ARES_WEBUI_PORT",
    "ARES_SHARED_WORKSPACE",
}


def load_local_environment(state: Path) -> dict[str, str]:
    """Load a strict, secret-free machine overlay from outside the repository."""

    config_path = Path(
        os.environ.get("ARES_SYSTEM_FABRIC_CONFIG")
        or state / "config" / "system-fabric.json"
    ).expanduser()
    document: dict = {"version": 1, "environment": {}}
    if config_path.exists():
        with config_path.open("rb") as handle:
            document = json.load(handle)
    if document.get("version") != 1 or not isinstance(document.get("environment"), dict):
        raise SystemExit(f"Unsupported System fabric configuration: {config_path}")
    unknown = set(document["environment"]) - PUBLIC_ENV_KEYS
    if unknown:
        raise SystemExit(f"Unsupported System fabric keys: {', '.join(sorted(unknown))}")
    values: dict[str, str] = {}
    for key in PUBLIC_ENV_KEYS:
        value = os.environ.get(key, document["environment"].get(key, ""))
        if value:
            values[key] = str(value)
    return values


def write_plist(path: Path, payload: dict) -> None:
    temporary = path.with_suffix(".plist.tmp")
    with temporary.open("wb") as handle:
        plistlib.dump(payload, handle, sort_keys=False)
    os.replace(temporary, path)


def install(
    label: str,
    arguments: list[str],
    log_dir: Path,
    keep_alive: bool,
    *,
    environment: dict[str, str] | None = None,
) -> None:
    launch_dir = Path.home() / "Library" / "LaunchAgents"
    launch_dir.mkdir(parents=True, exist_ok=True)
    plist = launch_dir / f"{label}.plist"
    payload = {
        "Label": label,
        "ProgramArguments": arguments,
        "RunAtLoad": True,
        "KeepAlive": keep_alive,
        "ProcessType": "Background",
        "ThrottleInterval": 10,
        "StandardOutPath": str(log_dir / f"{label}.log"),
        "StandardErrorPath": str(log_dir / f"{label}.err.log"),
    }
    if environment:
        payload["EnvironmentVariables"] = environment
    write_plist(plist, payload)
    domain = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", domain, str(plist)], check=False, capture_output=True)
    subprocess.run(["launchctl", "bootstrap", domain, str(plist)], check=True)
    print(f"Installed {label}")


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    state = Path(os.environ.get("ARES_HOME") or Path.home() / ".ares")
    log_dir = state / "logs"
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    state.chmod(0o700)
    log_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    log_dir.chmod(0o700)
    local_env = load_local_environment(state)
    install(
        "com.jenkinsrobotics.ares-control",
        ["/bin/zsh", str(repo / "scripts" / "run-ares-control.sh")],
        log_dir,
        True,
        environment=local_env,
    )
    allowed_users = local_env.get("ARES_WEBUI_TAILSCALE_USERS", "")
    if allowed_users:
        for label, upstream, port in (
            ("com.jenkinsrobotics.ares-tailproxy", "http://127.0.0.1:8787", "8786"),
            ("com.jenkinsrobotics.ares-tailproxy-jaeger", "http://127.0.0.1:8790", "8785"),
        ):
            install(
                label,
                [
                    str(repo / "services" / "controller" / ".venv" / "bin" / "python"),
                    str(repo / "services" / "controller" / "tailscale_identity_proxy.py"),
                ],
                log_dir,
                True,
                environment={
                    "ARES_WEBUI_TAILSCALE_USERS": allowed_users,
                    "ARES_TAILPROXY_UPSTREAM": upstream,
                    "ARES_TAILPROXY_HOST": "127.0.0.1",
                    "ARES_TAILPROXY_PORT": port,
                },
            )
    install(
        "com.jenkinsrobotics.ares-agentgateway",
        ["/bin/zsh", str(repo / "scripts" / "run-agentgateway.sh")],
        log_dir,
        True,
    )
    install(
        "com.jenkinsrobotics.ares-containers",
        ["/bin/zsh", str(repo / "scripts" / "start-managed-containers.sh")],
        log_dir,
        False,
    )
    ollama_path = shutil.which("ollama")
    if ollama_path:
        install(
            "com.jenkinsrobotics.ares-ollama",
            [ollama_path, "serve"],
            log_dir,
            True,
            environment={
                # Containers reach this loopback listener through Apple's
                # host.container.internal redirect. LAN and tailnet peers do
                # not receive Ollama's unauthenticated API.
                "OLLAMA_HOST": "127.0.0.1:11434",
                "OLLAMA_FLASH_ATTENTION": "1",
                "OLLAMA_KV_CACHE_TYPE": "q8_0",
                # Unified memory is the scarce resource on this Mac. Keep one
                # model resident briefly for conversational follow-ups, but do
                # not let concurrent frameworks load competing model weights.
                "OLLAMA_KEEP_ALIVE": os.environ.get("ARES_OLLAMA_KEEP_ALIVE", "90s"),
                "OLLAMA_MAX_LOADED_MODELS": os.environ.get("ARES_OLLAMA_MAX_LOADED_MODELS", "1"),
                "OLLAMA_NUM_PARALLEL": os.environ.get("ARES_OLLAMA_NUM_PARALLEL", "1"),
                "OLLAMA_MAX_QUEUE": os.environ.get("ARES_OLLAMA_MAX_QUEUE", "32"),
            },
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
