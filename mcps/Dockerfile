FROM ghcr.io/astral-sh/uv:latest AS uv
FROM python:3.12-slim

COPY --from=uv /uv /uvx /bin/
WORKDIR /app

COPY mcps/pyproject.toml mcps/uv.lock ./
COPY mcps/src ./src
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8001

CMD ["uv", "run", "--frozen", "python", "-m", "trackflow_mcp.server"]