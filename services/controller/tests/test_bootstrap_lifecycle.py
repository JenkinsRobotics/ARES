"""Tests for bootstrap.py port checking, PID file management, and signal handling."""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import time
from pathlib import Path

import pytest

import bootstrap
from bootstrap import check_port_in_use, install_child_signal_handlers, write_pid_file


class _Response:
    def __init__(self, body: bytes):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self):
        return self.body


def test_health_ok_parses_compact_json(monkeypatch):
    monkeypatch.setattr(
        bootstrap.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: _Response(b'{"status":"ok"}'),
    )

    assert bootstrap._health_ok("http://127.0.0.1:8788/health") is True


def test_check_port_in_use():
    # Bind a temporary port
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.listen(1)

    assert check_port_in_use("127.0.0.1", port) is True
    s.close()
    assert check_port_in_use("127.0.0.1", port) is False


def test_write_pid_file(tmp_path):
    pid_file = write_pid_file(tmp_path, os.getpid(), 9999)
    assert pid_file.exists()
    assert pid_file.read_text().strip() == str(os.getpid())


def test_install_child_signal_handlers(tmp_path):
    proc = subprocess.Popen(["sleep", "60"])
    install_child_signal_handlers(proc)
    assert proc.poll() is None
    proc.terminate()
    proc.wait()
