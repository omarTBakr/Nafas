# dialect-router: CUDA inference image. Build from this directory:
#   docker build -t nafas/dialect-router services/dialect_router
# Runs on CPU too when no GPU is passed in, just slower.

FROM python:3.12-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# dependencies first, from the lockfile alone, so a code change reuses this layer
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra model --no-install-project

COPY dialect_router ./dialect_router
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra model --no-editable

# bake the pinned weights in; the running container never reaches the Hub
RUN python -m dialect_router.download
ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

RUN useradd --system --uid 10001 app
USER app

EXPOSE 8410
HEALTHCHECK --interval=15s --timeout=3s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8410/health', timeout=2)"

CMD ["python", "-m", "dialect_router.main"]
