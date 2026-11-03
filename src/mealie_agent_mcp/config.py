"""Runtime configuration, read from environment variables.

Every setting has a single env var. The names are a public interface (they are
what container deployments set), so treat renames as breaking changes.
"""

from __future__ import annotations

import ipaddress
from typing import Annotated, Any, Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

AuthMode = Literal["none", "bearer", "oidc"]
Transport = Literal["stdio", "http"]

MIN_BEARER_TOKEN_LENGTH = 16


def _env(name: str) -> AliasChoices:
    # Only the documented variable name. Never the bare field name: that would
    # make generic variables like PATH, HOST or PORT configure the server.
    return AliasChoices(name)


def _split_csv(value: object) -> object:
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return value


def is_loopback_host(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    @classmethod
    def load(cls, **overrides: Any) -> Settings:
        """Read the environment; keyword overrides are given by field name."""
        by_alias = {}
        for name, value in overrides.items():
            alias = cls.model_fields[name].validation_alias
            assert isinstance(alias, AliasChoices)
            by_alias[str(alias.choices[0])] = value
        return cls(**by_alias)

    # --- Mealie connection -------------------------------------------------
    mealie_url: str = Field(validation_alias=_env("MEALIE_URL"))
    mealie_api_token: SecretStr = Field(validation_alias=_env("MEALIE_API_TOKEN"))
    mealie_public_url: str | None = Field(default=None, validation_alias=_env("MEALIE_PUBLIC_URL"))
    mealie_timeout: float = Field(default=30.0, gt=0, validation_alias=_env("MEALIE_TIMEOUT"))
    mealie_verify_tls: bool = Field(default=True, validation_alias=_env("MEALIE_VERIFY_TLS"))

    # --- Tool surface ------------------------------------------------------
    read_only: bool = Field(default=False, validation_alias=_env("MEALIE_MCP_READ_ONLY"))

    # --- Transport ---------------------------------------------------------
    transport: Transport = Field(default="stdio", validation_alias=_env("MEALIE_MCP_TRANSPORT"))
    host: str = Field(default="127.0.0.1", validation_alias=_env("MEALIE_MCP_HOST"))
    port: int = Field(default=8000, ge=1, le=65535, validation_alias=_env("MEALIE_MCP_PORT"))
    path: str = Field(default="/mcp", validation_alias=_env("MEALIE_MCP_PATH"))
    stateless_http: bool = Field(default=False, validation_alias=_env("MEALIE_MCP_STATELESS_HTTP"))
    log_level: str = Field(default="INFO", validation_alias=_env("MEALIE_MCP_LOG_LEVEL"))

    # --- Inbound auth ------------------------------------------------------
    auth_mode: AuthMode = Field(default="none", validation_alias=_env("MEALIE_MCP_AUTH_MODE"))
    allow_unauthenticated_remote: bool = Field(
        default=False, validation_alias=_env("MEALIE_MCP_ALLOW_UNAUTHENTICATED_REMOTE")
    )
    bearer_tokens: Annotated[list[SecretStr], NoDecode] = Field(
        default_factory=list, validation_alias=_env("MEALIE_MCP_BEARER_TOKENS")
    )
    base_url: str | None = Field(default=None, validation_alias=_env("MEALIE_MCP_BASE_URL"))
    oidc_config_url: str | None = Field(
        default=None, validation_alias=_env("MEALIE_MCP_OIDC_CONFIG_URL")
    )
    oidc_issuer: str | None = Field(default=None, validation_alias=_env("MEALIE_MCP_OIDC_ISSUER"))
    oidc_client_id: str | None = Field(
        default=None, validation_alias=_env("MEALIE_MCP_OIDC_CLIENT_ID")
    )
    oidc_client_secret: SecretStr | None = Field(
        default=None, validation_alias=_env("MEALIE_MCP_OIDC_CLIENT_SECRET")
    )
    oidc_scopes: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["openid", "profile", "email"],
        validation_alias=_env("MEALIE_MCP_OIDC_SCOPES"),
    )
    oidc_audience: str | None = Field(
        default=None, validation_alias=_env("MEALIE_MCP_OIDC_AUDIENCE")
    )
    oidc_verify_id_token: bool = Field(
        default=True, validation_alias=_env("MEALIE_MCP_OIDC_VERIFY_ID_TOKEN")
    )
    oidc_allowed_client_redirect_uris: Annotated[list[str] | None, NoDecode] = Field(
        default=None, validation_alias=_env("MEALIE_MCP_OIDC_ALLOWED_CLIENT_REDIRECT_URIS")
    )
    jwt_signing_key: SecretStr | None = Field(
        default=None, validation_alias=_env("MEALIE_MCP_JWT_SIGNING_KEY")
    )
    state_dir: str | None = Field(default=None, validation_alias=_env("MEALIE_MCP_STATE_DIR"))

    @field_validator("bearer_tokens", "oidc_scopes", mode="before")
    @classmethod
    def _csv(cls, value: object) -> object:
        return _split_csv(value)

    @field_validator("oidc_allowed_client_redirect_uris", mode="before")
    @classmethod
    def _csv_optional(cls, value: object) -> object:
        if value is None or value == "":
            return None
        return _split_csv(value)

    @field_validator("mealie_url", "mealie_public_url", "base_url")
    @classmethod
    def _http_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().rstrip("/")
        if not value.startswith(("http://", "https://")):
            raise ValueError("must start with http:// or https://")
        return value

    @field_validator("path")
    @classmethod
    def _leading_slash(cls, value: str) -> str:
        return value if value.startswith("/") else f"/{value}"

    @model_validator(mode="after")
    def _check_auth(self) -> Settings:
        if self.auth_mode == "bearer":
            if not self.bearer_tokens:
                raise ValueError("MEALIE_MCP_AUTH_MODE=bearer needs MEALIE_MCP_BEARER_TOKENS")
            if any(len(t.get_secret_value()) < MIN_BEARER_TOKEN_LENGTH for t in self.bearer_tokens):
                raise ValueError(
                    f"every MEALIE_MCP_BEARER_TOKENS entry must be at least "
                    f"{MIN_BEARER_TOKEN_LENGTH} characters (use e.g. `openssl rand -hex 32`)"
                )
        if self.auth_mode == "oidc":
            missing = [
                name
                for name, value in (
                    ("MEALIE_MCP_BASE_URL", self.base_url),
                    (
                        "MEALIE_MCP_OIDC_CONFIG_URL or MEALIE_MCP_OIDC_ISSUER",
                        self.oidc_discovery_url,
                    ),
                    ("MEALIE_MCP_OIDC_CLIENT_ID", self.oidc_client_id),
                    ("MEALIE_MCP_OIDC_CLIENT_SECRET", self.oidc_client_secret),
                )
                if not value
            ]
            if missing:
                raise ValueError(f"MEALIE_MCP_AUTH_MODE=oidc needs {', '.join(missing)}")
        return self

    @property
    def oidc_discovery_url(self) -> str | None:
        if self.oidc_config_url:
            return self.oidc_config_url
        if self.oidc_issuer:
            return self.oidc_issuer.rstrip("/") + "/.well-known/openid-configuration"
        return None

    @property
    def link_base_url(self) -> str:
        """Base URL used for links to Mealie shown to the user."""
        return self.mealie_public_url or self.mealie_url

    def check_bind_safety(self) -> None:
        """Refuse to expose an unauthenticated server beyond loopback."""
        if (
            self.transport == "http"
            and self.auth_mode == "none"
            and not is_loopback_host(self.host)
            and not self.allow_unauthenticated_remote
        ):
            raise ValueError(
                f"refusing to serve unauthenticated MCP on non-loopback host {self.host!r}. "
                "Set MEALIE_MCP_AUTH_MODE=bearer or oidc, bind to 127.0.0.1, or set "
                "MEALIE_MCP_ALLOW_UNAUTHENTICATED_REMOTE=true if another layer "
                "(reverse proxy, private network) enforces authentication."
            )
