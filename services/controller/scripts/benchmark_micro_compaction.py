#!/usr/bin/env python3
"""Deterministic calibration benchmark for compaction strategies.

This does not call a model and therefore cannot justify adoption. It measures
the harness itself (latency, character-token proxy, exact marker recall, and
repeated-pass drift) before a provider-backed corpus run is attempted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from pathlib import Path

MARKER = re.compile(r"\[(?:FACT|TASK|TOOL):[^\]]+\]")


def _tokens(text: str) -> int:
    return (len(text) + 3) // 4


def _markers(text: str) -> list[str]:
    return list(dict.fromkeys(MARKER.findall(text)))


def _arc(messages: list[str], keep: int = 8) -> str:
    old = "\n".join(messages[:-keep])
    summary = " ".join(_markers(old))
    return "\n".join(([f"[ARC] {summary}"] if summary else []) + messages[-keep:])


def _micro(messages: list[str], chunk: int = 6, keep: int = 8) -> str:
    compacted = []
    for start in range(0, max(0, len(messages) - keep), chunk):
        compacted.append("[MICRO] " + " ".join(_markers("\n".join(messages[start:start + chunk]))))
    return "\n".join(compacted + messages[-keep:])


def _fixture(turns: int) -> list[str]:
    rows = []
    for index in range(turns):
        marker = ""
        if index % 7 == 0:
            marker += f" [FACT:key{index}=value{index}]"
        if index % 11 == 0:
            marker += f" [TASK:task{index}=open]"
        if index % 13 == 0:
            marker += f" [TOOL:tool{index}=success]"
        rows.append(f"turn {index}: ordinary conversational context{marker}")
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--turns", type=int, default=240)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    messages = _fixture(max(24, args.turns))
    expected = set(_markers("\n".join(messages)))
    rows = []
    for name, strategy in (("whole_arc", _arc), ("micro", _micro)):
        started = time.perf_counter()
        first = strategy(messages)
        elapsed = time.perf_counter() - started
        # Re-run using the compacted representation as a single prior row to
        # detect deterministic loss/drift in the calibration implementation.
        second = strategy([first] + messages[-8:])
        found = set(_markers(first))
        rows.append({
            "strategy": name,
            "latency_ms": round(elapsed * 1000, 3),
            "input_token_proxy": _tokens("\n".join(messages)),
            "output_token_proxy": _tokens(first),
            "exact_marker_recall": round(len(found & expected) / max(1, len(expected)), 4),
            "repeated_pass_marker_recall": round(len(set(_markers(second)) & expected) / max(1, len(expected)), 4),
            "output_sha256": hashlib.sha256(first.encode()).hexdigest(),
        })
    report = {
        "evidence_level": "synthetic deterministic calibration; no model/provider boundary",
        "adoption_decision": "not justified",
        "turns": len(messages),
        "expected_markers": len(expected),
        "results": rows,
    }
    rendered = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
