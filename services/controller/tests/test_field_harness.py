"""Regression tests for release-harness behavior that must fail closed."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_bridge_probe_read_deadline_is_real():
    probe = _load("field_bridge_probe", ROOT / "scripts/lib/field_bridge_probe.py")
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(10)"],
        stdout=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    started = time.monotonic()
    try:
        frames = probe._stdout_frames(proc)
        assert probe.read_frame(proc, frames, 0.1) is None
        assert time.monotonic() - started < 1.0
    finally:
        proc.kill()
        proc.wait(timeout=2)


def test_field_stage_baseline_is_read_only_without_record_flag(tmp_path):
    runner = ROOT / "scripts/lib/field_stage.py"
    baseline = tmp_path / "baseline.json"
    baseline.write_text('{"check": {"seconds": 2.0}}\n')
    before = baseline.read_bytes()

    result = subprocess.run(
        [
            sys.executable, str(runner), "--name", "check",
            "--baseline", str(baseline), "--timeout", "2", "--",
            sys.executable, "-c", "pass",
        ],
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert baseline.read_bytes() == before


def test_no_jaeger_kill_switch_blocks_execution_discovery(monkeypatch):
    from api.providers.jaeger import streaming

    monkeypatch.setenv("ARES_NO_JAEGER", "1")
    assert streaming.local_jaeger_root() is None
