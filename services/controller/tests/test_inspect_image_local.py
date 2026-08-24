"""Image inspection is local ARES work. It must not call JaegerAI."""

from __future__ import annotations

import inspect
from io import BytesIO

from PIL import Image

from api.upload import inspect_image_bytes


def test_inspect_image_bytes_returns_local_metadata():
    buf = BytesIO()
    Image.new("RGB", (16, 9), color=(8, 16, 32)).save(buf, format="PNG")
    info = inspect_image_bytes(buf.getvalue(), "ui.png")
    assert info["width"] == 16
    assert info["height"] == 9
    assert info["jaeger_involved"] is False
    assert info["owner"] == "ares"
    assert "16x9" in info["summary"]


def test_inspect_image_source_does_not_call_jaeger():
    source = inspect.getsource(inspect_image_bytes)
    assert "query_local_companion" not in source
    assert "jaeger_ai" not in source
    assert "bridge.sock" not in source
