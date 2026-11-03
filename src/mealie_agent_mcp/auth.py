"""Inbound authentication for the HTTP transport."""

from __future__ import annotations

import hashlib
import hmac
import logging
from pathlib import Path

import fastmcp
from fastmcp.server.auth import AccessToken, AuthProvider, TokenVerifier

from .config import Settings

log = logging.getLogger(__name__)


class StaticBearerVerifier(TokenVerifier):
    """Accept a fixed set of bearer tokens, compared in constant time."""

    def __init__(self, tokens: list[str]) -> None:
        super().__init__()
        self._digests = [hashlib.sha256(t.encode()).digest() for t in tokens]

    async def verify_token(self, token: str) -> AccessToken | None:
        digest = hashlib.sha256(token.encode()).digest()
        match = None
        for idx, known in enumerate(self._digests):  # no early exit: constant time
            if hmac.compare_digest(digest, known):
                match = idx
        if match is None:
            return None
        return AccessToken(token=token, client_id=f"bearer-token-{match + 1}", scopes=[])


def build_auth(settings: Settings) -> AuthProvider | None:
    if settings.auth_mode == "none":
        return None

    if settings.auth_mode == "bearer":
        return StaticBearerVerifier([t.get_secret_value() for t in settings.bearer_tokens])

    # oidc: FastMCP acts as an OAuth authorization server towards MCP clients
    # (dynamic client registration, consent screen) and delegates login to the
    # upstream OIDC provider with one pre-registered client.
    from fastmcp.server.auth import OIDCProxy

    if settings.state_dir:
        # OAuth proxy state (client registrations, encrypted upstream tokens)
        # lives under FastMCP's home directory. Keep it on a persistent volume
        # so clients stay registered across restarts.
        fastmcp.settings.home = Path(settings.state_dir)

    assert settings.oidc_client_id and settings.oidc_client_secret and settings.base_url
    assert settings.oidc_discovery_url
    return OIDCProxy(
        config_url=settings.oidc_discovery_url,
        client_id=settings.oidc_client_id,
        client_secret=settings.oidc_client_secret.get_secret_value(),
        audience=settings.oidc_audience,
        base_url=settings.base_url,
        required_scopes=settings.oidc_scopes or None,
        verify_id_token=settings.oidc_verify_id_token,
        allowed_client_redirect_uris=settings.oidc_allowed_client_redirect_uris,
        jwt_signing_key=(
            settings.jwt_signing_key.get_secret_value() if settings.jwt_signing_key else None
        ),
    )
