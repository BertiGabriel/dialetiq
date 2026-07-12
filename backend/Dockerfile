# Multi-stage: uv resolves and installs, but never ships in the runtime image.
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app

# Dependencies first, so a source change does not invalidate the dependency layer.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev


FROM python:3.13-slim-bookworm AS runtime

# Never run as root.
RUN useradd --create-home --uid 1000 app
WORKDIR /app

COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --from=builder --chown=app:app /app/src /app/src

ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
USER app

# The command is overridden per process type (api, worker-transactional,
# worker-bulk). One image, several entrypoints -- see ADR 0002.
CMD ["uvicorn", "dialetiq.entrypoints.api:app", "--host", "0.0.0.0", "--port", "8000"]
