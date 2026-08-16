from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_broken_parallel_dispatch_chat_surface_is_not_mounted():
    routers = (ROOT / "fastapi_app" / "routers" / "__init__.py").read_text(
        encoding="utf-8"
    )

    assert "dispatch_chat" not in routers
    assert not (ROOT / "fastapi_app" / "routers" / "dispatch_chat.py").exists()


def test_supported_chat_route_remains_owned_by_realtime_router():
    realtime = (ROOT / "fastapi_app" / "routers" / "realtime.py").read_text(
        encoding="utf-8"
    )

    assert '@router.post("/api/chat/start"' in realtime
    assert '@router.websocket("/api/chat/stream")' in realtime
