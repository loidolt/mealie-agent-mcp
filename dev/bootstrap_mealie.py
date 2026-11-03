"""Prepare a fresh Mealie container for development and integration tests.

Logs in with Mealie's default admin account, creates a dedicated non-admin
user for the MCP server (mirroring the recommended production setup), and
creates a long-lived API token for that user.

Usage:
    uv run python dev/bootstrap_mealie.py [--url http://localhost:9925] [--github-env]

Prints `MEALIE_URL=...` and `MEALIE_API_TOKEN=...` lines (shell-eval friendly).
With --github-env the values are appended to $GITHUB_ENV instead.
"""

from __future__ import annotations

import argparse
import os
import secrets

import httpx

ADMIN_EMAIL = "changeme@example.com"
ADMIN_PASSWORD = "MyPassword"  # Mealie's documented default for new installs
MCP_USER = "mcp-agent"
MCP_EMAIL = "mcp-agent@example.com"


def login(client: httpx.Client, username: str, password: str) -> str:
    resp = client.post("/api/auth/token", data={"username": username, "password": password})
    resp.raise_for_status()
    return str(resp.json()["access_token"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=os.environ.get("MEALIE_URL", "http://localhost:9925"))
    parser.add_argument("--github-env", action="store_true")
    args = parser.parse_args()

    with httpx.Client(base_url=args.url, timeout=30) as client:
        admin_token = login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
        admin = {"Authorization": f"Bearer {admin_token}"}

        password = secrets.token_urlsafe(24)
        users = client.get("/api/admin/users", headers=admin, params={"perPage": -1})
        users.raise_for_status()
        existing = next((u for u in users.json()["items"] if u["username"] == MCP_USER), None)
        if existing is None:
            created = client.post(
                "/api/admin/users",
                headers=admin,
                json={
                    "username": MCP_USER,
                    "fullName": "MCP Agent",
                    "email": MCP_EMAIL,
                    "password": password,
                    "admin": False,
                    # Needed so the agent can create foods/units when saving
                    # structured ingredients.
                    "canOrganize": True,
                },
            )
            created.raise_for_status()
        else:
            # Re-run against the same container: reset the user's password.
            reset = client.post(
                "/api/admin/users/password-reset-token", headers=admin, json={"email": MCP_EMAIL}
            )
            reset.raise_for_status()
            client.post(
                "/api/users/reset-password",
                json={
                    "token": reset.json()["token"],
                    "email": MCP_EMAIL,
                    "password": password,
                    "passwordConfirm": password,
                },
            ).raise_for_status()

        user_token = login(client, MCP_USER, password)
        resp = client.post(
            "/api/users/api-tokens",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"name": f"mcp-dev-{secrets.token_hex(3)}"},
        )
        resp.raise_for_status()
        api_token = resp.json()["token"]

    lines = [f"MEALIE_URL={args.url}", f"MEALIE_API_TOKEN={api_token}"]
    if args.github_env:
        with open(os.environ["GITHUB_ENV"], "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    else:
        print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
