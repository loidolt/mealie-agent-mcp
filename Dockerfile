# syntax=docker/dockerfile:1.7
ARG PYTHON_IMAGE=python:3.13-slim-trixie

FROM ghcr.io/astral-sh/uv:0.13.7 AS uv

FROM ${PYTHON_IMAGE} AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /src
# Dependencies first (cached unless the lockfile changes), then the project.
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev --no-install-project
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev --no-editable

FROM ${PYTHON_IMAGE}
LABEL org.opencontainers.image.title="mealie-agent-mcp" \
      org.opencontainers.image.description="Curated MCP server for Mealie v3" \
      org.opencontainers.image.source="https://github.com/loidolt/mealie-agent-mcp" \
      org.opencontainers.image.licenses="MIT"
RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --home-dir /data --no-create-home app \
 && install -d -o app -g app -m 0700 /data
COPY --from=build /app/.venv /app/.venv
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/data \
    MEALIE_MCP_TRANSPORT=http \
    MEALIE_MCP_HOST=0.0.0.0 \
    MEALIE_MCP_PORT=8000 \
    MEALIE_MCP_STATE_DIR=/data
USER app
WORKDIR /data
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('MEALIE_MCP_PORT', '8000'), timeout=4)"]
ENTRYPOINT ["mealie-agent-mcp"]
