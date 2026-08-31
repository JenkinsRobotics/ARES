#!/usr/bin/env python3
"""Identity-gated reverse proxy for runtime UIs exposed by Tailscale Serve."""

from __future__ import annotations

import asyncio
import os
from urllib.parse import urlsplit

from aiohttp import ClientSession, ClientTimeout, WSMsgType, web

UPSTREAM = os.environ.get("ARES_TAILPROXY_UPSTREAM", "http://127.0.0.1:8787").rstrip("/")
LISTEN_HOST = os.environ.get("ARES_TAILPROXY_HOST", "127.0.0.1")
LISTEN_PORT = int(os.environ.get("ARES_TAILPROXY_PORT", "8786"))
MAX_BODY_BYTES = 64 * 1024 * 1024
HOP_HEADERS = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade",
}
IDENTITY_HEADERS = {
    "tailscale-user-login", "tailscale-user-name", "tailscale-user-profile-pic",
    "tailscale-app-capabilities",
}


def authorized(host: str, login: str, allowlist: str) -> bool:
    hostname = urlsplit(f"//{host}").hostname or ""
    allowed = {
        item.strip().lower()
        for item in allowlist.replace(";", ",").split(",")
        if item.strip()
    }
    return bool(
        hostname.rstrip(".").lower().endswith(".ts.net")
        and login.strip().lower() in allowed
    )


def _request_headers(request: web.Request) -> dict[str, str]:
    return {
        key: value for key, value in request.headers.items()
        if key.lower() not in HOP_HEADERS | IDENTITY_HEADERS | {"host", "content-length"}
    }


async def _websocket(request: web.Request, session: ClientSession) -> web.StreamResponse:
    downstream = web.WebSocketResponse(protocols=request.headers.getall("Sec-WebSocket-Protocol", []))
    await downstream.prepare(request)
    upstream = await session.ws_connect(
        f"{UPSTREAM}{request.rel_url}", headers=_request_headers(request),
        protocols=downstream.ws_protocol and [downstream.ws_protocol] or (),
    )

    async def client_to_owner() -> None:
        async for message in downstream:
            if message.type == WSMsgType.TEXT:
                await upstream.send_str(message.data)
            elif message.type == WSMsgType.BINARY:
                await upstream.send_bytes(message.data)
            elif message.type in {WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.ERROR}:
                break

    async def owner_to_client() -> None:
        async for message in upstream:
            if message.type == WSMsgType.TEXT:
                await downstream.send_str(message.data)
            elif message.type == WSMsgType.BINARY:
                await downstream.send_bytes(message.data)
            elif message.type in {WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.ERROR}:
                break

    try:
        await asyncio.gather(client_to_owner(), owner_to_client())
    finally:
        await upstream.close()
        await downstream.close()
    return downstream


async def proxy(request: web.Request) -> web.StreamResponse:
    if not authorized(
        request.host,
        request.headers.get("Tailscale-User-Login", ""),
        os.environ.get("ARES_WEBUI_TAILSCALE_USERS", ""),
    ):
        raise web.HTTPForbidden(text="Tailscale identity is not authorized")
    session: ClientSession = request.app["session"]
    if request.headers.get("Upgrade", "").lower() == "websocket":
        return await _websocket(request, session)
    # Hermes' stdlib HTTP server does not implement chunked request bodies.
    # Buffer one explicitly bounded body so aiohttp can send Content-Length;
    # bodyless GET/HEAD requests must send no chunk terminator at all.
    body = await request.read() if request.can_read_body else None
    async with session.request(
        request.method,
        f"{UPSTREAM}{request.rel_url}",
        headers=_request_headers(request),
        data=body,
        allow_redirects=False,
    ) as upstream:
        response = web.StreamResponse(status=upstream.status, reason=upstream.reason)
        for key_bytes, value_bytes in upstream.raw_headers:
            key = key_bytes.decode("latin-1")
            if key.lower() not in HOP_HEADERS | {"content-length"}:
                response.headers.add(key, value_bytes.decode("latin-1"))
        await response.prepare(request)
        async for chunk in upstream.content.iter_chunked(64 * 1024):
            await response.write(chunk)
        await response.write_eof()
        return response


async def session_context(app: web.Application):
    app["session"] = ClientSession(timeout=ClientTimeout(total=None, connect=10, sock_read=None))
    yield
    await app["session"].close()


def main() -> None:
    app = web.Application(client_max_size=MAX_BODY_BYTES)
    app.cleanup_ctx.append(session_context)
    app.router.add_route("*", "/{path:.*}", proxy)
    web.run_app(app, host=LISTEN_HOST, port=LISTEN_PORT, print=None, access_log=None)


if __name__ == "__main__":
    main()
