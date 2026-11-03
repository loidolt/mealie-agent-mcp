# mealie-agent-mcp

A small, curated [Model Context Protocol](https://modelcontextprotocol.io) server for
[Mealie](https://mealie.io) v3. It lets Claude (claude.ai, Claude Desktop and mobile,
Claude Code), LibreChat and other MCP clients search and edit your recipes, plan meals and
manage shopping lists.

- **20 focused tools** with descriptions written for language models, not a 1:1 dump of
  Mealie's API.
- **Compact responses.** Mealie's JSON is trimmed to the fields an agent needs; a recipe
  is typically 3–7× smaller than the raw API response.
- **Safe by default.** No webhook, notification, user or admin tools. A read-only mode.
  Refuses to serve unauthenticated HTTP beyond localhost.
- **Runs anywhere.** stdio for local clients, streamable HTTP (`/mcp`) for remote ones,
  with static bearer tokens or OAuth through any OIDC provider (Pocket ID, Authentik,
  Authelia, Keycloak, …).
- Built on [FastMCP](https://gofastmcp.com) 4, with pinned dependencies and a multi-arch
  container image.

Tested against Mealie v3.0.2 and v3.30.0.

## Tools

| Tool | Kind | What it does |
| --- | --- | --- |
| `search_recipes` | read | Search by text and/or tag, category or food |
| `list_recipes` | read | Browse all recipes: newest, name, rating, last made, random |
| `get_recipe` | read | One recipe: ingredients, steps, times, tags, notes, nutrition |
| `list_recipe_organizers` | read | Tags, categories or tools (names and slugs) |
| `parse_ingredients` | read | Parse "2 cups flour, sifted" into quantity/unit/food/note |
| `list_meal_plans` | read | Meal plan entries in a date range (default: next 7 days) |
| `get_meal_plan_for_date` | read | Meal plan for one day (default: today) |
| `list_shopping_lists` | read | The household's shopping lists |
| `get_shopping_list` | read | Items on a list (unchecked only by default) |
| `create_recipe_from_url` | write | Import a recipe from a web page (Mealie's scraper) |
| `create_recipe` | write | Create a recipe, with free-text or structured ingredients |
| `update_recipe` | write | Change fields; list fields (ingredients, steps, tags) are replaced |
| `create_meal_plan_entry` | write | Put a recipe or a free-text note on the meal plan |
| `create_random_meal_plan_entry` | write | Let Mealie pick a recipe (respects meal plan rules) |
| `delete_meal_plan_entry` | write, destructive | Remove a meal plan entry |
| `create_shopping_list` | write | New empty list |
| `add_shopping_list_items` | write | Add free-text items |
| `add_recipe_to_shopping_list` | write | Add a recipe's ingredients, optionally scaled |
| `set_shopping_list_items_checked` | write | Check off or uncheck items |
| `remove_shopping_list_items` | write, destructive | Delete items, or all checked items |

With `MEALIE_MCP_READ_ONLY=true` only the read tools are registered.

Ingredients can be passed as free text (`{"text": "2 cups flour"}`), which is parsed with
Mealie's ingredient parser, or structured (`{"quantity": 2, "unit": "cup", "food":
"flour"}`). Foods, units, tags and categories that don't exist yet are created. If the
Mealie user isn't allowed to create foods/units, the words are kept in the ingredient note
instead.

## Quick start

### 1. Create a Mealie user and token

Create a **dedicated, non-admin** Mealie user for the agent (Admin → Users), in the
household whose meal plans and shopping lists it should manage. Give it the "can organize"
permission if it should be able to create foods, units and tags. Log in as that user and
create an API token under Profile → API Tokens.

### 2a. Run as a container (remote clients)

```bash
docker run -d --name mealie-mcp -p 8000:8000 \
  -e MEALIE_URL=https://recipes.example.com \
  -e MEALIE_API_TOKEN=... \
  -e MEALIE_MCP_AUTH_MODE=bearer \
  -e MEALIE_MCP_BEARER_TOKENS="$(openssl rand -hex 32)" \
  -v mealie-mcp-data:/data \
  ghcr.io/loidolt/mealie-agent-mcp:latest
```

The MCP endpoint is `http://<host>:8000/mcp`; `GET /healthz` is an unauthenticated health
check. Put TLS in front of it (reverse proxy, Cloudflare Tunnel, …) before exposing it.

### 2b. Run locally over stdio

```bash
MEALIE_URL=https://recipes.example.com MEALIE_API_TOKEN=... \
  uvx --from git+https://github.com/loidolt/mealie-agent-mcp mealie-agent-mcp
```

## Configuration

All configuration is through environment variables. CLI flags (`--transport`, `--host`,
`--port`, `--read-only`) override them.

### Mealie

| Variable | Default | Description |
| --- | --- | --- |
| `MEALIE_URL` | *required* | Base URL of Mealie, e.g. `https://recipes.example.com` or `http://mealie:9000` |
| `MEALIE_API_TOKEN` | *required* | API token of the Mealie user the agent acts as |
| `MEALIE_PUBLIC_URL` | `MEALIE_URL` | Base for recipe links in tool output, when `MEALIE_URL` is an internal address |
| `MEALIE_TIMEOUT` | `30` | Seconds per Mealie request (URL imports can be slow) |
| `MEALIE_VERIFY_TLS` | `true` | Verify Mealie's TLS certificate |

### Server

| Variable | Default (image default) | Description |
| --- | --- | --- |
| `MEALIE_MCP_READ_ONLY` | `false` | Register read tools only |
| `MEALIE_MCP_TRANSPORT` | `stdio` (`http`) | `stdio` or `http` (streamable HTTP) |
| `MEALIE_MCP_HOST` | `127.0.0.1` (`0.0.0.0`) | Bind address for `http` |
| `MEALIE_MCP_PORT` | `8000` | Port for `http` |
| `MEALIE_MCP_PATH` | `/mcp` | Path of the MCP endpoint |
| `MEALIE_MCP_STATELESS_HTTP` | `false` | Stateless streamable HTTP (no session affinity needed; for multiple replicas) |
| `MEALIE_MCP_LOG_LEVEL` | `INFO` | Python log level |

### Inbound authentication (HTTP transport)

| Variable | Default (image default) | Description |
| --- | --- | --- |
| `MEALIE_MCP_AUTH_MODE` | `none` | `none`, `bearer` or `oidc` |
| `MEALIE_MCP_ALLOW_UNAUTHENTICATED_REMOTE` | `false` | Allow `none` on a non-loopback address (only when something else authenticates requests) |
| `MEALIE_MCP_BEARER_TOKENS` | | `bearer`: comma-separated accepted tokens, each ≥ 16 characters |
| `MEALIE_MCP_BASE_URL` | | `oidc`: public URL of this server without the path, e.g. `https://mealie-mcp.example.com` |
| `MEALIE_MCP_OIDC_ISSUER` | | `oidc`: issuer URL; discovery is read from `<issuer>/.well-known/openid-configuration` |
| `MEALIE_MCP_OIDC_CONFIG_URL` | | `oidc`: full discovery URL, instead of `MEALIE_MCP_OIDC_ISSUER` |
| `MEALIE_MCP_OIDC_CLIENT_ID` | | `oidc`: client id registered at the provider |
| `MEALIE_MCP_OIDC_CLIENT_SECRET` | | `oidc`: client secret |
| `MEALIE_MCP_OIDC_SCOPES` | `openid,profile,email` | `oidc`: scopes requested from the provider |
| `MEALIE_MCP_OIDC_AUDIENCE` | | `oidc`: `audience` parameter, for providers that need one |
| `MEALIE_MCP_OIDC_VERIFY_ID_TOKEN` | `true` | `oidc`: verify the provider's ID token (always a JWT) instead of its access token (opaque at some providers, e.g. Authelia) |
| `MEALIE_MCP_OIDC_ALLOWED_CLIENT_REDIRECT_URIS` | any | `oidc`: comma-separated patterns of MCP-client callback URLs allowed to register, e.g. `https://claude.ai/api/mcp/auth_callback,http://localhost:*` |
| `MEALIE_MCP_JWT_SIGNING_KEY` | derived from client secret | `oidc`: key for the tokens this server issues to MCP clients |
| `MEALIE_MCP_STATE_DIR` | FastMCP data dir (`/data`) | `oidc`: where client registrations and encrypted upstream tokens are stored. Persist it |

## Authentication modes

### `none`

For stdio, or HTTP on `127.0.0.1` for a client on the same machine. The server refuses to
start with `none` on any other address unless `MEALIE_MCP_ALLOW_UNAUTHENTICATED_REMOTE=true`.

### `bearer`

Clients send `Authorization: Bearer <token>`. Simple and works with Claude Code, LibreChat
and most MCP clients. Configure several tokens (comma-separated) to give each client its
own and rotate them independently.

### `oidc`

claude.ai connectors (and therefore Claude Desktop and mobile) authenticate with OAuth.
In this mode the server is an OAuth authorization server for MCP clients (with dynamic
client registration and a consent screen) and delegates the actual login to your OIDC
provider through one pre-registered client.

1. In your OIDC provider, create a **confidential** client (authorization code flow) with
   the redirect URI:

   ```
   <MEALIE_MCP_BASE_URL>/auth/callback
   ```

   e.g. `https://mealie-mcp.example.com/auth/callback`. This is the only redirect URI the
   provider needs. MCP clients' own callbacks (for claude.ai,
   `https://claude.ai/api/mcp/auth_callback`) are registered with this server, not with
   the provider.
2. **Restrict who may use the client** at the provider (Pocket ID: "allowed user groups";
   Authentik: application bindings; Authelia: an `authorization_policy`). Anyone who can
   complete the login gets the Mealie user's access.
3. Set `MEALIE_MCP_AUTH_MODE=oidc`, `MEALIE_MCP_BASE_URL`, `MEALIE_MCP_OIDC_ISSUER`,
   `MEALIE_MCP_OIDC_CLIENT_ID`, `MEALIE_MCP_OIDC_CLIENT_SECRET`, and mount a volume at
   `MEALIE_MCP_STATE_DIR` (`/data` in the image) so registrations survive restarts.

| Provider | Issuer (`MEALIE_MCP_OIDC_ISSUER`) |
| --- | --- |
| Pocket ID | `https://id.example.com` |
| Authentik | `https://auth.example.com/application/o/<app-slug>/` |
| Authelia | `https://auth.example.com` |
| Keycloak | `https://kc.example.com/realms/<realm>` |

The server also publishes the standard discovery documents
(`/.well-known/oauth-authorization-server`, `/.well-known/oauth-protected-resource/mcp`),
so MCP clients find everything from the `/mcp` URL alone.

## Client setup

### claude.ai, Claude Desktop, Claude mobile

Requires `oidc` mode and a public HTTPS URL. In claude.ai: Settings → Connectors → Add
custom connector, URL `https://mealie-mcp.example.com/mcp`. Claude opens your provider's
login when you connect. Connectors added on claude.ai are available in Claude Desktop and
the mobile apps.

### Claude Code

```bash
# bearer mode
claude mcp add --transport http mealie https://mealie-mcp.example.com/mcp \
  --header "Authorization: Bearer $MEALIE_MCP_TOKEN"

# oidc mode (then run /mcp in Claude Code to log in)
claude mcp add --transport http mealie https://mealie-mcp.example.com/mcp

# local stdio, no server to run
claude mcp add mealie -e MEALIE_URL=https://recipes.example.com -e MEALIE_API_TOKEN=... \
  -- uvx --from git+https://github.com/loidolt/mealie-agent-mcp mealie-agent-mcp
```

### LibreChat

In `librechat.yaml`:

```yaml
mcpServers:
  mealie:
    type: streamable-http
    url: http://mealie-mcp:8000/mcp   # or your public https URL
    headers:
      Authorization: "Bearer ${MEALIE_MCP_TOKEN}"
    timeout: 60000                     # recipe imports can take a while
```

and set `MEALIE_MCP_TOKEN` in LibreChat's `.env` to one of `MEALIE_MCP_BEARER_TOKENS`.

### Other clients (stdio)

```json
{
  "mcpServers": {
    "mealie": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/loidolt/mealie-agent-mcp", "mealie-agent-mcp"],
      "env": { "MEALIE_URL": "https://recipes.example.com", "MEALIE_API_TOKEN": "..." }
    }
  }
}
```

## Security model

- **The agent acts as one Mealie user.** Use a dedicated, non-admin account in the
  intended household, never your own or an admin's token. Everything a connected client
  can do is bounded by that user's Mealie permissions.
- **Read-only mode** (`MEALIE_MCP_READ_ONLY=true`) removes every write tool from the
  server, not just from descriptions. Use it for clients that only need to look things up.
- **Recipe content is untrusted.** Recipes imported from the web can contain text written
  to manipulate language models ("ignore previous instructions and …"). This server
  therefore exposes no tools that send data to arbitrary destinations: no webhooks,
  notifications, user management, backups or admin operations. The only tool that
  reaches an outside URL is `create_recipe_from_url`, which makes *Mealie* fetch the page
  you name. Tool descriptions and server instructions tell models to treat recipe text
  as data. Still, keep a human in the loop for write actions, and be careful about
  connecting this server in the same session as tools that can exfiltrate data (email,
  web requests, file access).
- **Inbound auth.** Unauthenticated HTTP is refused beyond localhost. Bearer tokens are
  compared in constant time. In `oidc` mode, MCP clients only ever receive tokens issued
  by this server; upstream provider tokens are stored encrypted in `MEALIE_MCP_STATE_DIR`.
- **Outbound.** The Mealie token is only sent to `MEALIE_URL`; redirects are not
  followed. Model-supplied ids are encoded as single path segments.
- **Container.** Runs as an unprivileged user (uid 10001), writes only to `/data`.

## Development

```bash
uv sync
uv run pytest                 # unit tests (Mealie API mocked)
uv run ruff check . && uv run ruff format --check . && uv run mypy

# integration tests against a throwaway Mealie container
docker compose -f dev/compose.yaml up -d --wait mealie
eval "$(uv run python dev/bootstrap_mealie.py)" && export MEALIE_URL MEALIE_API_TOKEN
uv run pytest -m integration

# the container in bearer mode, exercised over streamable HTTP
export MEALIE_MCP_BEARER_TOKENS=$(openssl rand -hex 32)
docker compose -f dev/compose.yaml --profile mcp up -d --build --wait
uv run python dev/smoke_http.py http://127.0.0.1:8000/mcp "$MEALIE_MCP_BEARER_TOKENS"
```

`dev/bootstrap_mealie.py` logs in with Mealie's default admin account, so only use it on
throwaway instances. Set `MCP_HOST_PORT` if port 8000 is taken.

Releases: push a tag `vX.Y.Z`; CI builds `linux/amd64` and `linux/arm64` images and
publishes `ghcr.io/loidolt/mealie-agent-mcp:X.Y.Z`, `X.Y`, `X` (from 1.0) and `latest`.

## License

[MIT](LICENSE)
