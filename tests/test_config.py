from __future__ import annotations

import pytest
from pydantic import ValidationError

from mealie_agent_mcp.config import Settings, is_loopback_host

from .conftest import make_settings


def test_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEALIE_URL", "https://recipes.example.com/")
    monkeypatch.setenv("MEALIE_API_TOKEN", "t")
    monkeypatch.setenv("MEALIE_MCP_READ_ONLY", "true")
    monkeypatch.setenv("MEALIE_MCP_AUTH_MODE", "bearer")
    monkeypatch.setenv("MEALIE_MCP_BEARER_TOKENS", " " + "a" * 21 + " , " + "b" * 20 + ",")
    s = Settings()  # type: ignore[call-arg]
    assert s.mealie_url == "https://recipes.example.com"
    assert s.read_only is True
    assert [t.get_secret_value() for t in s.bearer_tokens] == ["a" * 21, "b" * 20]


def test_generic_env_vars_do_not_leak(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression: field names must not be read as env vars (PATH, HOST, PORT...)."""
    monkeypatch.setenv("MEALIE_URL", "http://m")
    monkeypatch.setenv("MEALIE_API_TOKEN", "t")
    for name, value in {
        "PATH": "/usr/bin:/bin",
        "HOST": "evil",
        "PORT": "1",
        "TRANSPORT": "http",
        "READ_ONLY": "true",
        "AUTH_MODE": "oidc",
    }.items():
        monkeypatch.setenv(name, value)
    s = Settings()  # type: ignore[call-arg]
    assert (s.path, s.host, s.port, s.transport) == ("/mcp", "127.0.0.1", 8000, "stdio")
    assert (s.read_only, s.auth_mode) == (False, "none")


def test_load_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEALIE_URL", "http://m")
    monkeypatch.setenv("MEALIE_API_TOKEN", "t")
    monkeypatch.setenv("MEALIE_MCP_PORT", "9000")
    assert Settings.load().port == 9000
    assert Settings.load(port=9100, read_only=True).port == 9100


def test_bearer_requires_tokens() -> None:
    with pytest.raises(ValidationError, match="MEALIE_MCP_BEARER_TOKENS"):
        make_settings(auth_mode="bearer")


def test_bearer_rejects_short_tokens() -> None:
    with pytest.raises(ValidationError, match="at least 16"):
        make_settings(auth_mode="bearer", bearer_tokens="short")


def test_oidc_requires_fields() -> None:
    with pytest.raises(ValidationError) as exc:
        make_settings(auth_mode="oidc", oidc_client_id="x")
    msg = str(exc.value)
    assert "MEALIE_MCP_BASE_URL" in msg
    assert "MEALIE_MCP_OIDC_CLIENT_SECRET" in msg
    assert "MEALIE_MCP_OIDC_CLIENT_ID" not in msg


def test_oidc_issuer_derives_discovery_url() -> None:
    s = make_settings(
        auth_mode="oidc",
        base_url="https://mcp.example.com",
        oidc_issuer="https://id.example.com/",
        oidc_client_id="id",
        oidc_client_secret="secret",
    )
    assert s.oidc_discovery_url == "https://id.example.com/.well-known/openid-configuration"
    assert s.oidc_scopes == ["openid", "profile", "email"]


def test_rejects_non_http_mealie_url() -> None:
    with pytest.raises(ValidationError):
        make_settings(mealie_url="file:///etc/passwd")


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("127.0.0.1", True),
        ("localhost", True),
        ("::1", True),
        ("[::1]", True),
        ("0.0.0.0", False),
        ("192.168.1.5", False),
        ("example.com", False),
    ],
)
def test_loopback(host: str, expected: bool) -> None:
    assert is_loopback_host(host) is expected


def test_refuses_unauthenticated_remote_bind() -> None:
    s = make_settings(transport="http", host="0.0.0.0")
    with pytest.raises(ValueError, match="refusing"):
        s.check_bind_safety()


def test_unauthenticated_remote_bind_override() -> None:
    make_settings(
        transport="http", host="0.0.0.0", allow_unauthenticated_remote=True
    ).check_bind_safety()


def test_authenticated_remote_bind_ok() -> None:
    make_settings(
        transport="http", host="0.0.0.0", auth_mode="bearer", bearer_tokens="x" * 32
    ).check_bind_safety()
    make_settings(transport="http", host="127.0.0.1").check_bind_safety()
    make_settings(transport="stdio", host="0.0.0.0").check_bind_safety()


def test_oidc_forward_resource_defaults_off(monkeypatch: pytest.MonkeyPatch) -> None:
    assert make_settings().oidc_forward_resource is False
    monkeypatch.setenv("MEALIE_URL", "http://m")
    monkeypatch.setenv("MEALIE_API_TOKEN", "t")
    monkeypatch.setenv("MEALIE_MCP_OIDC_FORWARD_RESOURCE", "true")
    assert Settings.load().oidc_forward_resource is True
