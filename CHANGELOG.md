# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/). The environment variables and the container
image's port and volume are the public interface: renaming or removing any of them is a
breaking change.

## [Unreleased]

## [0.1.1] - 2026-11-03

### Fixed

- OAuth sign-in through Pocket ID 2.19+ (and other providers that validate RFC 8707
  resource indicators) failed with "The 'resource' or 'scope' parameter is invalid".
  The MCP client's `resource` is no longer forwarded to the identity provider; this server
  issues its own tokens and uses the provider only for login.

### Added

- `MEALIE_MCP_OIDC_FORWARD_RESOURCE` (default `false`) to restore forwarding for providers
  that need the resource to set the token audience.

## [0.1.0] - 2026-11-02

### Added

- 20 curated tools for recipes, meal plans and shopping lists, with compact responses.
- `MEALIE_MCP_READ_ONLY` to register only the 9 read tools.
- stdio and streamable HTTP transports, `/healthz` health endpoint.
- Inbound auth modes `none` (loopback only unless overridden), `bearer` and `oidc`
  (OAuth proxy in front of any OIDC provider).
- Non-root multi-arch container image `ghcr.io/loidolt/mealie-agent-mcp`.
- Unit tests with a mocked Mealie API; integration tests against Mealie v3.0.2 and v3.30.0.

[Unreleased]: https://github.com/loidolt/mealie-agent-mcp/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/loidolt/mealie-agent-mcp/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/loidolt/mealie-agent-mcp/releases/tag/v0.1.0
