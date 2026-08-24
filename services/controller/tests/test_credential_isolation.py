"""ARES tests must not inherit the operator's live credentials or state."""

from __future__ import annotations

import os
from pathlib import Path

import pytest


def test_pytest_process_has_no_credential_shaped_env():
    from tests import conftest as c

    leftovers = [
        name for name in os.environ
        if name not in c._CREDENTIAL_ENV_KEEP
        and (
            name in c._CREDENTIAL_ENV_EXACT
            or name.endswith(("_API_KEY", "_TOKEN", "_SECRET", "_PASSWORD"))
        )
    ]
    assert leftovers == [], leftovers


def test_isolated_home_is_not_the_operator_ares_home():
    from tests.conftest import TEST_STATE_DIR

    prod = Path.home() / ".ares"
    isolated = Path(TEST_STATE_DIR).resolve()
    assert isolated != prod.resolve()
    assert prod.resolve() not in isolated.parents


def test_jaeger_is_disabled_for_the_default_suite():
    assert os.environ.get("ARES_NO_JAEGER") == "1"


def test_subprocess_env_builder_strips_keys(monkeypatch):
    from tests import conftest as c

    sample = {
        "OPENAI_API_KEY": "sk-live",
        "ANTHROPIC_API_KEY": "sk-ant",
        "PATH": "/usr/bin",
        "ARES_WEBUI_PASSWORD": "",
    }
    removed = c._strip_credential_env(sample)
    assert "OPENAI_API_KEY" in removed
    assert "ANTHROPIC_API_KEY" in removed
    assert "OPENAI_API_KEY" not in sample
    assert sample["PATH"] == "/usr/bin"
    assert sample["ARES_WEBUI_PASSWORD"] == ""
