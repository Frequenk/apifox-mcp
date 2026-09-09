FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.9.2 /uv /uvx /bin/

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY pyproject.toml uv.lock README.md ./
COPY apifox_mcp/ ./apifox_mcp/
RUN uv sync --frozen --no-dev

ENTRYPOINT ["/app/.venv/bin/python", "-m", "apifox_mcp.main"]
