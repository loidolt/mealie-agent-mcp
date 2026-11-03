from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest
import respx
from fastmcp import Client, FastMCP

from mealie_agent_mcp.config import Settings
from mealie_agent_mcp.server import create_server

MEALIE = "http://mealie.test"


def make_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {"mealie_url": MEALIE, "mealie_api_token": "mealie-token"}
    values.update(overrides)
    return Settings.load(**values)


@pytest.fixture(autouse=True)
def _clean_env(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the developer's real MEALIE_* environment out of unit tests."""
    import os

    if request.node.get_closest_marker("integration"):
        return
    for key in list(os.environ):
        if key.startswith("MEALIE_"):
            monkeypatch.delenv(key)


@pytest.fixture
def mealie() -> respx.Router:
    router = respx.Router(base_url=MEALIE, assert_all_mocked=True)
    router.get("/api/users/self").respond(json={"groupSlug": "home"})
    return router


@pytest.fixture
def server_factory(mealie: respx.Router) -> Callable[..., FastMCP]:
    def factory(**overrides: Any) -> FastMCP:
        return create_server(
            make_settings(**overrides),
            mealie_transport=httpx.MockTransport(mealie.async_handler),
        )

    return factory


@pytest.fixture
async def client(server_factory: Callable[..., FastMCP]) -> AsyncIterator[Client[Any]]:
    async with Client(server_factory()) as c:
        yield c
