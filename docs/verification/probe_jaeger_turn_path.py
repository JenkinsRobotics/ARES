#!/usr/bin/env python
"""Reproduce the runtime evidence in ``jaeger-turn-path-evidence.md``.

Reads live state only — it starts no turn, writes no config, and kills nothing.
Run it against a machine with a JaegerAI install to regenerate every observation
the report cites:

    cd services/controller
    .venv/bin/python ../../docs/verification/probe_jaeger_turn_path.py

Output is the observation, not a verdict. Two probes are expected to disagree
with each other on a machine exhibiting Finding 1 — that disagreement IS the
finding, so neither is "the right answer" to keep.
"""

from __future__ import annotations

import glob
import json
import os
import pathlib
import socket
import sys

REPO = pathlib.Path(__file__).resolve().parents[2] / "services" / "controller"
MONOREPO = REPO.parent.parent
for _path in (str(REPO), str(MONOREPO)):
    if _path not in sys.path:
        sys.path.insert(0, _path)
os.chdir(REPO)


def _rule(title: str) -> None:
    print(f"\n{'─' * 72}\n{title}\n{'─' * 72}")


def probe_backend_selection() -> None:
    """Finding 3: what the REAL router's backend returns, not a fake's."""
    _rule("Backend selection — the flag chat_runtime actually branches on")
    from api.backends.router import get_default_router

    backend = get_default_router().backends["jaeger_local"]
    target, is_gateway, is_jaeger = backend.get_worker_target()
    print(f"  class        : {type(backend).__module__}.{type(backend).__name__}")
    print(f"  defined in   : {sys.modules[type(backend).__module__].__file__}")
    print(f"  worker target: {target.__module__}.{target.__name__}")
    print(f"  is_gateway   : {is_gateway}   <- selects the prompt shape")
    print(f"  is_jaeger    : {is_jaeger}")


def probe_status() -> None:
    """Finding 1, half one: what ARES tells the operator."""
    _rule("Reported status — what the operator is told")
    from api.providers.jaeger.status import check_status

    status = check_status(use_cache=False)
    print(f"  available : {status.available}")
    print(f"  state     : {status.state.value}")
    print(f"  message   : {status.message}")
    print(f"  details   : {json.dumps(status.details, indent=14, default=str)}")


def probe_bridge_queries() -> None:
    """Finding 1, half two: what the bridge actually does when asked."""
    _rule("Bridge queries — what the runtime actually answers")
    from api.providers.jaeger.streaming import query_local_companion

    for what in ("serving_model", "model_catalog", "contract", "list_tools"):
        try:
            value = json.dumps(query_local_companion(what, {}), default=str)
            print(f"  {what:<14}: OK {value[:120]}")
        except Exception as exc:  # noqa: BLE001 - the exception IS the evidence
            print(f"  {what:<14}: {type(exc).__name__}: {exc}")


def probe_attach_candidates() -> None:
    """Finding 2: where ARES looks versus where a bridge is listening."""
    _rule("Attach candidates — where ARES looks vs. where the bridge listens")
    from api.providers.jaeger.paths import (
        jaeger_bridge_socket_candidates,
        jaeger_instance_name,
    )
    from api.providers.jaeger.streaming import local_jaeger_root

    home = local_jaeger_root()
    if home is None:
        print("  no JaegerAI install found; nothing to compare")
        return
    instance = jaeger_instance_name()
    sticky = home / ".jaeger_ai" / "active_instance"
    print(f"  ARES explicit selector : {instance!r}")
    print(f"  Jaeger sticky default  : "
          f"{sticky.read_text().strip()!r}" if sticky.exists() else
          "  Jaeger sticky default  : <unset>")

    print("  candidates ARES will try:")
    for path in jaeger_bridge_socket_candidates(str(home), instance):
        print(f"      exists={str(path.exists()):<5} {path}")

    print("  sockets on disk, and whether anything is listening:")
    for found in sorted(glob.glob(f"{home}/.jaeger_ai/instances/*/run/bridge.sock")):
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        probe.settimeout(2.0)
        try:
            probe.connect(found)
            verdict = "LISTENING"
        except OSError as exc:
            verdict = f"stale ({exc.strerror})"
        finally:
            probe.close()
        print(f"      {verdict:<28} {found}")


def main() -> int:
    for probe in (
        probe_backend_selection,
        probe_status,
        probe_bridge_queries,
        probe_attach_candidates,
    ):
        try:
            probe()
        except Exception as exc:  # noqa: BLE001 - one probe must not end the run
            print(f"  probe {probe.__name__} raised {type(exc).__name__}: {exc}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
