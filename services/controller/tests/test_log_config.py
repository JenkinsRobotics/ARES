"""Tests for api.log_config logging configuration and FastAPI OpenAPI toggle."""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from pathlib import Path

import pytest

from api.log_config import _JsonFormatter, configure_logging, get_log_dir
from fastapi_app.main import create_app


def test_get_log_dir_respects_env(monkeypatch, tmp_path):
    custom_dir = tmp_path / "custom_logs"
    monkeypatch.setenv("ARES_LOG_DIR", str(custom_dir))
    log_dir = get_log_dir()
    assert log_dir == custom_dir
    assert custom_dir.exists()


def test_json_formatter():
    formatter = _JsonFormatter()
    record = logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname="test.py",
        lineno=10,
        msg="Hello %s",
        args=("world",),
        exc_info=None,
    )
    output = formatter.format(record)
    assert '"level": "INFO"' in output
    assert '"logger": "test_logger"' in output
    assert '"message": "Hello world"' in output
    assert '"ts":' in output


def test_configure_logging_text_format(monkeypatch, tmp_path):
    log_dir = tmp_path / "logs"
    monkeypatch.setenv("ARES_LOG_DIR", str(log_dir))
    monkeypatch.setenv("ARES_LOG_FORMAT", "text")
    monkeypatch.setenv("ARES_LOG_LEVEL", "DEBUG")

    import api.log_config
    monkeypatch.setattr(api.log_config, "_CONFIGURED", False)

    res = configure_logging()
    assert res["status"] == "configured"
    assert res["format"] == "text"
    assert res["level"] == "DEBUG"
    assert Path(res["log_file"]).parent == log_dir


def test_configure_logging_already_configured(monkeypatch):
    import api.log_config
    monkeypatch.setattr(api.log_config, "_CONFIGURED", True)
    res = configure_logging()
    assert res["status"] == "already_configured"


def test_openapi_toggle(monkeypatch):
    monkeypatch.setenv("ARES_OPENAPI", "0")
    app_disabled = create_app()
    assert app_disabled.docs_url is None
    assert app_disabled.redoc_url is None
    assert app_disabled.openapi_url is None

    monkeypatch.setenv("ARES_OPENAPI", "1")
    app_enabled = create_app()
    assert app_enabled.docs_url == "/docs"
    assert app_enabled.redoc_url == "/redoc"
    assert app_enabled.openapi_url == "/openapi.json"
