"""Thin async wrapper around the Mealie REST API."""

from __future__ import annotations

from typing import Any

import httpx
from fastmcp.exceptions import ToolError

from . import __version__

JSON = Any


class MealieError(ToolError):
    """A Mealie API call failed. The message is safe to show to the model."""

    def __init__(self, status: int | None, message: str) -> None:
        self.status = status
        super().__init__(message)


def _error_detail(resp: httpx.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        return resp.reason_phrase or "error"
    detail = body.get("detail", body) if isinstance(body, dict) else body
    if isinstance(detail, dict):
        detail = detail.get("message") or detail
    if isinstance(detail, list):  # FastAPI validation errors
        detail = "; ".join(
            f"{'.'.join(str(p) for p in d.get('loc', []))}: {d.get('msg')}"
            for d in detail
            if isinstance(d, dict)
        ) or str(detail)
    return str(detail)[:500]


class MealieClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout: float = 30.0,
        verify: bool = True,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._http = httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "User-Agent": f"mealie-agent-mcp/{__version__}",
            },
            timeout=timeout,
            verify=verify,
            transport=transport,
            # Never follow redirects: the token must only ever go to MEALIE_URL.
            follow_redirects=False,
        )
        self._group_slug: str | None = None

    async def aclose(self) -> None:
        await self._http.aclose()

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | list[tuple[str, Any]] | None = None,
        json: JSON = None,
    ) -> JSON:
        try:
            resp = await self._http.request(method, path, params=params, json=json)
        except httpx.TimeoutException as exc:
            raise MealieError(None, f"Mealie did not respond in time ({method} {path})") from exc
        except httpx.HTTPError as exc:
            raise MealieError(None, f"Could not reach Mealie: {type(exc).__name__}") from exc
        if resp.status_code >= 400:
            if resp.status_code in (401, 403):
                hint = " (check MEALIE_API_TOKEN and the Mealie user's permissions)"
            elif resp.status_code == 404:
                hint = " (not found)"
            else:
                hint = ""
            raise MealieError(
                resp.status_code,
                f"Mealie returned HTTP {resp.status_code} for {method} {path}: "
                f"{_error_detail(resp)}{hint}",
            )
        if resp.status_code == 204 or not resp.content:
            return None
        try:
            return resp.json()
        except ValueError:
            return resp.text

    async def get(self, path: str, **kw: Any) -> JSON:
        return await self.request("GET", path, **kw)

    async def post(self, path: str, **kw: Any) -> JSON:
        return await self.request("POST", path, **kw)

    async def put(self, path: str, **kw: Any) -> JSON:
        return await self.request("PUT", path, **kw)

    async def patch(self, path: str, **kw: Any) -> JSON:
        return await self.request("PATCH", path, **kw)

    async def delete(self, path: str, **kw: Any) -> JSON:
        return await self.request("DELETE", path, **kw)

    async def group_slug(self) -> str | None:
        """Group slug of the token's user, used to build links to the Mealie UI."""
        if self._group_slug is None:
            try:
                me = await self.get("/api/users/self")
            except MealieError:
                return None
            self._group_slug = me.get("groupSlug") if isinstance(me, dict) else None
        return self._group_slug
