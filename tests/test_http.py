"""Streamable HTTP transport, /healthz and inbound auth, over a real socket."""

from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
import uvicorn
from fastmcp import Client, FastMCP
from fastmcp.client.transports import StreamableHttpTransport
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

TOKEN = "test-token-" + "x" * 20


@asynccontextmanager
async def serve(app: FastMCP | Starlette) -> AsyncIterator[str]:
    if isinstance(app, FastMCP):
        app = app.http_app(path="/mcp")
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", lifespan="on"))
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        while not server.started:  # noqa: ASYNC110 - uvicorn exposes no startup event
            await asyncio.sleep(0.01)
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await task
        sock.close()


async def test_bearer_mode(server_factory: Callable[..., FastMCP], mealie: respx.Router) -> None:
    mealie.get("/api/households/shopping/lists").respond(
        json={"items": [{"id": "l1", "name": "Weekly"}]}
    )
    mcp = server_factory(
        transport="http", auth_mode="bearer", bearer_tokens=f"other-{TOKEN},{TOKEN}"
    )
    async with serve(mcp) as base, httpx.AsyncClient(base_url=base) as http:
        health = await http.get("/healthz")
        assert health.status_code == 200 and health.json()["status"] == "ok"

        init = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "t", "version": "0"},
            },
        }
        headers = {"Accept": "application/json, text/event-stream"}
        assert (await http.post("/mcp", json=init, headers=headers)).status_code == 401
        bad = headers | {"Authorization": "Bearer wrong-token-xxxxxxxxxxxx"}
        assert (await http.post("/mcp", json=init, headers=bad)).status_code == 401

        transport = StreamableHttpTransport(
            f"{base}/mcp", headers={"Authorization": f"Bearer {TOKEN}"}
        )
        async with Client(transport) as client:
            result = await client.call_tool("list_shopping_lists", {})
            assert json.loads(result.content[0].text) == {
                "shopping_lists": [{"id": "l1", "name": "Weekly"}]
            }  # type: ignore[union-attr]


async def test_no_auth_on_loopback(server_factory: Callable[..., FastMCP]) -> None:
    async with (
        serve(server_factory(transport="http")) as base,
        Client(StreamableHttpTransport(f"{base}/mcp")) as client,
    ):
        assert len(await client.list_tools()) == 20


@contextmanager
def serve_in_thread(app: Starlette) -> Iterator[str]:
    """For apps hit by blocking calls (FastMCP's OIDC discovery runs synchronously)."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        while not server.started:
            time.sleep(0.01)
        yield f"http://127.0.0.1:{sock.getsockname()[1]}"
    finally:
        server.should_exit = True
        thread.join(5)
        sock.close()


def fake_idp() -> Starlette:
    """Just enough of an OIDC provider for FastMCP's discovery at startup."""

    async def discovery(request: Request) -> JSONResponse:
        issuer = str(request.base_url).rstrip("/")
        return JSONResponse(
            {
                "issuer": issuer,
                "authorization_endpoint": f"{issuer}/authorize",
                "token_endpoint": f"{issuer}/api/oidc/token",
                "jwks_uri": f"{issuer}/.well-known/jwks.json",
                "response_types_supported": ["code"],
                "subject_types_supported": ["public"],
                "id_token_signing_alg_values_supported": ["RS256"],
            }
        )

    return Starlette(routes=[Route("/.well-known/openid-configuration", discovery)])


@pytest.mark.parametrize("use_issuer", [True, False])
async def test_oidc_mode_publishes_oauth_metadata(
    server_factory: Callable[..., FastMCP], tmp_path: Path, use_issuer: bool
) -> None:
    with serve_in_thread(fake_idp()) as idp_url:
        idp: dict[str, Any] = (
            {"oidc_issuer": idp_url}
            if use_issuer
            else {"oidc_config_url": f"{idp_url}/.well-known/openid-configuration"}
        )
        mcp = server_factory(
            transport="http",
            auth_mode="oidc",
            base_url="https://mcp.example.com",
            oidc_client_id="mealie-mcp",
            oidc_client_secret="s3cret",
            state_dir=str(tmp_path),
            **idp,
        )
        async with serve(mcp) as base, httpx.AsyncClient(base_url=base) as http:
            assert (await http.get("/healthz")).status_code == 200
            unauth = await http.post("/mcp", json={})
            assert unauth.status_code == 401
            assert "resource_metadata" in unauth.headers.get("www-authenticate", "")

            meta = (await http.get("/.well-known/oauth-authorization-server")).json()
            assert meta["issuer"].rstrip("/") == "https://mcp.example.com"
            assert meta["authorization_endpoint"] == "https://mcp.example.com/authorize"
            assert "registration_endpoint" in meta

            prm = await http.get("/.well-known/oauth-protected-resource/mcp")
            assert prm.json()["resource"] == "https://mcp.example.com/mcp"

            # Unknown clients get no further than the authorize endpoint.
            authorize = await http.get(
                "/authorize", params={"client_id": "nope", "response_type": "code"}
            )
            assert authorize.status_code >= 400
    assert (tmp_path / "oauth-proxy").is_dir(), "OAuth state belongs in MEALIE_MCP_STATE_DIR"


@pytest.mark.parametrize("forward", [False, True])
def test_oidc_forward_resource(tmp_path: Path, forward: bool) -> None:
    """Strict RFC 8707 providers (Pocket ID >= 2.19) reject an unknown `resource`,
    so it is only sent upstream when explicitly enabled."""
    from urllib.parse import parse_qs, urlparse

    from fastmcp.server.auth import OAuthProxy

    from mealie_agent_mcp.auth import build_auth

    from .conftest import make_settings

    with serve_in_thread(fake_idp()) as idp_url:
        overrides: dict[str, Any] = {"oidc_forward_resource": True} if forward else {}
        auth = build_auth(
            make_settings(
                transport="http",
                auth_mode="oidc",
                base_url="https://mcp.example.com",
                oidc_issuer=idp_url,
                oidc_client_id="mealie-mcp",
                oidc_client_secret="s3cret",
                state_dir=str(tmp_path),
                **overrides,
            )
        )
    assert isinstance(auth, OAuthProxy)
    url = auth._build_upstream_authorize_url(
        "txn-1",
        {"resource": "https://mcp.example.com/mcp", "scopes": ["openid", "profile", "email"]},
    )
    query = parse_qs(urlparse(url).query)
    assert url.startswith(f"{idp_url}/authorize?")
    assert query["redirect_uri"] == ["https://mcp.example.com/auth/callback"]
    assert query["scope"] == ["openid profile email"]
    if forward:
        assert query["resource"] == ["https://mcp.example.com/mcp"]
    else:
        assert "resource" not in query
